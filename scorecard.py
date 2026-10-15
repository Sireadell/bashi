"""Scorecard: Bashi against a plain "balance only" answer on 40 credit questions.

Reads the live graph only. Bashi's verdict comes from rules.decide with
save=False, so no decision is stored. The balance-only answer is what a shop
ledger gives: all sales minus all payments for the customer, plus the new
request, against the limit. It does not care which sale a payment settles and
it does not look at broken promises.

Run:  python scorecard.py
"""
import json
import os
import random
import sys

from db import get_graph
from rules import decide, possible_phantoms, read_state, naira

SEED = 42
N_QUESTIONS = 40
KNOWN = {"C001": 45000}          # Tunde, the broken-promise case
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scorecard_results.json")


def balance_only(state, orphan_paid):
    """Sales minus payments, as a plain ledger would. orphan_paid is money the
    customer paid that was never linked to a sale (the ledger still has it)."""
    sales = sum(t["amount"] for t in state["trades"].values())
    paid = sum(p["amount"] for p in state["payments"].values()) + orphan_paid
    return sales - paid


def make_questions(graph):
    """25 customers once each, then 15 more drawn with the seed. Amounts are
    spread around each customer's limit (30% to 130%), rounded to N1,000.
    Known cases: C001 N45,000 (Tunde), C002 sized so the phantom debt matters,
    C003 a small request that should be a clean YES."""
    rng = random.Random(SEED)
    rows = graph.query("MATCH (c:Customer) RETURN c.id, c.name, c.credit_limit ORDER BY c.id").result_set
    cust = {r[0]: {"name": r[1], "limit": r[2]} for r in rows}
    ids = sorted(cust)

    def spread(cid):
        return max(1000, int(round(cust[cid]["limit"] * rng.uniform(0.3, 1.3) / 1000.0)) * 1000)

    qs = []
    for cid in ids:
        qs.append((cid, spread(cid)))
    for cid in rng.sample(ids, N_QUESTIONS - len(ids)):
        qs.append((cid, spread(cid)))
    fixed = {"C001": KNOWN["C001"],
             "C002": max(1000, cust["C002"]["limit"] - 6000),   # phantom scene
             "C003": 10000}                                      # clean YES
    seen = set()
    for i, (cid, _) in enumerate(qs):
        if cid in fixed and cid not in seen:
            qs[i] = (cid, fixed[cid])
            seen.add(cid)
    return cust, qs


def explain(bashi, bal_verdict, state, orphan_paid):
    if bashi["verdict"] == bal_verdict:
        return ""
    why = []
    if bashi["broken_promises"] and bashi["verdict"] == "NO" and bal_verdict == "YES":
        why.append("broken promise " + ", ".join(bashi["broken_promises"]))
    if orphan_paid:
        why.append("unlinked payment of %s (counted by the balance, not tied to a sale)" % naira(orphan_paid))
    if bashi["verdict"] not in ("YES", "NO"):
        why.append("Bashi could not trace an amount")
    return "; ".join(why) or "different open debt"


def run(graph=None):
    graph = graph or get_graph()
    cust, qs = make_questions(graph)
    out = []
    for n, (cid, amount) in enumerate(qs, 1):
        bashi = decide(cid, amount, graph=graph, save=False)
        state = read_state(graph, cid)
        orphan_paid = sum(ph["amount"] for ph in possible_phantoms(graph, state))
        bal = balance_only(state, orphan_paid)
        bal_verdict = "YES" if bal + amount <= state["customer"]["limit"] else "NO"
        out.append({
            "n": n, "customer": cid, "name": cust[cid]["name"], "request": amount,
            "limit": cust[cid]["limit"], "bashi": bashi["verdict"], "balance_only": bal_verdict,
            "bashi_open_debt": bashi["open_debt"], "balance_debt": bal,
            "differs": bashi["verdict"] != bal_verdict,
            "why": explain(bashi, bal_verdict, state, orphan_paid),
        })
    diffs = [r for r in out if r["differs"]]
    return {"seed": SEED, "questions": len(out), "differ": len(diffs),
            "same": len(out) - len(diffs), "rows": out}


def print_report(res):
    print("Bashi vs balance-only, %d questions (seed %d)" % (res["questions"], res["seed"]))
    print("Same answer: %d   Different: %d" % (res["same"], res["differ"]))
    if res["differ"]:
        print("%-3s %-5s %-18s %9s %-6s %-12s %s" % ("#", "Cust", "Name", "Request", "Bashi", "Balance-only", "Why"))
        for r in res["rows"]:
            if r["differs"]:
                print("%-3d %-5s %-18s %9s %-6s %-12s %s" % (
                    r["n"], r["customer"], r["name"], naira(r["request"]), r["bashi"], r["balance_only"], r["why"]))


def main():
    res = run()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print_report(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
