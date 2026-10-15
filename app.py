"""Bashi: shop credit decisions with a receipt that links the exact records used."""
import os
import threading
import time
from collections import deque

from flask import Flask, abort, jsonify, make_response, redirect, render_template, request, url_for

import agent
from db import DEFAULT_GRAPH, OWN_GRAPH
from own_shop import EXPLAINER as OWN_EXPLAINER
from own_shop import LABEL_TEXT as OWN_LABEL
from own_shop import TAG, find_demo_case, find_real_case
from rules import (CANNOT_TRACE, CANNOT_TRACE_TEXT, RULES, decide, evaluate,
                   fingerprint, naira, prune_decisions, read_state, snapshot_of)
from verify import verify_decision
from whatif import get_graph, load_decision, whatif

app = Flask(__name__)
app.jinja_env.filters["cap"] = lambda s: (s[:1].upper() + s[1:]) if s else s
app.jinja_env.filters["naira"] = lambda n: naira(n) if isinstance(n, int) else CANNOT_TRACE_TEXT

# ---------------------------------------------------------------- write limits
# Every route that writes or spends the model key goes through this. In memory,
# so it resets when the site restarts. Behind Render the visitor's address
# comes from X-Forwarded-For, which a determined caller can fake, so there is
# also one limit for the whole site.
WINDOW = 600            # seconds
PER_IP_LIMIT = 20       # writes per window per visitor
SITE_LIMIT = 200        # writes per window across everyone
_hits = {}
_site_hits = deque()
_hits_lock = threading.Lock()


def reset_limits():
    with _hits_lock:
        _hits.clear()
        _site_hits.clear()


def client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() or request.remote_addr or "unknown")


def too_many_writes():
    """Count one write for this visitor. True if they are over the limit."""
    now = time.time()
    with _hits_lock:
        q = _hits.setdefault(client_ip(), deque())
        while q and now - q[0] > WINDOW:
            q.popleft()
        while _site_hits and now - _site_hits[0] > WINDOW:
            _site_hits.popleft()
        if len(q) >= PER_IP_LIMIT or len(_site_hits) >= SITE_LIMIT:
            return True
        q.append(now)
        _site_hits.append(now)
        if len(_hits) > 5000:   # drop visitors with nothing recent
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > WINDOW]:
                del _hits[k]
        return False


def slow_down():
    if request.path.startswith("/whatif/"):
        return jsonify(error="Too many requests from you just now. Wait a few minutes and try again."), 429
    return render_template("slow.html"), 429


# ---------------------------------------------------------------- which shop
# The demo shop (synthetic) is the default. The visitor can switch to the
# founder's own shop (names removed); the choice is kept in a cookie.
SHOP_COOKIE = "bashi_shop"
GRAPH_OF = {"demo": DEFAULT_GRAPH, "own": OWN_GRAPH}
_own_seen = {"at": 0.0, "ok": False}


def own_available():
    """True when the own-shop graph exists and holds own-shop customers. Checked at most every 30 seconds."""
    now = time.time()
    if now - _own_seen["at"] > 30:
        _own_seen["at"] = now
        try:
            rows = get_graph(OWN_GRAPH).query(
                "MATCH (c:Customer {own_shop:true}) RETURN count(c)").result_set
            _own_seen["ok"] = bool(rows) and rows[0][0] > 0
        except Exception:
            _own_seen["ok"] = False
    return _own_seen["ok"]


def shop_key():
    """The own shop is the default whenever it is loaded. Anyone can pick the practice
    shop instead. If the own shop is missing or empty, everyone gets the practice shop."""
    if request.cookies.get(SHOP_COOKIE) == "demo":
        return "demo"
    return "own" if own_available() else "demo"


def cur_graph():
    return get_graph(GRAPH_OF[shop_key()])


def graph_for_decision(decision_id):
    """The graph that holds this receipt: the chosen shop first, then the other one."""
    first = shop_key()
    order = [first] + [k for k in ("demo", "own") if k != first and (k == "demo" or own_available())]
    for k in order:
        try:
            g = get_graph(GRAPH_OF[k])
            if load_decision(decision_id, g) is not None:
                return k, g
        except Exception:
            continue
    return first, get_graph(GRAPH_OF[first])


@app.context_processor
def shop_context():
    key = shop_key()
    return {"shop": {"key": key, "own": key == "own", "own_available": own_available(),
                     "label": OWN_LABEL if key == "own" else "Demo data, all synthetic",
                     "explainer": OWN_EXPLAINER if key == "own" else None}}


@app.route("/shop", methods=["POST"])
def choose_shop():
    resp = make_response(redirect(url_for("home")))
    want = "own" if request.form.get("shop") == "own" and own_available() else "demo"
    resp.set_cookie(SHOP_COOKIE, want, max_age=60 * 60 * 24 * 30, samesite="Lax")
    return resp


def store_decision_cap():
    try:
        prune_decisions(cur_graph())
    except Exception:
        pass


LABELS = {"Trade": "Credit sale", "Payment": "Payment", "Promise": "Promise to pay"}


def customers():
    rows = cur_graph().query(
        "MATCH (c:Customer) RETURN c.id, c.name, c.credit_limit, c.source ORDER BY c.id").result_set
    return [{"id": r[0], "name": r[1], "limit": r[2], "tag": TAG.get(r[3])} for r in rows]


@app.route("/health")
def health():
    """Healthy when at least one shop graph answers. Reports each shop's customer count."""
    out, errors = {}, []
    for key, name in GRAPH_OF.items():
        try:
            out[key] = get_graph(name).query("MATCH (c:Customer) RETURN count(c)").result_set[0][0]
        except Exception as e:  # report, never hide
            if key == "demo":
                errors.append(type(e).__name__)
    if out.get("demo") is None and not out.get("own"):
        return jsonify(ok=False, error=(errors or ["EmptyGraph"])[0]), 503
    return jsonify(ok=True, customers=out.get("demo", 0), own_customers=out.get("own", 0))


def ask_in_words(q):
    """Run the plain-words agent. Receipt links are made relative so they work on any host."""
    try:
        r = agent.ask(q, graph=cur_graph())
    except Exception as e:
        return {"text": "Bashi could not answer right now (%s). Use the form below." % type(e).__name__,
                "verdict": None, "mode": None, "receipt": None}
    text = r["reply"].rsplit("\n[answered by:", 1)[0]
    receipt = None
    if r["decision_id"]:
        receipt = url_for("receipt", decision_id=r["decision_id"])
        text = text.replace(r["receipt_url"], receipt)
    return {"text": text, "verdict": r["verdict"], "mode": r["answered_by"], "receipt": receipt,
            "note": r["note"]}


@app.route("/", methods=["GET", "POST"])
def home():
    custs = customers()
    form = {"customer": custs[0]["id"] if custs else "C001", "amount": "45000"}
    if request.method == "POST" and too_many_writes():
        return slow_down()
    result = None
    error = None
    answer = None
    if request.method == "POST" and "q" in request.form:
        q = request.form.get("q", "").strip()[:300]
        form["q"] = q
        if not q:
            error = "Type a question, for example: Can Tunde take N45,000 on credit?"
        else:
            answer = ask_in_words(q)
            store_decision_cap()
    elif request.method == "POST":
        form["customer"] = request.form.get("customer", form["customer"])
        form["amount"] = request.form.get("amount", "").replace(",", "").replace("N", "").strip()
        if not form["amount"].isdigit() or int(form["amount"]) <= 0:
            error = "Type the amount in naira, for example 45000."
        else:
            result = decide(form["customer"], int(form["amount"]), graph=cur_graph())
            store_decision_cap()
            result["customer_name"] = next((c["name"] for c in custs if c["id"] == form["customer"]), form["customer"])
            result["request"] = int(form["amount"])
            if result["verdict"] == CANNOT_TRACE:
                error = result["reason"]
                result = None
    return render_template("home.html", custs=custs, form=form, result=result, error=error,
                           answer=answer)


def receipt_data(decision_id):
    _, g = graph_for_decision(decision_id)
    dec = load_decision(decision_id, g)
    if dec is None:
        return None
    state = read_state(g, dec["customer_id"], as_of=dec["as_of"])
    src = g.query("MATCH (c:Customer {id:$c}) RETURN c.source", {"c": dec["customer_id"]}).result_set
    out = {"dec": dec, "state": state, "tag": TAG.get(src[0][0]) if src else None, "trace_ok": False, "trades": [], "payments": [],
           "promises": [], "orphans": [], "verify": None, "open_debt": None}
    if state is None:
        return out
    ev = evaluate(state, dec["request"])
    out["trace_ok"] = ev["verdict"] != CANNOT_TRACE
    out["open_debt"] = ev["open_debt"]
    settled = {}
    pays_for = {}
    for key, amt in state["settles"].items():
        pid, tid = key.split(">")
        settled[tid] = settled.get(tid, 0) + amt
        pays_for.setdefault(tid, []).append({"id": pid, "amount": amt})
    for tid in sorted(state["trades"]):
        t = state["trades"][tid]
        s = settled.get(tid, 0)
        out["trades"].append({"id": tid, "amount": t["amount"], "date": t["date"],
                              "settled": s, "open": t["amount"] - s, "pays": pays_for.get(tid, [])})
    for pid in sorted(state["payments"]):
        out["payments"].append({"id": pid, **state["payments"][pid]})
    for prid in sorted(state["promises"]):
        out["promises"].append({"id": prid, **state["promises"][prid]})
    # Same check as verify.py: one shared function, no second copy of the logic.
    # The snapshot came with the decision, and the records were read above on
    # the same day verify would use, so neither is fetched a second time.
    ok, problems = verify_decision(
        g, (dec["id"], dec["customer_id"], dec["request"], dec["verdict"],
            dec["fingerprint"], dec["snapshot"]), state=state)
    out["verify"] = {"ok": ok, "problems": problems}
    # Possible phantom debt: unlinked payment with the same amount as a still-open sale.
    open_amounts = {t["amount"]: t["id"] for t in out["trades"] if t["open"] > 0 and t["settled"] == 0}
    if open_amounts:
        rows = g.query(
            "MATCH (p:Payment) WHERE NOT (p)-[:SETTLES]->(:Trade) RETURN p.id, p.amount, p.date").result_set
        for pid, amt, date in rows:
            if amt in open_amounts:
                out["orphans"].append({"payment": pid, "amount": amt, "date": date,
                                       "trade": open_amounts[amt]})
    return out


@app.route("/demo", methods=["GET", "POST"])
def demo():
    """Ask Tunde N45,000 fresh and land on the new receipt. Writes, so POST only."""
    if request.method != "POST":
        return redirect(url_for("home"))
    if too_many_writes():
        return slow_down()
    case = None
    if shop_key() == "own":
        try:
            case = find_demo_case(cur_graph(), only_source="invented")
        except Exception:
            case = None
    if case:
        g = cur_graph()
        res = decide(case["customer"], case["amount"], graph=g)
        hint = case["remove"]
    else:   # practice shop: the Tunde case, flipped by removing his broken promise
        g = get_graph(DEFAULT_GRAPH)
        res = decide("C001", 45000, graph=g)
        hint = "PR001"
    try:
        prune_decisions(g)
    except Exception:
        pass
    if not res.get("decision_id"):
        return render_template("gone.html", decision_id=None), 503
    return redirect(url_for("receipt", decision_id=res["decision_id"], **{"try": hint}))


@app.route("/demo/real", methods=["GET", "POST"])
def demo_real():
    """Open the receipt for the real-audit customer with the most phantom debt. Own shop only."""
    if request.method != "POST" or shop_key() != "own":
        return redirect(url_for("home"))
    if too_many_writes():
        return slow_down()
    g = cur_graph()
    try:
        case = find_real_case(g)
    except Exception:
        case = None
    if not case:
        return redirect(url_for("home"))
    res = decide(case["customer"], case["amount"], graph=g)
    try:
        prune_decisions(g)
    except Exception:
        pass
    if not res.get("decision_id"):
        return render_template("gone.html", decision_id=None), 503
    return redirect(url_for("receipt", decision_id=res["decision_id"]))


@app.route("/receipt/<decision_id>")
def receipt(decision_id):
    data = receipt_data(decision_id)
    if data is None:
        return render_template("gone.html", decision_id=decision_id), 404
    rules = [{"id": r, "text": RULES.get(r, "")} for r in
             __import__("json").loads(data["dec"]["rule_ids"] or "[]")]
    ids = {x["id"] for k in ("trades", "payments", "promises") for x in data[k]}
    hint = request.args.get("try")
    return render_template("receipt.html", rules=rules, labels=LABELS,
                           hint=hint if hint in ids else None, **data)


@app.route("/record/<label>/<rid>")
def record(label, rid):
    if label not in LABELS:
        abort(404)
    back = request.args.get("d")
    g = graph_for_decision(back)[1] if back else cur_graph()
    rows = g.query("MATCH (n:%s {id:$i}) RETURN properties(n)" % label, {"i": rid}).result_set
    if not rows:
        abort(404)
    props = rows[0][0]
    links = []
    if label == "Trade":
        q = ("MATCH (c:Customer)-[:MADE]->(t:Trade {id:$i}) "
             "OPTIONAL MATCH (p:Payment)-[s:SETTLES]->(t) RETURN c.name, c.id, p.id, p.amount, p.date, s.amount")
        for name, cid, pid, pamt, pdate, samt in g.query(q, {"i": rid}).result_set:
            props["customer"] = name
            if pid:
                links.append({"label": "Payment", "id": pid, "amount": pamt, "date": pdate, "applied": samt})
    elif label == "Payment":
        q = ("MATCH (p:Payment {id:$i}) OPTIONAL MATCH (p)-[s:SETTLES]->(t:Trade)<-[:MADE]-(c:Customer) "
             "RETURN t.id, t.amount, t.date, s.amount, c.name")
        for tid, tamt, tdate, samt, name in g.query(q, {"i": rid}).result_set:
            if tid:
                props["customer"] = name
                links.append({"label": "Trade", "id": tid, "amount": tamt, "date": tdate, "applied": samt})
    else:
        q = "MATCH (c:Customer)-[:PROMISED]->(p:Promise {id:$i}) RETURN c.name"
        r = g.query(q, {"i": rid}).result_set
        if r:
            props["customer"] = r[0][0]
    return render_template("record.html", label=label, rid=rid, kind=LABELS[label],
                           props=props, links=links, back=back)


@app.route("/whatif/<decision_id>", methods=["POST"])
def whatif_route(decision_id):
    if too_many_writes():
        return slow_down()
    ids = request.get_json(silent=True) or {}
    try:
        res = whatif(decision_id, ids.get("remove", []),
                     graph_name=GRAPH_OF[graph_for_decision(decision_id)[0]])
    except ValueError:
        return jsonify(error="unknown decision"), 404
    except Exception as e:
        return jsonify(error="what-if failed: " + type(e).__name__), 500
    return jsonify(res)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
