"""Ten different edits to a saved decision's records; verify.py must catch every one.

  python tamper_sweep.py            run on a throwaway copy of shop_a, write TAMPER_SWEEP.md

It copies the practice shop, saves one fresh decision on the copy, then for each edit:
make the change, replay the decision (must FAIL), undo the change, replay again (must
PASS). The copy is deleted at the end. The real graphs are never changed.
"""
import os
import sys
import time

from db import get_db, get_graph
from rules import decide
from verify import verify_decision

HERE = os.path.dirname(os.path.abspath(__file__))
CUSTOMER, REQUEST = "C001", 45000
COLS = "d.id, d.customer_id, d.request, d.verdict, d.fingerprint, d.snapshot"


def replay(g, did):
    row = g.query("MATCH (d:Decision {id:$i}) RETURN " + COLS, {"i": did}).result_set[0]
    return verify_decision(g, row)


def one(g, q, p=None):
    rows = g.query(q, p or {}).result_set
    return rows[0][0] if rows else None


def main():
    db = get_db()
    name = "shop_a_sweep_%d" % int(time.time())
    get_graph("shop_a").copy(name)
    g = db.select_graph(name)
    results = []
    try:
        res = decide(CUSTOMER, REQUEST, graph=g, save=True)
        did = res["decision_id"]
        ev = {lab: [] for lab in ("Trade", "Payment", "Promise")}
        for lab, eid in g.query("MATCH (:Decision {id:$i})-[:USED_EVIDENCE]->(e) RETURN labels(e)[0], e.id",
                                {"i": did}).result_set:
            ev[lab].append(eid)
        ok0, p0 = replay(g, did)
        if not ok0:
            raise SystemExit("Baseline replay should pass but failed: %s" % p0)
        t1, t2 = ev["Trade"][0], ev["Trade"][-1]
        pay = ev["Payment"][0]
        pr = ev["Promise"][0]
        edits = [
            ("Change a sale amount (%s)" % t1,
             "MATCH (n:Trade {id:$x}) SET n.amount = n.amount + 1000", "MATCH (n:Trade {id:$x}) SET n.amount = $o",
             t1, "MATCH (n:Trade {id:$x}) RETURN n.amount"),
            ("Change a different sale amount (%s)" % t2,
             "MATCH (n:Trade {id:$x}) SET n.amount = n.amount * 2", "MATCH (n:Trade {id:$x}) SET n.amount = $o",
             t2, "MATCH (n:Trade {id:$x}) RETURN n.amount"),
            ("Change a payment amount (%s)" % pay,
             "MATCH (n:Payment {id:$x}) SET n.amount = n.amount + 500", "MATCH (n:Payment {id:$x}) SET n.amount = $o",
             pay, "MATCH (n:Payment {id:$x}) RETURN n.amount"),
            ("Change a sale date (%s)" % t1,
             "MATCH (n:Trade {id:$x}) SET n.date = '2020-01-01'", "MATCH (n:Trade {id:$x}) SET n.date = $o",
             t1, "MATCH (n:Trade {id:$x}) RETURN n.date"),
            ("Mark a promise as kept (%s)" % pr,
             "MATCH (n:Promise {id:$x}) SET n.kept = true", "MATCH (n:Promise {id:$x}) SET n.kept = $o",
             pr, "MATCH (n:Promise {id:$x}) RETURN n.kept"),
            ("Change a promise amount (%s)" % pr,
             "MATCH (n:Promise {id:$x}) SET n.amount = n.amount + 700", "MATCH (n:Promise {id:$x}) SET n.amount = $o",
             pr, "MATCH (n:Promise {id:$x}) RETURN n.amount"),
            ("Raise the customer's credit limit",
             "MATCH (n:Customer {id:$x}) SET n.credit_limit = n.credit_limit + 100000",
             "MATCH (n:Customer {id:$x}) SET n.credit_limit = $o",
             CUSTOMER, "MATCH (n:Customer {id:$x}) RETURN n.credit_limit"),
            ("Edit the saved decision's yes or no",
             "MATCH (n:Decision {id:$x}) SET n.verdict = 'YES'", "MATCH (n:Decision {id:$x}) SET n.verdict = $o",
             did, "MATCH (n:Decision {id:$x}) RETURN n.verdict"),
            ("Edit the saved decision's fingerprint",
             "MATCH (n:Decision {id:$x}) SET n.fingerprint = 'forged'", "MATCH (n:Decision {id:$x}) SET n.fingerprint = $o",
             did, "MATCH (n:Decision {id:$x}) RETURN n.fingerprint"),
            ("Edit the decision's saved copy of its records",
             "MATCH (n:Decision {id:$x}) SET n.snapshot = replace(n.snapshot, '\"amount\"', '\"amt\"')",
             "MATCH (n:Decision {id:$x}) SET n.snapshot = $o",
             did, "MATCH (n:Decision {id:$x}) RETURN n.snapshot"),
        ]
        for label, do_q, undo_q, x, read_q in edits:
            orig = one(g, read_q, {"x": x})
            g.query(do_q, {"x": x})
            bad_ok, bad_p = replay(g, did)
            g.query(undo_q, {"x": x, "o": orig})
            good_ok, _ = replay(g, did)
            caught = (not bad_ok) and good_ok
            results.append((label, caught, bad_p[0] if bad_p else "NOT CAUGHT"))
        # Take away a link the decision used.
        g.query("MATCH (:Decision {id:$i})-[r:USED_EVIDENCE]->(:Trade {id:$t}) DELETE r", {"i": did, "t": t2})
        bad_ok, bad_p = replay(g, did)
        g.query("MATCH (d:Decision {id:$i}), (t:Trade {id:$t}) CREATE (d)-[:USED_EVIDENCE]->(t)", {"i": did, "t": t2})
        good_ok, _ = replay(g, did)
        results.append(("Remove a record from the decision's evidence (%s)" % t2,
                        (not bad_ok) and good_ok, bad_p[0] if bad_p else "NOT CAUGHT"))
    finally:
        try:
            g.delete()
        except Exception:
            pass
    caught = sum(1 for r in results if r[1])
    lines = ["# Tamper sweep", "",
             "Run with `python tamper_sweep.py` on a throwaway copy of the practice shop (`shop_a`), which is deleted afterwards. "
             "For each edit: change one thing, replay the saved decision (it must fail), undo the change, replay again (it must pass).", "",
             "| # | Edit | Caught and restored | What verify said |", "|---|---|---|---|"]
    for i, (lab, ok, msg) in enumerate(results, 1):
        lines.append("| %d | %s | %s | %s |" % (i, lab, "yes" if ok else "NO", msg))
    lines += ["", "**%d of %d edits caught.**" % (caught, len(results)), ""]
    with open(os.path.join(HERE, "TAMPER_SWEEP.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print("\n".join(lines))
    return 0 if caught == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
