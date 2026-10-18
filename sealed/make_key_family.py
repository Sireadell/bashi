"""Write sealed set F: 20 family-network credit cases, from a fixed seed, each with the correct answer.

Run once: python sealed/make_key_family.py
Writes sealed/cases_family.json and sealed/KEY_HASH_FAMILY.txt. The hash is committed BEFORE Bashi is
run on these cases (python sealed/run_family.py).

Every case is invented. Each one is a small world of accounts and people:
  - a person can own an account, and buys for exactly one shop account (collects goods or pays there)
  - two people can be family
  - one extra group of people and accounts that is NOT linked to the asking account, owing a lot
How the correct answer is made, by plain arithmetic in truth() below (no rules.py, no database):
  1. Start at the asking account. Follow every owner, buyer and family link, any number of steps.
  2. If that reaches no other account, the answer is the old one: NO if owed + request > limit.
  3. Else add up what every reached account owes, the asking one included.
     NO if that total + request > the asking account's limit. Else YES.
  (No promises in this set, so the broken-promise rule never fires.)
Depth is the number of links from the asking account to the farthest account reached; a family link
counts as one link. Cases cover depth 1 (a buyer of the asking shop only, no other account) to 9.
"""
import hashlib
import json
import os
import random

SEED = 20261018
AS_OF = "2026-10-01"
HERE = os.path.dirname(os.path.abspath(__file__))
rng = random.Random(SEED)


def owed():
    return rng.choice([0, 5000, 10000, 15000, 20000, 25000, 30000, 40000])


def truth(c):
    """The correct answer from the links, by breadth-first search and addition."""
    nbr = {}

    def join(a, b):
        nbr.setdefault(a, set()).add(b)
        nbr.setdefault(b, set()).add(a)
    for p in c["people"]:
        join("P:" + p["id"], "A:" + p["buys_for"])
        for a in p["owns"]:
            join("P:" + p["id"], "A:" + a)
    for a, b in c["family"]:
        join("P:" + a, "P:" + b)
    start = "A:" + c["ask"]
    seen, todo = {start}, [start]
    while todo:
        n = todo.pop()
        for m in nbr.get(n, ()):
            if m not in seen:
                seen.add(m)
                todo.append(m)
    reached = sorted(x[2:] for x in seen if x.startswith("A:") and x != start)
    debt = {a["id"]: a["owed"] for a in c["accounts"]}
    total = debt[c["ask"]] + (sum(debt[a] for a in reached) if reached else 0)
    return ("NO" if total + c["request"] > c["limit"] else "YES"), reached, total


def depth_of(c):
    """Links from the asking account to the farthest account reached (0 when none)."""
    nbr = {}
    for p in c["people"]:
        for a in [p["buys_for"]] + p["owns"]:
            nbr.setdefault("P:" + p["id"], set()).add("A:" + a)
            nbr.setdefault("A:" + a, set()).add("P:" + p["id"])
    for a, b in c["family"]:
        nbr.setdefault("P:" + a, set()).add("P:" + b)
        nbr.setdefault("P:" + b, set()).add("P:" + a)
    dist, frontier = {"A:" + c["ask"]: 0}, ["A:" + c["ask"]]
    while frontier:
        nxt = []
        for n in frontier:
            for m in nbr.get(n, ()):
                if m not in dist:
                    dist[m] = dist[n] + 1
                    nxt.append(m)
        frontier = nxt
    acc = [d for n, d in dist.items() if n.startswith("A:") and d > 0]
    return max(acc) if acc else (1 if any(n.startswith("P:") for n in dist) else 0)


def make(q, depth, want):
    """One case: a chain from the asking account `depth` links long, with random link types."""
    accts, people, family = [], [], []

    def acct(own=None):
        a = {"id": "%s-A%d" % (q, len(accts) + 1), "owed": owed() if own is None else own}
        accts.append(a)
        return a["id"]

    def person():
        p = {"id": "%s-B%d" % (q, len(people) + 1), "buys_for": None, "owns": [], "role": None}
        people.append(p)
        return p

    ask = acct(rng.choice([0, 0, 5000, 10000]))
    if depth == 1:
        p = person()
        p["buys_for"], p["role"] = ask, rng.choice(["collects", "pays"])
    elif depth >= 2:
        here, kind, links = ask, "A", 0
        while links < depth:
            left = depth - links
            if kind == "A":
                p = person()
                if rng.random() < 0.5:
                    p["owns"].append(here)
                else:
                    p["buys_for"], p["role"] = here, rng.choice(["collects", "pays"])
                here, kind = p, "P"
            elif left == 2 or (left >= 3 and rng.random() < 0.4):
                p = person()
                family.append((here["id"], p["id"]))
                here = p
            else:
                a = acct()
                if here["buys_for"] is None and rng.random() < 0.5:
                    here["buys_for"], here["role"] = a, rng.choice(["collects", "pays"])
                else:
                    here["owns"].append(a)
                here, kind = a, "A"
            links += 1
        for p in people:                      # everyone buys for one shop: give the rest a side shop
            if p["buys_for"] is None:
                p["buys_for"], p["role"] = acct(), rng.choice(["collects", "pays"])
    # an unlinked group that owes a lot, which must never count
    far = person()
    far["buys_for"], far["role"] = acct(90000), "collects"
    far["owns"].append(acct(60000))
    limit = rng.choice([100000, 150000, 200000])
    c = {"id": q, "ask": ask, "limit": limit, "as_of": AS_OF, "accounts": accts, "people": people,
         "family": family, "request": 0}
    _, reached, total = truth(c)
    room = limit - total
    if want == "YES":
        if room < 1000:
            return None
        c["request"] = max(1000, rng.randrange(1000, room + 1, 1000))
    else:
        c["request"] = max(1000, room + rng.randrange(1000, 40001, 1000))
    c["depth"] = depth_of(c)
    c["correct"], c["reached"], c["network_owed"] = truth(c)
    alone = "NO" if c["accounts"][0]["owed"] + c["request"] > limit else "YES"
    c["alone_says"] = alone
    return c if c["correct"] == want else None


PLAN = [  # (depth, wanted answer)
    (0, "YES"), (0, "NO"), (0, "YES"),
    (1, "YES"), (1, "NO"),
    (2, "NO"), (2, "YES"), (3, "NO"), (3, "YES"), (4, "NO"), (4, "YES"),
    (5, "NO"), (5, "YES"), (6, "NO"), (7, "NO"), (7, "YES"), (8, "NO"), (8, "YES"), (9, "NO"), (9, "NO"),
]


def build():
    cases = []
    for i, (depth, want) in enumerate(PLAN, 1):
        for _ in range(500):
            c = make("F%02d" % i, depth, want)
            if c and (depth < 2 or c["depth"] == depth):
                cases.append(c)
                break
        else:
            raise SystemExit("could not make case %d" % i)
    return cases


def main():
    cases = build()
    body = json.dumps(cases, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with open(os.path.join(HERE, "cases_family.json"), "w", encoding="utf-8") as fh:
        json.dump(cases, fh, indent=1, sort_keys=True)
    with open(os.path.join(HERE, "KEY_HASH_FAMILY.txt"), "w", encoding="utf-8") as fh:
        fh.write("sha256 of the 20 set-F family-network cases and their correct answers, canonical JSON "
                 "(sorted keys, no spaces), seed %d:\n%s\n" % (SEED, digest))
    print("wrote %d cases, %d YES, %d NO, alone-vs-network differ in %d; hash %s" % (
        len(cases), sum(c["correct"] == "YES" for c in cases), sum(c["correct"] == "NO" for c in cases),
        sum(c["correct"] != c["alone_says"] for c in cases), digest))
    for c in cases:
        print(c["id"], "depth", c["depth"], "reached", len(c["reached"]), "owed", c["network_owed"],
              "limit", c["limit"], "ask", c["request"], c["correct"], "alone", c["alone_says"])


if __name__ == "__main__":
    main()
