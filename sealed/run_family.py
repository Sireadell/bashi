"""Take sealed set F: run Bashi and a plain balance check on the 20 family-network cases and score them.

Run: python sealed/run_family.py      (set F, 20 cases)
     python sealed/run_family.py g    (set G, 10 long cases, 10 to 22 links)
Writes sealed/RESULTS_FAMILY.md and sealed/results_family.json (set G: ..._G.md, ..._g.json). It builds one private graph, runs every
case, and deletes the graph afterwards. It never touches shop_a, shop_own or shop_real.
It refuses to run if the answer key no longer matches the fingerprint in KEY_HASH_FAMILY.txt.

Two arms:
  Bashi               the decision rules as they ship, family network rule included
  This account only   owed by the asking account alone plus the request, against the limit
"""
import hashlib
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import own_shop  # noqa: E402
from db import get_db  # noqa: E402
from rules import CANNOT_TRACE, decide, naira  # noqa: E402

ARMS = ("Bashi", "This account only")
SETS = {"f": ("cases_family.json", "KEY_HASH_FAMILY.txt", "RESULTS_FAMILY.md", "results_family.json", "F"),
        "g": ("cases_family_g.json", "KEY_HASH_FAMILY_G.txt", "RESULTS_FAMILY_G.md", "results_family_g.json", "G")}
WHICH = SETS["g" if "g" in [a.lower() for a in sys.argv[1:]] else "f"]


def load_key():
    with open(os.path.join(HERE, WHICH[0]), encoding="utf-8") as fh:
        cases = json.load(fh)
    digest = hashlib.sha256(json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    with open(os.path.join(HERE, WHICH[1]), encoding="utf-8") as fh:
        if fh.read().split()[-1] != digest:
            raise SystemExit("The answer key does not match its fingerprint. Not running.")
    return cases, digest


def export_of(cases):
    """The cases in the shape the own-shop loader reads, every record tagged invented."""
    data = {"customers": [], "sales": [], "payments": [], "promises": [], "buyers": [], "family": []}
    inv = "invented"
    n = 0
    for c in cases:
        by_acct = {}
        for p in c["people"]:
            by_acct.setdefault(p["buys_for"], []).append(p)
        for a in c["accounts"]:
            data["customers"].append({"id": a["id"], "source": inv})
            if a["owed"]:
                n += 1
                data["sales"].append({"id": "S%04d" % n, "kind": "sale", "customer": a["id"],
                                      "amount": a["owed"], "date": "2026-08-01", "paid": 0, "source": inv})
            for p in by_acct.get(a["id"], []):
                n += 1
                sale = {"id": "S%04d" % n, "kind": "sale", "customer": a["id"], "amount": 5000,
                        "date": "2026-07-01", "paid": 5000, "source": inv}
                pay = {"id": "P%04d" % n, "customer": a["id"], "amount": 5000, "date": "2026-07-02",
                       "settles": sale["id"], "applied": 5000, "source": inv}
                (sale if p["role"] == "collects" else pay)["buyer"] = p["id"]
                data["sales"].append(sale)
                data["payments"].append(pay)
        for p in c["people"]:
            data["buyers"].append({"id": p["id"], "label": p["id"], "customer": p["buys_for"],
                                   "owns": list(p["owns"])})
        for k, (a, b) in enumerate(c["family"], 1):
            data["family"].append({"id": "%s-L%d" % (c["id"], k), "a": a, "b": b, "source": inv})
    return data


def run(cases):
    db = get_db()
    name = "sealed_family_" + uuid.uuid4().hex[:8]
    answers = {a: {} for a in ARMS}
    try:
        own_shop.load_seed(db, export_of(cases), graph_name=name)
        g = db.select_graph(name)
        g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid}) SET c.credit_limit = r.limit",
                {"rows": [{"cid": c["ask"], "limit": c["limit"]} for c in cases]})
        for c in cases:
            r = decide(c["ask"], c["request"], graph=g, save=False, today=c["as_of"])
            answers[ARMS[0]][c["id"]] = "REFUSE" if r["verdict"] == CANNOT_TRACE else r["verdict"]
            answers[ARMS[1]][c["id"]] = c["alone_says"]
    finally:
        try:
            db.select_graph(name).delete()
        except Exception:
            pass
    return answers


def score(cases, answers):
    out = {}
    for arm in ARMS:
        right = wrong_yes = wrong_no = other = leaked = 0
        for c in cases:
            got, want = answers[arm][c["id"]], c["correct"]
            if got == want:
                right += 1
            elif got == "YES":
                wrong_yes += 1
                leaked += c["request"]
            elif want == "YES":
                wrong_no += 1
            else:
                other += 1
        out[arm] = {"right": right, "wrong_approvals": wrong_yes, "wrong_refusals": wrong_no,
                    "other": other, "approved_wrongly": leaked}
    return out


def main():
    cases, digest = load_key()
    answers = run(cases)
    scores = score(cases, answers)
    lines = ["# Sealed set %s: family network, results" % WHICH[4], "",
             "%d invented cases, answer key locked first (sha256 `%s`). Correct answers come from plain "
             "arithmetic in the generator, not from Bashi." % (len(cases), digest), "",
             "| Arm | Right | Wrong approvals | Wrong refusals | Other |", "|---|---|---|---|---|"]
    for arm in ARMS:
        s = scores[arm]
        lines.append("| %s | %d/%d | %d (%s) | %d | %d |" % (arm, s["right"], len(cases), s["wrong_approvals"],
                                                            naira(s["approved_wrongly"]), s["wrong_refusals"], s["other"]))
    lines += ["", "| Case | Links deep | Accounts reached | Network owes | Limit | Asked | Correct | Bashi | This account only |",
              "|---|---|---|---|---|---|---|---|---|"]
    for c in cases:
        lines.append("| %s | %d | %d | %s | %s | %s | %s | %s | %s |" % (
            c["id"], c["depth"], len(c["reached"]), naira(c["network_owed"]), naira(c["limit"]),
            naira(c["request"]), c["correct"], answers[ARMS[0]][c["id"]], answers[ARMS[1]][c["id"]]))
    with open(os.path.join(HERE, WHICH[2]), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(HERE, WHICH[3]), "w", encoding="utf-8") as fh:
        json.dump({"hash": digest, "scores": scores, "answers": answers}, fh, indent=1, sort_keys=True)
    for arm in ARMS:
        s = scores[arm]
        print("%-20s right %d/%d  wrong approvals %d (%s)  wrong refusals %d  other %d" % (
            arm, s["right"], len(cases), s["wrong_approvals"], naira(s["approved_wrongly"]),
            s["wrong_refusals"], s["other"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
