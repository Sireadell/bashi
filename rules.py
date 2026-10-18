"""Bashi credit rule check. Fixed rules only, no AI in the decision.

decide() reads a customer's trades, payments and promises, applies two rules,
and stores a Decision node linked to every record it read, with a sha256
fingerprint so verify.py can replay it later.
"""
import hashlib
import json
import sys
from datetime import date, datetime, timezone

RULES = {
    "R_LIMIT": "Say NO if open debt plus the new request is above the credit limit.",
    "R_BROKEN_PROMISE": "Say NO if the customer has any broken promise to pay.",
}

COUNTERS = {"decision": ("Decision", "D", 4), "promise": ("Promise", "PR", 3)}
MAX_DECISIONS = 300

CANNOT_TRACE = "CANNOT_TRACE"
CANNOT_TRACE_TEXT = "cannot trace this amount"


def naira(n):
    return "N{:,}".format(int(n))


def _is_money(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


# ---------------------------------------------------------------- reading

def read_state(graph, customer_id, as_of=None):
    """Read everything the rule needs. Returns None if the customer is missing.

    as_of (an ISO date) hides broken-promise links that were only added after
    that date, so a replay or a what-if sees what the decision saw even after
    time has passed. Links with no date (the seeded ones) always count.

    state = {customer: {id, limit},
             trades: {id: {amount, date}},
             payments: {id: {amount, date}},
             settles: {"P0001>T0001": amount},
             promises: {id: {amount, due, kept, broke}}}
    """
    p = {"cid": customer_id}
    # One round trip for everything. Each branch is tagged so the rows can be
    # told apart; columns a..g are filled according to the tag.
    rows = graph.query(
        "MATCH (c:Customer {id:$cid}) "
        "RETURN 'C' AS k, c.id AS a, c.credit_limit AS b, null AS c, null AS d, "
        "null AS e, null AS f, null AS g, null AS h "
        "UNION ALL "
        "MATCH (c:Customer {id:$cid})-[:MADE]->(t:Trade) "
        "OPTIONAL MATCH (p:Payment)-[s:SETTLES]->(t) "
        "RETURN 'T' AS k, t.id AS a, t.amount AS b, t.date AS c, p.id AS d, "
        "p.amount AS e, p.date AS f, s.amount AS g, null AS h "
        "UNION ALL "
        "MATCH (c:Customer {id:$cid})-[:MADE]->(t:Trade)<-[s:INFERRED_SETTLES]-(p:Payment) "
        "RETURN 'I' AS k, t.id AS a, t.amount AS b, t.date AS c, p.id AS d, "
        "p.amount AS e, p.date AS f, s.amount AS g, s.method AS h "
        "UNION ALL "
        "MATCH (c:Customer {id:$cid})-[:PROMISED]->(pr:Promise) "
        "RETURN 'P' AS k, pr.id AS a, pr.amount AS b, pr.due AS c, pr.kept AS d, "
        "null AS e, null AS f, null AS g, null AS h "
        "UNION ALL "
        "MATCH (c:Customer {id:$cid})-[b:BROKE]->(pr:Promise) "
        "RETURN 'B' AS k, pr.id AS a, pr.amount AS b, pr.due AS c, pr.kept AS d, "
        "b.since AS e, null AS f, null AS g, null AS h", p
    ).result_set
    cust = [r for r in rows if r[0] == "C"]
    if not cust:
        return None
    state = {
        "customer": {"id": cust[0][1], "limit": cust[0][2]},
        "trades": {}, "payments": {}, "settles": {}, "promises": {}, "inferred": {},
    }
    for k, tid, tamt, tdate, pid, pamt, pdate, samt, *_ in rows:
        if k != "T":
            continue
        state["trades"][tid] = {"amount": tamt, "date": tdate}
        if pid is not None:
            state["payments"][pid] = {"amount": pamt, "date": pdate}
            state["settles"]["%s>%s" % (pid, tid)] = samt
    # Links proposed by linking.py (a payment matched to a sale by rule, not
    # confirmed by a person). They count toward the debt, and are kept apart in
    # state["inferred"] so every receipt can say which links are inferred.
    for k, tid, tamt, tdate, pid, pamt, pdate, samt, method in rows:
        if k != "I":
            continue
        state["payments"][pid] = {"amount": pamt, "date": pdate}
        state["settles"]["%s>%s" % (pid, tid)] = samt
        state["inferred"]["%s>%s" % (pid, tid)] = method
    for k, prid, amt, due, kept, *_ in rows:
        if k == "P":
            state["promises"][prid] = {"amount": amt, "due": due, "kept": kept, "broke": False}
    for k, prid, amt, due, kept, since, *_ in rows:
        if k != "B":
            continue
        if as_of and since and since > as_of:
            continue
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
    # One round trip: whether payments are tied to customers, this customer's
    # unlinked payments, and (for older graphs) every unlinked payment.
    rows = graph.query(
        "MATCH (:Customer)-[r:PAID]->() RETURN 'N' AS k, count(r) AS a, null AS b, null AS c "
        "UNION ALL "
        "MATCH (:Customer {id:$cid})-[:PAID]->(p:Payment) "
        "WHERE NOT (p)-[:SETTLES]->() AND NOT (p)-[:INFERRED_SETTLES]->() "
        "RETURN 'O' AS k, p.id AS a, p.amount AS b, p.date AS c "
        "UNION ALL "
        "MATCH (p:Payment) WHERE NOT (p)-[:SETTLES]->() "
        "RETURN 'A' AS k, p.id AS a, p.amount AS b, p.date AS c",
        {"cid": state["customer"]["id"]}).result_set
    tied = any(r[0] == "N" and r[1] for r in rows)
    # Payments are tied to customers here, so only this customer's own payments
    # can be a phantom, and a payment already matched by rule is not an orphan.
    orphans = [tuple(r[1:]) for r in rows if r[0] == ("O" if tied else "A")]
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
        rec = {"amount": v}
        if k in state.get("inferred", {}):
            rec["inferred"] = state["inferred"][k]    # tampering with the method is caught too
        snap["Settles:" + k] = rec
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

def _existing_max(graph, label, prefix):
    rows = graph.query("MATCH (n:%s) RETURN n.id" % label).result_set
    n = len(prefix)
    nums = [int(r[0][n:]) for r in rows if r[0] and r[0].startswith(prefix) and r[0][n:].isdigit()]
    return max(nums, default=0)


def allocate_id(graph, kind):
    """Hand out the next id ("D0008", "PR008") without two requests ever getting
    the same one. The counter lives in the graph and is bumped by a single
    query. A graph with no counter yet starts it from the highest id in use."""
    label, prefix, width = COUNTERS[kind]
    bump = "MATCH (k:Counter {id:$k}) SET k.n = k.n + 1 RETURN k.n"
    rows = graph.query(bump, {"k": kind}).result_set
    if not rows:
        graph.query("MERGE (k:Counter {id:$k}) ON CREATE SET k.n = $base",
                    {"k": kind, "base": _existing_max(graph, label, prefix)})
        rows = graph.query(bump, {"k": kind}).result_set
    return "%s%0*d" % (prefix, width, rows[0][0])


def _next_decision_id(graph):
    return allocate_id(graph, "decision")


# ---------------------------------------------------------------- overdue promises

def _iso(d):
    return d.isoformat() if hasattr(d, "isoformat") else d


def mark_overdue_promises(graph, today=None):
    """Link a customer to every promise that is still unkept and due before
    today. Safe to run any number of times; kept promises are never touched.

    The link carries the date it was added, so read_state(as_of=...) can show
    an older decision exactly what it saw."""
    today = _iso(today or date.today())
    graph.query(
        "MATCH (c:Customer)-[:PROMISED]->(p:Promise) "
        "WHERE p.kept = false AND p.due < $today "
        "MERGE (c)-[b:BROKE]->(p) ON CREATE SET b.since = $today",
        {"today": today})


def prune_decisions(graph, keep=MAX_DECISIONS):
    """Keep at most `keep` stored decisions: the oldest go first, together with
    their links. Sales, payments and promises are never deleted."""
    n = graph.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0]
    if n <= keep:
        return 0
    graph.query("MATCH (d:Decision) WITH d ORDER BY d.created ASC, d.id ASC LIMIT $n "
                "DETACH DELETE d", {"n": n - keep})
    return n - keep


def _save(graph, customer_id, request_amount, state, result, fp, snap, as_of):
    did = _next_decision_id(graph)
    by_label = {}
    for ev in evidence_list(state):
        by_label.setdefault(ev["label"], []).append(ev["id"])
    # One round trip for the whole decision: the rules, the decision, its links to
    # the customer, the rules and every record it used. Same nodes and links as
    # before, written in one query because each trip to the database costs time.
    q = ("UNWIND $rules AS r MERGE (x:Rule {id:r.id}) ON CREATE SET x.text=r.text "
         "WITH collect(x) AS rs "
         "MATCH (c:Customer {id:$cid}) "
         "CREATE (d:Decision {id:$did, customer_id:$cid, request:$req, verdict:$v, "
         "reason:$reason, created:$created, fingerprint:$fp, rule_ids:$rids, "
         "snapshot:$snap, open_debt:$debt, as_of:$as_of}) "
         "CREATE (d)-[:ABOUT]->(c) "
         "WITH d, rs UNWIND rs AS x CREATE (d)-[:APPLIED_RULE]->(x) WITH DISTINCT d")
    params = {"rules": [{"id": rid, "text": text} for rid, text in RULES.items()],
              "cid": customer_id, "did": did, "req": request_amount, "v": result["verdict"],
              "reason": result["reason"],
              "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "fp": fp, "rids": json.dumps(sorted(RULES)),
              "snap": json.dumps(snap, sort_keys=True), "debt": result["open_debt"],
              "as_of": as_of}
    for n, (label, ids) in enumerate(by_label.items()):
        q += (" UNWIND $ids%d AS eid%d MATCH (e%d:%s {id:eid%d}) "
              "CREATE (d)-[:USED_EVIDENCE]->(e%d) WITH DISTINCT d" % (n, n, n, label, n, n))
        params["ids%d" % n] = ids
    graph.query(q + " RETURN d.id", params)
    return did


def decide(customer_id, request_amount, graph=None, save=True, today=None, as_of=None):
    """today: override for the date (tests). as_of: replay mode, used by the
    what-if on a graph copy. It reads the records as they stood on that date
    and does not add any broken-promise links."""
    if graph is None:
        from db import get_graph
        graph = get_graph()
    if as_of is None:
        today = _iso(today or date.today())
        mark_overdue_promises(graph, today)
    else:
        today = as_of
    state = read_state(graph, customer_id, as_of=as_of)
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
                                   result, out["fingerprint"], snap, today)
    return out


def main(argv):
    from db import open_graph, pop_graph_arg
    name, rest = pop_graph_arg(argv[1:])
    args = [a for a in rest if not a.startswith("--")]
    if len(args) != 2 or not args[1].lstrip("-").isdigit():
        print("usage: python rules.py CUSTOMER 45000 [--no-save] [--graph NAME]")
        return 2
    _, graph, _ = open_graph(["--graph", name] if name else [])
    r = decide(args[0], int(args[1]), graph=graph, save="--no-save" not in rest)
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
