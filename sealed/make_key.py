"""Write the sealed answer key: 55 shop-credit cases, each with the correct answer.

Run once: python sealed/make_key.py
It writes sealed/cases.json and sealed/KEY_HASH.txt. The hash is committed and pushed
BEFORE any system is run against the cases, so the answers cannot be changed to suit a result.

The correct answer comes from the story of each case (which payment really paid which
sale), worked out here by plain arithmetic. It does not use rules.py, linking.py or any
code that is being tested. This is a test I wrote, on cases I chose, so it shows what
Bashi does on the situations it was built for. It is not a measure of real-world accuracy.

Shop rule used for the correct answer, in words:
  1. If any sale has no usable amount, the right answer is REFUSE (do not guess).
  2. What the customer truly owes is, for each sale, its amount minus every payment that
     really paid for it, never below zero. Extra money on one sale does not clear another.
  3. A promise to pay is broken if it was not kept and its due date is before the check date.
  4. Answer NO if the customer has a broken promise, or owes plus the request is more than
     the limit. Otherwise YES. Owing exactly up to the limit is allowed.
"""
import hashlib
import json
import os

AS_OF = "2026-10-01"
SALE_DAY = "2026-07-10"
PAY_DAY = "2026-07-25"
EARLY_DAY = "2026-07-01"
LIMIT = 100000
cases = []


def add(cls, story, expect, request, sales, pays=(), proms=(), limit=LIMIT, other=()):
    """sales: [amount or None]. pays: [(amount, paid_for sale number or None, linked, early)].
    proms: [(amount, due, kept)]. other: [amount] paid by someone else, never linked."""
    n = len(cases) + 1
    cases.append({
        "id": "Q%02d" % n, "class": cls, "story": story, "limit": limit, "request": request,
        "as_of": AS_OF,
        "sales": [{"n": i + 1, "amount": a, "date": SALE_DAY} for i, a in enumerate(sales)],
        "payments": [{"n": i + 1, "amount": a, "paid_for": pf, "linked": ln,
                      "date": EARLY_DAY if early else PAY_DAY} for i, (a, pf, ln, early) in enumerate(pays)],
        "promises": [{"amount": a, "due": d, "kept": k} for a, d, k in proms],
        "other_payments": list(other), "expect": expect})


# 1. clean, within the limit
add("clean_within", "Paid in full, asks for less than the limit", "YES", 30000, [20000], [(20000, 1, True, False)])
add("clean_within", "Owes 50,000, asks 30,000", "YES", 30000, [50000])
add("clean_within", "Two sales, one paid, asks 40,000", "YES", 40000, [30000, 25000], [(30000, 1, True, False)])
add("clean_within", "Bigger limit, owes 100,000, asks 100,000", "YES", 100000, [120000], [(20000, 1, True, False)], limit=300000)
add("clean_within", "New customer, nothing owed", "YES", 90000, [])
add("clean_within", "Three sales, two paid", "YES", 60000, [10000, 10000, 10000], [(10000, 1, True, False), (10000, 2, True, False)])
# 2. clean, over the limit
add("clean_over", "Owes 70,000, asks 40,000", "NO", 40000, [70000])
add("clean_over", "Owes 50,000, asks 60,000", "NO", 60000, [80000], [(30000, 1, True, False)])
add("clean_over", "Two unpaid sales, asks 30,000", "NO", 30000, [40000, 40000])
add("clean_over", "Big limit, still too much", "NO", 200000, [450000], [(100000, 1, True, False)], limit=500000)
add("clean_over", "New customer asks above the limit", "NO", 130000, [])
# 3. exactly at the limit, and one naira over
add("boundary", "Owes 60,000, asks exactly the room left", "YES", 40000, [60000])
add("boundary", "Owes 60,000, asks one naira too much", "NO", 40001, [60000])
add("boundary", "Part paid, asks exactly the room left", "YES", 50000, [60000], [(10000, 1, True, False)])
add("boundary", "Part paid, asks one naira too much", "NO", 50001, [60000], [(10000, 1, True, False)])
# 4. broken promise, small debt
P_BROKEN = [(10000, "2026-08-15", False)]
add("broken_promise", "Broken promise, no debt", "NO", 5000, [], proms=P_BROKEN)
add("broken_promise", "Broken promise, sale paid", "NO", 20000, [10000], [(10000, 1, True, False)], P_BROKEN)
add("broken_promise", "Broken promise, small unpaid sale", "NO", 10000, [5000], proms=P_BROKEN)
add("broken_promise", "Promise broken yesterday", "NO", 1000, [], proms=[(10000, "2026-09-30", False)])
add("broken_promise", "One kept promise, one broken", "NO", 15000, [], proms=[(5000, "2026-07-01", True), (8000, "2026-09-01", False)])
add("broken_promise", "Very old broken promise", "NO", 2000, [], proms=[(4000, "2026-01-10", False)])
add("broken_promise", "Part paid sale and a broken promise", "NO", 5000, [20000], [(15000, 1, True, False)], P_BROKEN)
# 5. kept promises must not block
add("kept_promise", "Kept promise, no debt", "YES", 20000, [], proms=[(10000, "2026-08-15", True)])
add("kept_promise", "Two kept promises, sale paid", "YES", 30000, [10000], [(10000, 1, True, False)], [(10000, "2026-07-15", True), (6000, "2026-08-20", True)])
add("kept_promise", "Kept promise, unpaid sale", "YES", 30000, [30000], proms=[(10000, "2026-08-15", True)])
add("kept_promise", "Kept promise, part paid", "YES", 50000, [10000, 10000], [(10000, 1, True, False)], [(5000, "2026-08-01", True)])
# 6. promise not yet due
add("promise_not_due", "Promise due in two weeks", "YES", 10000, [], proms=[(10000, "2026-10-15", False)])
add("promise_not_due", "Promise due later, unpaid sale", "YES", 20000, [20000], proms=[(10000, "2026-10-20", False)])
add("promise_not_due", "Promise due on the check date itself", "YES", 5000, [], proms=[(5000, "2026-10-01", False)])
# 7. a payment was recorded but never tied to its sale (the money did come in)
add("unlinked_payment", "Paid 60,000, never tied to the sale", "YES", 50000, [60000], [(60000, 1, False, False)])
add("unlinked_payment", "Paid 45,000, never tied", "YES", 90000, [45000], [(45000, 1, False, False)])
add("unlinked_payment", "Two same-size sales, one paid, not tied", "YES", 50000, [30000, 30000], [(30000, 2, False, False)])
add("unlinked_payment", "Big limit, paid 200,000, not tied", "YES", 250000, [200000], [(200000, 1, False, False)], limit=300000)
add("unlinked_payment", "Small sale paid, not tied, small ask", "YES", 80000, [12000], [(12000, 1, False, False)])
add("unlinked_payment", "Paid one sale, still owes the other", "NO", 40000, [60000, 70000], [(60000, 1, False, False)])
add("unlinked_payment", "Paid, not tied, but a broken promise", "NO", 5000, [50000], [(50000, 1, False, False)], P_BROKEN)
add("unlinked_payment", "Paid, not tied, ask above the limit", "NO", 120000, [80000], [(80000, 1, False, False)])
# 8. money paid before the sale (a deposit), not tied
add("deposit_first", "Deposit of 50,000 before the sale", "YES", 60000, [50000], [(50000, 1, False, True)])
add("deposit_first", "Deposit of 40,000 before the sale", "YES", 80000, [40000], [(40000, 1, False, True)])
add("deposit_first", "Deposit of 30,000 on a 70,000 sale", "YES", 50000, [70000], [(30000, 1, False, True)])
add("deposit_first", "Deposit of 20,000 before the sale", "YES", 90000, [20000], [(20000, 1, False, True)])
# 9. one sale paid in pieces, all tied
add("split_payment", "60,000 sale, two payments of 20,000", "YES", 70000, [60000], [(20000, 1, True, False), (20000, 1, True, False)])
add("split_payment", "Same, asks 85,000", "NO", 85000, [60000], [(20000, 1, True, False), (20000, 1, True, False)])
add("split_payment", "50,000 sale paid in two halves, asks the limit", "YES", 100000, [50000], [(25000, 1, True, False), (25000, 1, True, False)])
add("split_payment", "90,000 sale, 60,000 paid in two", "YES", 50000, [90000], [(30000, 1, True, False), (30000, 1, True, False)])
# 10. paid more than the sale
add("overpayment", "Paid 30,000 on a 20,000 sale", "YES", 90000, [20000], [(30000, 1, True, False)])
add("overpayment", "Same, asks one naira over the limit", "NO", 100001, [20000], [(30000, 1, True, False)])
add("overpayment", "Extra on one sale does not clear the other", "NO", 70000, [20000, 40000], [(30000, 1, True, False)])
# 11. a sale with no usable amount: refuse to guess
add("missing_data", "Only sale has no amount", "REFUSE", 10000, [None])
add("missing_data", "One of two sales has no amount", "REFUSE", 5000, [30000, None])
add("missing_data", "No-amount sale and a payment", "REFUSE", 5000, [None], [(10000, 1, False, False)])
add("missing_data", "Paid sale plus a no-amount sale", "REFUSE", 5000, [15000, None], [(15000, 1, True, False)])
# 12. someone else's payment must not clear this customer's sale
add("others_payment", "Another customer paid 40,000, ours owes 40,000", "NO", 70000, [40000], other=[40000])
add("others_payment", "Another customer paid 30,000, ours owes 30,000", "YES", 50000, [30000], other=[30000])
add("others_payment", "Another customer paid 60,000, ours owes 60,000", "NO", 45000, [60000], other=[60000])


def truth(c):
    """The correct answer, by plain arithmetic from the story. Independent of the code under test."""
    if any(s["amount"] is None for s in c["sales"]):
        return "REFUSE"
    owed = 0
    for s in c["sales"]:
        paid = sum(p["amount"] for p in c["payments"] if p["paid_for"] == s["n"])
        owed += max(0, s["amount"] - paid)
    broken = any((not p["kept"]) and p["due"] < c["as_of"] for p in c["promises"])
    return "NO" if broken or owed + c["request"] > c["limit"] else "YES"


def main():
    bad = [(c["id"], c["expect"], truth(c)) for c in cases if c["expect"] != truth(c)]
    assert not bad, "hand label and arithmetic disagree: %s" % bad
    assert len(cases) == 55 and len({c["id"] for c in cases}) == 55
    for c in cases:
        c["correct"] = c.pop("expect")
    body = json.dumps(cases, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "cases.json"), "w", encoding="utf-8") as fh:
        json.dump(cases, fh, sort_keys=True, indent=1)
    with open(os.path.join(here, "KEY_HASH.txt"), "w", encoding="utf-8") as fh:
        fh.write("sha256 of the 55 cases and their correct answers, canonical JSON (sorted keys, no spaces):\n%s\n" % digest)
    counts = {}
    for c in cases:
        counts[c["correct"]] = counts.get(c["correct"], 0) + 1
    print("55 cases written. Correct answers:", counts)
    print("sha256", digest)


if __name__ == "__main__":
    main()
