"""Bashi: shop credit decisions with a receipt that links the exact records used."""
import os
import threading
import time
from collections import deque

from flask import (Flask, abort, jsonify, make_response, redirect, render_template, request,
                   send_from_directory, url_for)

import agent
import agent_api
from db import DEFAULT_GRAPH, OWN_GRAPH
from own_shop import EXPLAINER as OWN_EXPLAINER
from own_shop import LABEL_TEXT as OWN_LABEL
from own_shop import TAG, find_demo_case, find_real_case
from linking import biggest_gap_case
from real_shop import REAL_GRAPH
from rules import (CANNOT_TRACE, CANNOT_TRACE_TEXT, RULES, decide, evaluate,
                   fingerprint, naira, prune_decisions, read_state, snapshot_of)
from verify import verify_decision
from whatif import get_graph, load_decision, whatif

ROOT = os.path.dirname(os.path.abspath(__file__))
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


READ_LIMIT = 120        # lighter limit for the read-only agent routes, per visitor per window
_read_hits = {}


def reset_limits():
    with _hits_lock:
        _hits.clear()
        _site_hits.clear()
        _read_hits.clear()
    _case_cache.clear()


# ---------------------------------------------------------------- demo case cache
# Finding the demo case reads every customer one by one (about 8 seconds on the
# free database). The answer only changes when the data is reloaded, so keep it
# for ten minutes. The decision itself is always made fresh.
CASE_TTL = 600
_case_cache = {}


def cached_case(graph_name, finder, *args, **kwargs):
    key = (graph_name, finder, tuple(sorted(kwargs.items())))
    hit = _case_cache.get(key)
    if hit and time.time() - hit[0] < CASE_TTL:
        return dict(hit[1])
    case = finder(*args, **kwargs)
    if case:
        _case_cache[key] = (time.time(), dict(case))
    return case


def demo_case(g, name):
    return cached_case(name, find_demo_case, g, only_source="invented")


def real_case(g, name, real):
    return cached_case(name, biggest_gap_case if real else find_real_case, g)


def warm_cases():
    """Fill the cache in the background so the first visitor's click is fast."""
    def run():
        for k in ("own", "real"):
            try:
                g = get_graph(GRAPH_OF[k])
                if k == "own":
                    demo_case(g, GRAPH_OF[k])
                real_case(g, GRAPH_OF[k], k == "real")
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


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


def too_many_reads():
    """A lighter limit for read-only agent routes (receipts, checks, lists)."""
    now = time.time()
    with _hits_lock:
        q = _read_hits.setdefault(client_ip(), deque())
        while q and now - q[0] > WINDOW:
            q.popleft()
        if len(q) >= READ_LIMIT:
            return True
        q.append(now)
        if len(_read_hits) > 5000:
            for k in [k for k, v in _read_hits.items() if not v or now - v[-1] > WINDOW]:
                del _read_hits[k]
        return False


def slow_down():
    if request.path.startswith("/whatif/"):
        return jsonify(error="Too many requests from you just now. Wait a few minutes and try again."), 429
    return render_template("slow.html"), 429


# ---------------------------------------------------------------- which shop
# The demo shop (synthetic) is the default. The visitor can switch to the
# founder's own shop (names removed); the choice is kept in a cookie.
SHOP_COOKIE = "bashi_shop"
GRAPH_OF = {"demo": DEFAULT_GRAPH, "own": OWN_GRAPH, "real": REAL_GRAPH}
_own_seen = {"at": 0.0, "ok": False}
_real_seen = {"at": 0.0, "ok": False}
REAL_LABEL = "Real shop, names removed. Payment-to-sale links are inferred by rule, not confirmed"
REAL_EXPLAINER = ("The whole record of a real shop that sells on credit, with names, phones and notes removed: "
                  "45 customers, 544 credit sales and 543 payments. The shop records each payment against the "
                  "customer, never against a sale, so nothing says which sale a payment cleared. Bashi matches "
                  "them by rule (a payment of the exact amount first, otherwise the oldest sale first, never a "
                  "sale dated after the payment) and saves each match in the graph marked inferred. "
                  "Credit limits are assumed.")


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


def real_available():
    """True when the real-shop graph is loaded. Checked at most every 30 seconds."""
    now = time.time()
    if now - _real_seen["at"] > 30:
        _real_seen["at"] = now
        try:
            rows = get_graph(REAL_GRAPH).query(
                "MATCH (c:Customer {own_shop:true}) RETURN count(c)").result_set
            _real_seen["ok"] = bool(rows) and rows[0][0] > 0
        except Exception:
            _real_seen["ok"] = False
    return _real_seen["ok"]


def shop_key():
    """The own shop is the default whenever it is loaded. Anyone can pick the practice
    shop instead. If the own shop is missing or empty, everyone gets the practice shop."""
    if request.cookies.get(SHOP_COOKIE) == "demo":
        return "demo"
    if request.cookies.get(SHOP_COOKIE) == "real" and real_available():
        return "real"
    return "own" if own_available() else "demo"


def cur_graph():
    return get_graph(GRAPH_OF[shop_key()])


def graph_for_decision(decision_id):
    """The graph that holds this receipt: the chosen shop first, then the other one."""
    first = shop_key()
    order = [first] + [k for k in ("demo", "own", "real") if k != first and (
        k == "demo" or (k == "own" and own_available()) or (k == "real" and real_available()))]
    for k in order:
        try:
            g = get_graph(GRAPH_OF[k])
            if load_decision(decision_id, g) is not None:
                return k, g
        except Exception:
            continue
    return first, get_graph(GRAPH_OF[first])


PRACTICE_LABEL = "Demo data, all synthetic"
INVENTED_LABEL = "Invented customer, not real data"


def banner_for(shop, source):
    """The banner for a page about one record. The real-audit banner is only for real customers;
    invented customers get their own label; a receipt from the practice shop gets the practice one."""
    if shop == "real":
        return REAL_LABEL
    if shop != "own":
        return PRACTICE_LABEL
    return INVENTED_LABEL if source == "invented" else OWN_LABEL


@app.context_processor
def shop_context():
    key = shop_key()
    return {"shop": {"key": key, "own": key == "own", "real": key == "real",
                     "ownlike": key in ("own", "real"),
                     "own_available": own_available(), "real_available": real_available(),
                     "label": REAL_LABEL if key == "real" else OWN_LABEL if key == "own" else PRACTICE_LABEL,
                     "explainer": REAL_EXPLAINER if key == "real" else OWN_EXPLAINER if key == "own" else None}}


@app.route("/shop", methods=["POST"])
def choose_shop():
    resp = make_response(redirect(url_for("home")))
    pick = request.form.get("shop")
    want = ("own" if pick == "own" and own_available()
            else "real" if pick == "real" and real_available() else "demo")
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
    return jsonify(ok=True, customers=out.get("demo", 0), own_customers=out.get("own", 0),
                   real_customers=out.get("real", 0))


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
    shop, g = graph_for_decision(decision_id)
    return build_receipt(shop, g, decision_id)


def build_receipt(shop, g, decision_id):
    """The receipt for one decision, read from the graph `g` of shop `shop`.
    Shared by the receipt page, the JSON routes and the MCP tools."""
    dec = load_decision(decision_id, g)
    if dec is None:
        return None
    state = read_state(g, dec["customer_id"], as_of=dec["as_of"])
    src = g.query("MATCH (c:Customer {id:$c}) RETURN c.source", {"c": dec["customer_id"]}).result_set
    source = src[0][0] if src else None
    out = {"dec": dec, "state": state, "tag": TAG.get(source), "banner": banner_for(shop, source),
           "trace_ok": False, "trades": [], "payments": [],
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
        pays_for.setdefault(tid, []).append({"id": pid, "amount": amt,
                                             "method": state.get("inferred", {}).get(key)})
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
    out["inferred_count"] = len(state.get("inferred", {}))
    out["deposits"] = sum(state["settles"][k] for k, m in state.get("inferred", {}).items() if m == "deposit")
    out["unapplied"] = None
    if out["inferred_count"]:
        # Money this customer paid that no sale could use (paid before the sale, or more than
        # was owed). It is shown, never used to clear a later sale.
        try:
            paid = g.query("MATCH (:Customer {id:$c})-[:PAID]->(p:Payment) RETURN sum(p.amount)",
                           {"c": dec["customer_id"]}).result_set[0][0] or 0
            out["unapplied"] = int(max(0, paid - sum(state["settles"].values())))
        except Exception:
            out["unapplied"] = None
    # Possible phantom debt: unlinked payment with the same amount as a still-open sale.
    open_amounts = {t["amount"]: t["id"] for t in out["trades"] if t["open"] > 0 and t["settled"] == 0}
    if open_amounts and shop == "real":
        rows = g.query(
            "MATCH (:Customer {id:$c})-[:PAID]->(p:Payment) WHERE NOT (p)-[:SETTLES]->() "
            "AND NOT (p)-[:INFERRED_SETTLES]->() RETURN p.id, p.amount, p.date",
            {"c": dec["customer_id"]}).result_set
        for pid, amt, date in rows:
            if amt in open_amounts:
                out["orphans"].append({"payment": pid, "amount": amt, "date": date,
                                       "trade": open_amounts[amt]})
    elif open_amounts:
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
    if shop_key() == "real":
        return redirect(url_for("home"))
    if shop_key() == "own":
        try:
            case = demo_case(cur_graph(), GRAPH_OF["own"])
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
    if request.method != "POST" or shop_key() not in ("own", "real"):
        return redirect(url_for("home"))
    if too_many_writes():
        return slow_down()
    g = cur_graph()
    try:
        case = real_case(g, GRAPH_OF[shop_key()], shop_key() == "real")
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


if os.environ.get("RENDER"):
    warm_cases()


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
    shop = graph_for_decision(back)[0] if back else shop_key()
    return render_template("record.html", label=label, rid=rid, kind=LABELS[label],
                           props=props, links=links, back=back,
                           banner=banner_for(shop, props.get("source")))


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


# ---------------------------------------------------------------- agent door
# Plain JSON routes and an MCP endpoint for other tools and AI apps. The work
# lives in agent_api.py so the routes and the MCP tools cannot drift apart.

def base_url():
    proto = request.headers.get("X-Forwarded-Proto", request.scheme).split(",")[0].strip()
    return "%s://%s" % (proto if proto in ("http", "https") else request.scheme, request.host)


def api_error(status, message):
    return jsonify(error=message), status


def api_call(fn, write=False, *args, **kw):
    """Run an agent_api function and turn its errors into JSON with the right status."""
    if (too_many_writes() if write else too_many_reads()):
        return api_error(429, "Too many requests from you just now. Wait a few minutes and try again.")
    try:
        return jsonify(fn(*args, **kw))
    except agent_api.ApiError as e:
        return api_error(e.status, e.message)


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith(("/api/", "/mcp")):
        return api_error(404, "Not found.")
    return e


@app.errorhandler(405)
def not_allowed(e):
    if request.path.startswith(("/api/", "/mcp")):
        return api_error(405, "That method is not allowed here.")
    return e


@app.route("/api/decide", methods=["POST"])
def api_decide():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return api_error(400, 'Send a JSON body like {"customer": "C001", "amount": 45000}.')
    try:     # check the input first, so a typo does not use up a write
        agent_api.check_customer(body.get("customer"))
        agent_api.check_amount(body.get("amount"))
        agent_api.resolve_shop(body.get("shop"))
    except agent_api.ApiError as e:
        return api_error(e.status, e.message)
    return api_call(agent_api.decide_credit, True, body.get("customer"), body.get("amount"),
                    body.get("shop"), base_url())


@app.route("/api/receipt/<decision_id>")
def api_receipt(decision_id):
    return api_call(agent_api.get_receipt, False, decision_id, base_url())


@app.route("/api/verify/<decision_id>")
def api_verify(decision_id):
    return api_call(agent_api.verify_decision, False, decision_id)


@app.route("/api/whatif/<decision_id>")
def api_whatif(decision_id):
    try:
        agent_api.check_decision_id(decision_id)
        remove = agent_api.check_remove(
            [p for v in request.args.getlist("remove") for p in v.split(",") if p.strip()])
    except agent_api.ApiError as e:
        return api_error(e.status, e.message)
    return api_call(agent_api.what_if_remove_evidence, True, decision_id, remove)


@app.route("/api/customers")
def api_customers():
    return api_call(agent_api.list_customers, False, request.args.get("shop"))


@app.route("/mcp", methods=["GET", "POST"])
def mcp():
    """MCP over HTTP: JSON-RPC 2.0, one request one reply, no sessions."""
    if request.method == "GET":
        return jsonify(agent_api.server_info(base_url()))
    msg = request.get_json(silent=True)
    if msg is None:
        return jsonify(agent_api._rpc_error(None, -32700, "Parse error")), 400
    if isinstance(msg, list):
        return jsonify(agent_api._rpc_error(None, -32600, "Send one message at a time (no batches)")), 400

    def guard(tool):
        limited = too_many_writes() if tool in agent_api.WRITE_TOOLS else too_many_reads()
        return "Too many requests from you just now. Wait a few minutes and try again." if limited else None

    reply = agent_api.handle_rpc(msg, base_url(), guard)
    if reply is None:
        return "", 202
    return jsonify(reply)


@app.route("/llms.txt")
def llms_txt():
    return send_from_directory(ROOT, "llms.txt", mimetype="text/plain")


@app.route("/AGENTS.md")
def agents_md():
    return send_from_directory(ROOT, "AGENTS.md", mimetype="text/markdown")


# ---------------------------------------------------------------- /proof
# A visitor changes one character of one record on a throwaway copy of the
# shop and watches the receipt check fail. The live graph is only read.

PROOF_COLS = "d.id, d.customer_id, d.request, d.verdict, d.fingerprint, d.snapshot"


def proof_edit_digit(n):
    """Change only the last digit of a whole number."""
    return n - n % 10 + (n % 10 + 1) % 10


def proof_run(decision_id, graph_name, tamper):
    """Copy the shop, optionally change one digit of one used record, check the
    receipt on the copy, delete the copy. Returns what happened."""
    import uuid
    import whatif as _w
    main = get_graph(graph_name)
    db = _w.get_db()
    _w.sweep_stale_copies(db)
    copy_name = "shop_a_whatif_%s_%d_%s" % (decision_id, int(time.time()), uuid.uuid4().hex[:6])
    out = {"decision_id": decision_id, "changed": None, "copy_deleted": False}
    try:
        main.copy(copy_name)
        cg = db.select_graph(copy_name)
        if tamper:
            rows = cg.query("MATCH (:Decision {id:$i})-[:USED_EVIDENCE]->(e) "
                            "WHERE e.amount IS NOT NULL AND (e:Trade OR e:Payment) "
                            "RETURN labels(e)[0], e.id, e.amount ORDER BY e.id", {"i": decision_id}).result_set
            rows = [r for r in rows if isinstance(r[2], int) and not isinstance(r[2], bool)]
            if not rows:
                raise ValueError("this receipt used no sale or payment amount to change")
            lab, rid, old = rows[0]
            new = proof_edit_digit(old)
            cg.query("MATCH (n:%s {id:$x}) SET n.amount = $a" % lab, {"x": rid, "a": new})
            out["changed"] = {"kind": LABELS[lab], "id": rid, "before": old, "after": new}
        row = cg.query("MATCH (d:Decision {id:$i}) RETURN " + PROOF_COLS, {"i": decision_id}).result_set
        if not row:
            raise ValueError("unknown decision")
        ok, problems = verify_decision(cg, row[0])
        out["passed"] = ok
        out["problems"] = problems
    finally:
        try:
            db.select_graph(copy_name).delete()
            out["copy_deleted"] = True
        except Exception:
            pass
    out["real_graph_untouched"] = True
    return out


@app.route("/proof")
def proof():
    try:
        rows = cur_graph().query(
            "MATCH (d:Decision)-[:ABOUT]->(c:Customer) RETURN d.id, c.name, d.request, d.verdict "
            "ORDER BY d.created DESC LIMIT 12").result_set
    except Exception:
        rows = []
    picks = [{"id": r[0], "name": r[1], "request": r[2], "verdict": r[3]} for r in rows]
    want = request.args.get("d")
    return render_template("proof.html", picks=picks, want=want if want in {p["id"] for p in picks} else None)


@app.route("/proof/run", methods=["POST"])
def proof_route():
    if too_many_writes():
        return slow_down()
    body = request.get_json(silent=True) or {}
    did = body.get("decision")
    if not isinstance(did, str) or not did:
        return jsonify(error="pick a receipt first"), 400
    key, g = graph_for_decision(did)
    try:
        if load_decision(did, g) is None:
            return jsonify(error="unknown receipt"), 404
        return jsonify(proof_run(did, GRAPH_OF[key], body.get("mode") == "tamper"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error="proof check failed: " + type(e).__name__), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
