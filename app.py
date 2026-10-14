"""Bashi: shop credit decisions with a receipt that links the exact records used."""
import os

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

import agent
from rules import (CANNOT_TRACE, CANNOT_TRACE_TEXT, RULES, decide, evaluate,
                   fingerprint, naira, read_state, snapshot_of)
from verify import verify_decision
from whatif import get_graph, load_decision, whatif

app = Flask(__name__)
app.jinja_env.filters["cap"] = lambda s: (s[:1].upper() + s[1:]) if s else s
app.jinja_env.filters["naira"] = lambda n: naira(n) if isinstance(n, int) else CANNOT_TRACE_TEXT

LABELS = {"Trade": "Credit sale", "Payment": "Payment", "Promise": "Promise to pay"}


def customers():
    rows = get_graph().query(
        "MATCH (c:Customer) RETURN c.id, c.name, c.credit_limit ORDER BY c.id").result_set
    return [{"id": r[0], "name": r[1], "limit": r[2]} for r in rows]


@app.route("/health")
def health():
    try:
        n = get_graph().query("MATCH (c:Customer) RETURN count(c)").result_set[0][0]
        return jsonify(ok=True, customers=n)
    except Exception as e:  # report, never hide
        return jsonify(ok=False, error=type(e).__name__), 503


def ask_in_words(q):
    """Run the plain-words agent. Receipt links are made relative so they work on any host."""
    try:
        r = agent.ask(q, graph=get_graph())
    except Exception as e:
        return {"text": "Bashi could not answer right now (%s). Use the form below." % type(e).__name__,
                "verdict": None, "mode": None, "receipt": None}
    text = r["reply"].rsplit("
[answered by:", 1)[0]
    receipt = None
    if r["decision_id"]:
        receipt = url_for("receipt", decision_id=r["decision_id"])
        text = text.replace(r["receipt_url"], receipt)
    return {"text": text, "verdict": r["verdict"], "mode": r["answered_by"], "receipt": receipt,
            "note": r["note"]}


@app.route("/", methods=["GET", "POST"])
def home():
    custs = customers()
    form = {"customer": "C001", "amount": "45000"}
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
    elif request.method == "POST":
        form["customer"] = request.form.get("customer", "C001")
        form["amount"] = request.form.get("amount", "").replace(",", "").replace("N", "").strip()
        if not form["amount"].isdigit() or int(form["amount"]) <= 0:
            error = "Type the amount in naira, for example 45000."
        else:
            result = decide(form["customer"], int(form["amount"]), graph=get_graph())
            result["customer_name"] = next((c["name"] for c in custs if c["id"] == form["customer"]), form["customer"])
            result["request"] = int(form["amount"])
            if result["verdict"] == CANNOT_TRACE:
                error = result["reason"]
                result = None
    return render_template("home.html", custs=custs, form=form, result=result, error=error,
                           answer=answer)


def receipt_data(decision_id):
    g = get_graph()
    dec = load_decision(decision_id, g)
    if dec is None:
        return None
    state = read_state(g, dec["customer_id"])
    out = {"dec": dec, "state": state, "trace_ok": False, "trades": [], "payments": [],
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
    snap = g.query("MATCH (d:Decision {id:$d}) RETURN d.snapshot", {"d": decision_id}).result_set
    ok, problems = verify_decision(
        g, (dec["id"], dec["customer_id"], dec["request"], dec["verdict"],
            dec["fingerprint"], snap[0][0] if snap else None))
    out["verify"] = {"ok": ok, "problems": problems}
    # Possible phantom debt: unlinked payment with the same amount as a still-open sale.
    open_amounts = {t["amount"]: t["id"] for t in out["trades"] if t["open"] > 0 and t["settled"] == 0}
    if open_amounts:
        rows = get_graph().query(
            "MATCH (p:Payment) WHERE NOT (p)-[:SETTLES]->(:Trade) RETURN p.id, p.amount, p.date").result_set
        for pid, amt, date in rows:
            if amt in open_amounts:
                out["orphans"].append({"payment": pid, "amount": amt, "date": date,
                                       "trade": open_amounts[amt]})
    return out


@app.route("/demo")
def demo():
    """Ask Tunde N45,000 fresh and land on the new receipt."""
    res = decide("C001", 45000, graph=get_graph())
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
    return render_template("receipt.html", rules=rules, labels=LABELS, **data)


@app.route("/record/<label>/<rid>")
def record(label, rid):
    if label not in LABELS:
        abort(404)
    g = get_graph()
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
    back = request.args.get("d")
    return render_template("record.html", label=label, rid=rid, kind=LABELS[label],
                           props=props, links=links, back=back)


@app.route("/whatif/<decision_id>", methods=["POST"])
def whatif_route(decision_id):
    ids = request.get_json(silent=True) or {}
    try:
        res = whatif(decision_id, ids.get("remove", []))
    except ValueError:
        return jsonify(error="unknown decision"), 404
    except Exception as e:
        return jsonify(error="what-if failed: " + type(e).__name__), 500
    return jsonify(res)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
