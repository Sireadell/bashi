"""Match a customer's payments to their sales and save each match in the graph.

Real shops record a payment against the customer, not against a sale. So nothing
says which sale a payment cleared. This module proposes the matches with two plain
rules and writes each one as an INFERRED_SETTLES link, kept apart from the SETTLES
links a person confirmed. Nothing here changes a confirmed link or a sale.

Rules, per customer, oldest first:
  1. exact: a payment equal to the whole open amount of an earlier-or-same-day sale
     settles that sale.
  2. oldest first: what is left of each payment goes to the oldest open sales dated on
     or before the payment, splitting a payment across sales when needed.
A payment never settles a sale dated after it. Money left over is reported as unapplied
credit and is never used to settle a later sale.

Run: python linking.py [--graph shop_real] [--dry-run]
"""
import sys

from db import get_db

LINK_BATCH = 500


def plan_customer(trades, payments):
    """trades: [(id, amount, date)]. payments: [(id, amount, date)].
    Returns (links, unapplied) with links = [(payment id, trade id, amount, method)]."""
    open_left = {t[0]: t[1] for t in trades}
    t_date = {t[0]: t[2] or "" for t in trades}
    order = sorted(open_left, key=lambda i: (t_date[i], i))
    pay_left = {p[0]: p[1] for p in payments}
    p_date = {p[0]: p[2] or "" for p in payments}
    pay_order = sorted(pay_left, key=lambda i: (p_date[i], i))
    links = []
    for pid in pay_order:                       # rule 1: exact
        for tid in order:
            if open_left[tid] > 0 and open_left[tid] == pay_left[pid] and t_date[tid] <= p_date[pid]:
                links.append((pid, tid, pay_left[pid], "exact"))
                open_left[tid] = 0
                pay_left[pid] = 0
                break
    for pid in pay_order:                       # rule 2: oldest first
        for tid in order:
            if pay_left[pid] <= 0:
                break
            if open_left[tid] > 0 and t_date[tid] <= p_date[pid]:
                amt = min(open_left[tid], pay_left[pid])
                links.append((pid, tid, amt, "oldest_first"))
                open_left[tid] -= amt
                pay_left[pid] -= amt
    unapplied = sum(v for v in pay_left.values() if v > 0)
    return links, unapplied


def read_customer_rows(graph, cid):
    trades = graph.query(
        "MATCH (:Customer {id:$cid})-[:MADE]->(t:Trade) WHERE NOT (:Payment)-[:SETTLES]->(t) "
        "RETURN t.id, t.amount, t.date", {"cid": cid}).result_set
    pays = graph.query(
        "MATCH (:Customer {id:$cid})-[:PAID]->(p:Payment) WHERE NOT (p)-[:SETTLES]->() "
        "RETURN p.id, p.amount, p.date", {"cid": cid}).result_set
    return trades, pays


def infer_all(graph, dry_run=False, force=False):
    """Compute and (unless dry_run) save links for every customer. Returns a summary.

    Saved decisions fingerprint the links they used, so re-running this after a
    decision exists would make that decision fail its replay. It refuses unless forced."""
    if not dry_run and not force:
        n = graph.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0]
        if n:
            raise RuntimeError("%d saved decision(s) rely on the current links; "
                               "re-matching would break their replay (use --force)" % n)
    cids = [r[0] for r in graph.query("MATCH (c:Customer) RETURN c.id ORDER BY c.id").result_set]
    all_links, per_customer = [], {}
    for cid in cids:
        trades, pays = read_customer_rows(graph, cid)
        links, unapplied = plan_customer(trades, pays)
        all_links += links
        sold = sum(t[1] for t in trades)
        paid = sum(p[1] for p in pays)
        applied = sum(l[2] for l in links)
        per_customer[cid] = {"sold": sold, "paid": paid, "applied": applied,
                             "open": sold - applied, "unapplied": unapplied,
                             "balance": sold - paid}
    if not dry_run:
        graph.query("MATCH ()-[r:INFERRED_SETTLES]->() DELETE r")
        for i in range(0, len(all_links), LINK_BATCH):
            rows = [{"pid": p, "tid": t, "amount": a, "method": m}
                    for p, t, a, m in all_links[i:i + LINK_BATCH]]
            graph.query("UNWIND $rows AS r MATCH (p:Payment {id:r.pid}), (t:Trade {id:r.tid}) "
                        "CREATE (p)-[:INFERRED_SETTLES {amount:r.amount, method:r.method}]->(t)",
                        {"rows": rows})
    return {"links": len(all_links),
            "exact": sum(1 for l in all_links if l[3] == "exact"),
            "oldest_first": sum(1 for l in all_links if l[3] == "oldest_first"),
            "customers": per_customer}


_case_cache = {"at": 0.0, "case": None}
CASE_REQUEST = 10000
CASE_KEEP_SECONDS = 600


def biggest_gap_case(graph):
    """The customer whose matched debt is furthest above the plain balance: the case the
    plain balance gets most wrong. Cached, because it reads every customer."""
    import time
    if time.time() - _case_cache["at"] < CASE_KEEP_SECONDS and _case_cache["case"]:
        return _case_cache["case"]
    res = infer_all(graph, dry_run=True)
    best = None
    for cid, v in res["customers"].items():
        gap = v["open"] - v["balance"]
        if v["open"] > 0 and (best is None or (gap, v["open"]) > best[0]):
            best = ((gap, v["open"]), cid)
    case = {"customer": best[1], "amount": CASE_REQUEST} if best else None
    _case_cache.update(at=time.time(), case=case)
    return case


def main(argv):
    name = argv[argv.index("--graph") + 1] if "--graph" in argv else "shop_real"
    res = infer_all(get_db().select_graph(name), dry_run="--dry-run" in argv, force="--force" in argv)
    print("graph %s: %d links (%d exact, %d oldest first)%s" % (
        name, res["links"], res["exact"], res["oldest_first"],
        " [dry run, nothing saved]" if "--dry-run" in argv else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
