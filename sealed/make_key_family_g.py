"""Write sealed set G: 10 long family-network cases (10 to 22 links), from a fixed seed, with answers.

Run once: python sealed/make_key_family_g.py
Writes sealed/cases_family_g.json and sealed/KEY_HASH_FAMILY_G.txt, committed BEFORE Bashi is run
(python sealed/run_family.py g).

Same worlds and same arithmetic as set F (make_key_family.py), with one more stated rule: the walk stops
at 20 links, so an account more than 20 links away does not count. A family link counts as one link.
The last two cases are 21 and 22 links long, to check that limit.
"""
import hashlib
import json
import os

import make_key_family as f

SEED = 20261019
CAP = 20
HERE = os.path.dirname(os.path.abspath(__file__))
f.rng.seed(SEED)


def dist(c):
    """Links from the asking account to each account (breadth-first, family counts as one)."""
    nbr = {}

    def join(a, b):
        nbr.setdefault(a, set()).add(b)
        nbr.setdefault(b, set()).add(a)
    for p in c["people"]:
        for a in [p["buys_for"]] + p["owns"]:
            join("P:" + p["id"], "A:" + a)
    for a, b in c["family"]:
        join("P:" + a, "P:" + b)
    d, frontier = {"A:" + c["ask"]: 0}, ["A:" + c["ask"]]
    while frontier:
        nxt = []
        for n in frontier:
            for m in nbr.get(n, ()):
                if m not in d:
                    d[m] = d[n] + 1
                    nxt.append(m)
        frontier = nxt
    return {n[2:]: v for n, v in d.items() if n.startswith("A:") and v > 0}


def truth(c):
    reached = sorted(a for a, v in dist(c).items() if v <= CAP)
    debt = {a["id"]: a["owed"] for a in c["accounts"]}
    total = debt[c["ask"]] + sum(debt[a] for a in reached)
    return ("NO" if total + c["request"] > c["limit"] else "YES"), reached, total


PLAN = [(10, "NO"), (11, "YES"), (12, "NO"), (14, "YES"), (15, "NO"), (17, "NO"), (19, "YES"), (20, "NO"),
        (21, "YES"), (22, "YES")]


def make(q, depth, want):
    c = f.make(q, depth, "YES") or f.make(q, depth, "NO")
    if not c or c["depth"] != depth:
        return None
    c["correct"], c["reached"], c["network_owed"] = truth(c)
    room = c["limit"] - c["network_owed"]
    if want == "YES":
        if room < 1000:
            return None
        c["request"] = f.rng.randrange(1000, room + 1, 1000)
    else:
        c["request"] = max(1000, room + f.rng.randrange(1000, 40001, 1000))
    c["correct"], c["reached"], c["network_owed"] = truth(c)
    c["alone_says"] = "NO" if c["accounts"][0]["owed"] + c["request"] > c["limit"] else "YES"
    beyond = [a for a, v in dist(c).items() if v > CAP]
    if depth > CAP:   # the far end must owe enough to flip the answer if it were wrongly counted
        far = sum(a["owed"] for a in c["accounts"] if a["id"] in beyond)
        if c["network_owed"] + far + c["request"] <= c["limit"]:
            return None
    return c if c["correct"] == want else None


def build():
    cases = []
    for i, (depth, want) in enumerate(PLAN, 1):
        for _ in range(3000):
            c = make("G%02d" % i, depth, want)
            if c:
                cases.append(c)
                break
        else:
            raise SystemExit("could not make case %d" % i)
    return cases


def main():
    cases = build()
    body = json.dumps(cases, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with open(os.path.join(HERE, "cases_family_g.json"), "w", encoding="utf-8") as fh:
        json.dump(cases, fh, indent=1, sort_keys=True)
    with open(os.path.join(HERE, "KEY_HASH_FAMILY_G.txt"), "w", encoding="utf-8") as fh:
        fh.write("sha256 of the 10 set-G long family-network cases and their correct answers, canonical JSON "
                 "(sorted keys, no spaces), seed %d:\n%s\n" % (SEED, digest))
    print("wrote %d cases, %d YES, %d NO; hash %s" % (len(cases), sum(c["correct"] == "YES" for c in cases),
                                                       sum(c["correct"] == "NO" for c in cases), digest))
    for c in cases:
        print(c["id"], "depth", c["depth"], "reached", len(c["reached"]), "owed", c["network_owed"],
              "limit", c["limit"], "ask", c["request"], c["correct"], "alone", c["alone_says"])


if __name__ == "__main__":
    main()
