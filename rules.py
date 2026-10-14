"""Bashi credit rule check. Fixed rules only, no AI in the decision.

decide() reads a customer's trades, payments and promises, applies two rules,
and stores a Decision node linked to every record it read, with a sha256
fingerprint so verify.py can replay it later.
"""
import hashlib
import json
import sys
from datetime import datetime, timezone

RULES = {
    "R_LIMIT": "Say NO if open debt plus the new request is above the credit limit.",
    "R_BROKEN_PROMISE": "Say NO if the customer has any broken promise to pay.",
}

CANNOT_TRACE = "CANNOT_TRACE"
CANNOT_TRACE_TEXT = "cannot trace this amount"


def naira(n):
    return "N{:,}".format(int(n))


def _is_money(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


# ---------------------------------------------------------------- reading

def read_state(graph, customer_id):
    """Read everything the rule needs. Returns None if the customer is missing.

    state = {customer: {id, limit},
             trades: {id: {amount, date}},
             payments: {id: {amount, date}},
             settles: {"P0001>T0001": amount},
             promises: {id: {amount, due, kept, broke}}}
    """
    p = {"cid": customer_id}
    rows = graph.query(
        "MATCH (c:Customer {id:$cid}) RETURN c.id, c.credit_limit", p
    ).result_set
    if not rows:
        return None
    state = {
        "customer": {"id": rows[0][0], "limit": rows[0][1]},
        "trades": {}, "payments": {}, "settles": {}, "promises": {},
    }
    rows = graph.query(
        "MATCH (c:Customer {id:$cid})-[:MADE]->(t:Trade) "
        "OPTIONAL MATCH (p:Payment)-[s:SETTLES]->(t) "
        "RETURN t.id, t.amount, t.date, p.id, p.amount, p.date, s.amount", p
    ).result_set
    for tid, tamt, tdate, pid, pamt, pdate, samt in rows:
        state["trades"][tid] = {"amount": tamt, "date": tdate}
        if pid is not None:
            state["payments"][pid] = {"amount": pamt, "date": pdate}
            state["settles"]["%s>%s" % (pid, tid)] = samt
    rows = graph.query(
        "MATCH (c:Customer {id:$cid})-[:PROMISED]->(pr:Promise) "
        "RETURN pr.id, pr.amount, pr.due, pr.kept", p
    ).result_set
    for prid, amt, due, kept in rows:
        state["promises"][prid] = {"amount": amt, "due": due, "kept": kept, "broke": False}
    rows = graph.query(
        "MATCH (c:Customer {id:$cid})-[:BROKE]->(pr:Promise) "
        "RETURN pr.id, pr.amount, pr.due, pr.kept", p
    ).result_set
    for prid, amt, due, kept in rows:
        rec = state["promises"].setdefault(
            prid, {"amount": amt, "due": due, "kept": kept, "broke": True})
        rec["broke"] = True
    return state


# ---------------------------------------------------------------- the rule

def evaluate(state, request_amount):
    """Pure rule check on a state. No database access, no randomness."""
    if not _is_money(request_amount) or request_amount <= 0:
        return _untraceable("the request amount is not a valid number")
    limit = state["customer"]["limit"]
    if not _is_money(limit):
        return _untraceable("the credit limit is missing")
    for tid, t in state["trades"].items():
        if not _is_money(t["amount"]):
            return _untraceable("trade %s has no valid amount" % tid)
    for pid, p in state["payments"].items():
        if not _is_money(p["amount"]):
            return _untraceable("payment %s has no valid amount" % pid)
    settled_by_trade, settled_by_pay = {}, {}
    for key, amt in state["settles"].items():
        pid, tid = key.split(">")
        if not _is_money(amt):
            return _untraceable("link %s has no valid amount" % key)
        settled_by_trade[tid] = settled_by_trade.get(tid, 0) + amt
        settled_by_pay[pid] = settled_by_pay.get(pid, 0) + amt
    for tid, s in settled_by_trade.items():
        if s > state["trades"][tid]["amount"]:
            return _untraceable("payments on trade %s add up to more than the trade" % tid)
    for pid, s in settled_by_pay.items():
        if s > state["payments"][pid]["amount"]:
            return _untraceable("payment %s is used for more than it paid" % pid)

    total = sum(t["amount"] for t in state["trades"].values())
    open_debt = total - sum(state["settles"].values())
    broken = sorted(k for k, v in state["promises"].items() if v["broke"])
    over = open_debt + request_amount > limit
    reasons = []
    if over:
        reasons.append(
            "open debt %s plus request %s is %s, above the limit %s"
            % (naira(open_debt), naira(request_amount),
               naira(open_debt + request_amount), naira(limit)))
    if broken:
        reasons.append("broken promise%s: %s" % ("s" if len(broken) > 1 else "", ", ".join(broken)))
    if reasons:
        verdict, reason = "NO", "; ".join(reasons)
    else:
        verdict = "YES"
        reason = ("open debt %s plus request %s is %s, within the limit %s, "
                  "and no broken promises"
                  % (naira(open_debt), naira(request_amount),
                     naira(open_debt + request_amount), naira(limit)))
    return {
        "verdict": verdict, "reason": reason, "open_debt": open_debt,
        "limit": limit, "broken_promises": broken,
        "rules_failed": (["R_LIMIT"] if over else []) + (["R_BROKEN_PROMISE"] if broken else []),
    }


def _untraceable(why):
    return {"verdict": CANNOT_TRACE, "reason": "%s (%s)" % (CANNOT_TRACE_TEXT, why),
            "open_debt": None, "limit": None, "broken_promises": [], "rules_failed": []}


def possible_phantoms(graph, state):
    """Open trades that an unlinked payment of the same size probably paid.

    Never changes the debt. It is only a warning, so the shop owner can link
    the payment by hand."""
    open_by_trade = {}
    for key, amt in state["settles"].items():
        tid = key.split(">")[1]
        open_by_trade[tid] = open_by_trade.get(tid, 0) + amt
    open_trades = {tid: t for tid, t in state["trades"].items()
                   if t["amount"] - open_by_trade.get(tid, 0) > 0
                   and isinstance(t["amount"], int)}
    if not open_trades:
        return []
    orphans = graph.query(
        "MATCH (p:Payment) WHERE NOT (p)-[:SETTLES]->() RETURN p.id, p.amount, p.date").result_set
    found = []
    for tid, t in sorted(open_trades.items()):
        left = t["amount"] - open_by_trade.get(tid, 0)
        for pid, pamt, pdate in orphans:
            if pamt == left and (pdate or "") >= (t["date"] or ""):
                found.append({"trade": tid, "payment": pid, "amount": left})
    return found


# ---------------------------------------------------------------- fingerprint

def evidence_list(state):
    out = [{"label": "Trade", "id": i} for i in sorted(state["trades"])]
    out += [{"label": "Payment", "id": i} for i in sorted(state["payments"])]
    out += [{"label": "Promise", "id": i} for i in sorted(state["promises"])]
    return out


def snapshot_of(state):
    """Flat canonical view of every record read, used for fingerprint and diff."""
    snap = {"Customer:%s" % state["customer"]["id"]: {"limit": state["customer"]["limit"]}}
    for i, v in state["trades"].items():
        snap["Trade:" + i] = dict(v)
    for i, v in state["payments"].items():
        snap["Payment:" + i] = dict(v)
    for i, v in state["promises"].items():
        snap["Promise:" + i] = dict(v)
    for k, v in state["settles"].items():
        snap["Settles:" + k] = {"amount": v}
    return snap


def fingerprint(snapshot, verdict, request_amount):
    lines = []
    for key, fields in snapshot.items():
        parts = ["%s=%s" % (f, json.dumps(fields[f])) for f in sorted(fields)]
        lines.append("%s:%s" % (key, "|".join(parts)))
    lines.sort()
    lines.append("verdict:%s" % verdict)
    lines.append("request:%s" % request_amount)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- saving

def _next_decision_id(graph):
    rows = graph.query("MATCH (d:Decision) RETURN d.id").result_set
    nums = [int(r[0][1:]) for r in rows if r[0] and r[0][1:].isdigit()]
    return "D%04d" % (max(nums, default=0) + 1)


def _save(graph, customer_id, request_amount, state, result, fp, snap):
    did = _next_decision_id(graph)
    for rid, text in RULES.items():
        graph.query("MERGE (r:Rule {id:$id}) ON CREATE SET r.text=$text",
                    {"id": rid, "text": text})
    graph.query(
        "MATCH (c:Customer {id:$cid}) "
        "CREATE (d:Decision {id:$did, customer_id:$cid, request:$req, verdict:$v, "
        "reason:$reason, created:$created, fingerprint:$fp, rule_ids:$rids, "
        "snapshot:$snap, open_debt:$debt}) "
        "CREATE (d)-[:ABOUT]->(c)",
        {"cid": customer_id, "did": did, "req": request_amount, "v": result["verdict"],
         "reason": result["reason"],
         "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "fp": fp, "rids": json.dumps(sorted(RULES)),
         "snap": json.dumps(snap, sort_keys=True), "debt": result["open_debt"]})
    for ev in evidence_list(state):
        graph.query(
            "MATCH (d:Decision {id:$did}), (e:%s {id:$eid}) "
            "CREATE (d)-[:USED_EVIDENCE]->(e)" % ev["label"],
            {"did": did, "eid": ev["id"]})
    for rid in RULES:
        graph.query("MATCH (d:Decision {id:$did}), (r:Rule {id:$rid}) "
                    "CREATE (d)-[:APPLIED_RULE]->(r)", {"did": did, "rid": rid})
    return did


def decide(customer_id, request_amount, graph=None, save=True):
    if graph is None:
        from db import get_graph
        graph = get_graph()
    state = read_state(graph, customer_id)
    if state is None:
        return {"verdict": CANNOT_TRACE, "reason": "%s (no customer %s)" % (CANNOT_TRACE_TEXT, customer_id),
                "open_debt": None, "limit": None, "broken_promises": [], "evidence": [],
                "decision_id": None, "fingerprint": None}
    result = evaluate(state, request_amount)
    out = {
        "verdict": result["verdict"], "reason": result["reason"],
        "open_debt": result["open_debt"], "limit": result["limit"],
        "broken_promises": result["broken_promises"],
        "evidence": evidence_list(state), "decision_id": None, "fingerprint": None,
        "possible_phantoms": [],
    }
    if result["verdict"] == CANNOT_TRACE:
        return out  # never saved, never given a number
    out["possible_phantoms"] = possible_phantoms(graph, state)
    snap = snapshot_of(state)
    out["fingerprint"] = fingerprint(snap, result["verdict"], request_amount)
    if save:
        out["decision_id"] = _save(graph, customer_id, request_amount, state,
                                   result, out["fingerprint"], snap)
    return out


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) != 2 or not args[1].lstrip("-").isdigit():
        print("usage: python rules.py C001 45000 [--no-save]")
        return 2
    r = decide(args[0], int(args[1]), save="--no-save" not in argv)
    print("Verdict:      %s" % r["verdict"])
    print("Why:          %s" % r["reason"])
    if r["open_debt"] is not None:
        print("Open debt:    %s   Limit: %s" % (naira(r["open_debt"]), naira(r["limit"])))
    if r["broken_promises"]:
        print("Broken:       %s" % ", ".join(r["broken_promises"]))
    print("Records read: %d (%s)" % (len(r["evidence"]),
          ", ".join("%s %s" % (e["label"], e["id"]) for e in r["evidence"][:6]) +
          (" ..." if len(r["evidence"]) > 6 else "")))
    for ph in r.get("possible_phantoms", []):
        print("Warning:      Trade %s (%s) is counted as owed, but unlinked Payment %s has the same "
              "amount. Debt left as recorded; link the payment if it belongs." % (ph["trade"], naira(ph["amount"]), ph["payment"]))
    if r["decision_id"]:
        print("Saved as:     %s   Fingerprint: %s" % (r["decision_id"], r["fingerprint"][:16]))
    return 0 if r["verdict"] in ("YES", "NO") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
