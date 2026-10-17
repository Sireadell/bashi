"""Write sealed set B: 200 shop-credit cases, generated from a fixed seed, each with the correct answer.

Run once: python sealed/make_key_b.py
Writes sealed/cases_b.json and sealed/KEY_HASH_B.txt. The hash is committed and pushed BEFORE any system
is run on these cases.

Why a second set: the first 55 cases (sealed/cases.json) were where the deposit rule was fixed, so they
are no longer an untouched exam. These 200 were fixed before the fixed rule was ever run on them.

How the correct answer is made: each case is a story (which payment really paid which sale), and the
answer comes from plain arithmetic on that story in truth() below. It does not use rules.py or linking.py.
The generator uses a fixed random seed, so anyone can regenerate the same file and compare the hash.
The cases are templated, so they vary the amounts, dates and mix of situations, not the kinds of situation.

Shop rule used for the correct answer, in words:
  1. If any sale has no usable amount, the right answer is REFUSE.
  2. What the customer owes is, for each sale, its amount minus every payment that really paid for it,
     never below zero. Extra money on one sale does not clear another.
  3. A promise is broken if it was not kept and its due date is before the check date.
  4. Answer NO if there is a broken promise, or owes plus the request is more than the limit. Else YES.
"""
import hashlib
import json
import os
import random

SEED = 20261017
AS_OF = "2026-10-01"
rng = random.Random(SEED)
cases = []


def amt(lo=5000, hi=120000):
    return rng.randrange(lo, hi + 1, 5000)


def truth(c):
    if any(s["amount"] is None for s in c["sales"]):
        return "REFUSE"
    owed = 0
    for s in c["sales"]:
        paid = sum(p["amount"] for p in c["payments"] if p["paid_for"] == s["n"])
        owed += max(0, s["amount"] - paid)
    broken = any((not p["kept"]) and p["due"] < c["as_of"] for p in c["promises"])
    return "NO" if broken or owed + c["request"] > c["limit"] else "YES"


def owed_of(c):
    return sum(max(0, s["amount"] - sum(p["amount"] for p in c["payments"] if p["paid_for"] == s["n"]))
               for s in c["sales"])


def build(cls, story, sales, pays=(), proms=(), limit=None, other=(), request=None):
    """sales: [amount or None]. pays: [(amount, paid_for, linked, early)]. proms: [(amount, due, kept)]."""
    limit = limit or rng.choice([100000, 150000, 200000, 300000])
    c = {"class": cls, "story": story, "limit": limit, "as_of": AS_OF,
         "sales": [{"n": i + 1, "amount": a, "date": "2026-07-%02d" % (10 + i)} for i, a in enumerate(sales)],
         "payments": [{"n": i + 1, "amount": a, "paid_for": pf, "linked": ln,
                       "date": "2026-07-01" if early else "2026-08-%02d" % (1 + i)} for i, (a, pf, ln, early) in enumerate(pays)],
         "promises": [{"amount": a, "due": d, "kept": k} for a, d, k in proms],
         "other_payments": list(other), "request": 0}
    if request is None:
        room = limit - (owed_of(c) if all(s["amount"] is not None for s in c["sales"]) else 0)
        if rng.random() < 0.4:
            request = max(1000, room) + rng.randrange(5000, 60000, 5000)      # asks for more than the room left
        else:
            request = max(1000, min(room, rng.randrange(5000, limit, 5000))) if room >= 1000 else 1000
    c["request"] = request
    return c


def accept(c, want):
    return truth(c) == want


def add(maker, want, count):
    made = 0
    guard = 0
    while made < count:
        guard += 1
        assert guard < 5000, "could not make enough cases"
        c = maker()
        if accept(c, want(made)):
            cases.append(c)
            made += 1


def prom_broken():
    return [(amt(5000, 30000), rng.choice(["2026-08-15", "2026-09-01", "2026-09-20", "2026-09-30"]), False)]


def mk_clean_within():
    n = rng.randint(0, 3)
    sales = [amt() for _ in range(n)]
    pays = [(sales[i], i + 1, True, False) for i in range(n) if rng.random() < 0.5]
    return build("clean_within", "Owes some, asks within the limit", sales, pays)


def mk_clean_over():
    n = rng.randint(1, 3)
    sales = [amt(30000, 150000) for _ in range(n)]
    pays = [(sales[i] // 2 // 5000 * 5000 or 5000, i + 1, True, False) for i in range(n) if rng.random() < 0.4]
    limit = rng.choice([100000, 150000, 200000])
    c = build("clean_over", "Owes a lot, asks above the limit", sales, pays, limit=limit, request=0)
    c["request"] = max(1000, c["limit"] - owed_of(c) + rng.randrange(5000, 60000, 5000))
    return c


def mk_boundary():
    sales = [amt(20000, 90000) for _ in range(rng.randint(1, 2))]
    pays = [(sales[0] // 2 // 5000 * 5000 or 5000, 1, True, False)] if rng.random() < 0.5 else []
    c = build("boundary", "", sales, pays, request=0)
    room = c["limit"] - owed_of(c)
    c["request"] = max(1, room + rng.choice([0, 1]))
    c["story"] = "Asks exactly the room left" if c["request"] == room else "Asks one naira over the room left"
    return c


def mk_broken():
    n = rng.randint(0, 2)
    sales = [amt(5000, 60000) for _ in range(n)]
    pays = [(sales[i], i + 1, True, False) for i in range(n) if rng.random() < 0.5]
    proms = prom_broken() + ([(amt(5000, 20000), "2026-07-20", True)] if rng.random() < 0.3 else [])
    c = build("broken_promise", "Broken promise, small ask", sales, pays, proms)
    c["request"] = max(1000, min(c["request"], c["limit"] - owed_of(c)))
    return c


def mk_kept():
    n = rng.randint(0, 2)
    sales = [amt(5000, 60000) for _ in range(n)]
    pays = [(sales[i], i + 1, True, False) for i in range(n) if rng.random() < 0.5]
    proms = [(amt(5000, 30000), rng.choice(["2026-07-15", "2026-08-20", "2026-09-10"]), True) for _ in range(rng.randint(1, 2))]
    return build("kept_promise", "Only kept promises", sales, pays, proms)


def mk_not_due():
    sales = [amt(5000, 60000) for _ in range(rng.randint(0, 2))]
    proms = [(amt(5000, 30000), rng.choice(["2026-10-01", "2026-10-10", "2026-10-25"]), False)]
    return build("promise_not_due", "Promise not yet due", sales, [], proms)


def mk_unlinked():
    n = rng.randint(1, 3)
    sales = [amt(10000, 80000) for _ in range(n)]
    pays = []
    for i in range(n):
        if rng.random() < 0.65:
            pays.append((sales[i], i + 1, False, False))          # paid in full, never tied
    proms = prom_broken() if rng.random() < 0.15 else []
    return build("unlinked_payment", "Payments recorded but not tied to sales", sales, pays, proms)


def mk_deposit():
    n = rng.randint(1, 2)
    sales = [amt(20000, 100000) for _ in range(n)]
    pays = []
    for i in range(n):
        if rng.random() < 0.8:
            part = sales[i] if rng.random() < 0.5 else max(5000, sales[i] // 2 // 5000 * 5000)
            pays.append((part, i + 1, False, True))              # paid before the sale, never tied
    return build("deposit_first", "Money paid before the sale", sales, pays)


def mk_split():
    s = amt(30000, 120000)
    k = rng.randint(2, 3)
    share = max(5000, s // k // 5000 * 5000)
    pays = [(share, 1, True, False) for _ in range(k)]
    return build("split_payment", "One sale paid in pieces", [s], pays)


def mk_overpay():
    n = rng.randint(1, 2)
    sales = [amt(10000, 60000) for _ in range(n)]
    pays = [(sales[0] + amt(5000, 30000), 1, True, False)]
    return build("overpayment", "Paid more than the sale", sales, pays)


def mk_missing():
    sales = [amt(10000, 60000) for _ in range(rng.randint(0, 2))] + [None]
    rng.shuffle(sales)
    pays = [(amt(5000, 30000), None, False, False)] if rng.random() < 0.4 else []
    return build("missing_data", "A sale has no amount", sales, pays, request=amt(5000, 50000))


def mk_others():
    s = amt(20000, 80000)
    return build("others_payment", "Someone else paid the same amount", [s], other=[s])


def mk_mixed():
    n = rng.randint(2, 4)
    sales = [amt(10000, 70000) for _ in range(n)]
    pays = []
    for i in range(n):
        r = rng.random()
        if r < 0.3:
            pays.append((sales[i], i + 1, True, False))
        elif r < 0.55:
            pays.append((sales[i], i + 1, False, False))
        elif r < 0.7:
            pays.append((sales[i], i + 1, False, True))
    proms = prom_broken() if rng.random() < 0.25 else ([(amt(5000, 20000), "2026-08-10", True)] if rng.random() < 0.4 else [])
    return build("mixed", "Several sales, mixed payment situations", sales, pays, proms,
                 other=[amt(10000, 50000)] if rng.random() < 0.3 else [])


def alt(first, second):
    return lambda i: first if i % 2 == 0 else second


PLAN = [
    (mk_clean_within, lambda i: "YES", 20), (mk_clean_over, lambda i: "NO", 20),
    (mk_boundary, alt("YES", "NO"), 16), (mk_broken, lambda i: "NO", 24),
    (mk_kept, lambda i: "YES", 12), (mk_not_due, lambda i: "YES", 10),
    (mk_unlinked, alt("YES", "NO"), 28), (mk_deposit, alt("YES", "NO"), 16),
    (mk_split, alt("YES", "NO"), 16), (mk_overpay, alt("YES", "NO"), 12),
    (mk_missing, lambda i: "REFUSE", 10), (mk_others, alt("NO", "YES"), 10),
]


def main():
    for maker, want, count in PLAN:
        add(maker, want, count)
    # mixed: whatever the arithmetic says, the first 6 that come out
    mixed = []
    while len(mixed) < 6:
        c = mk_mixed()
        mixed.append(c)
    cases.extend(mixed)
    assert len(cases) == 200, len(cases)
    for i, c in enumerate(cases, 1):
        c["id"] = "B%03d" % i
        c["correct"] = truth(c)
        if not c["story"]:
            c["story"] = c["class"]
    body = json.dumps(cases, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "cases_b.json"), "w", encoding="utf-8") as fh:
        json.dump(cases, fh, sort_keys=True, indent=1)
    with open(os.path.join(here, "KEY_HASH_B.txt"), "w", encoding="utf-8") as fh:
        fh.write("sha256 of the 200 set-B cases and their correct answers, canonical JSON (sorted keys, no spaces), seed %d:\n%s\n" % (SEED, digest))
    counts, kinds = {}, {}
    for c in cases:
        counts[c["correct"]] = counts.get(c["correct"], 0) + 1
        kinds[c["class"]] = kinds.get(c["class"], 0) + 1
    print("200 cases written. Correct answers:", counts)
    print("Kinds:", kinds)
    print("sha256", digest)


if __name__ == "__main__":
    main()
