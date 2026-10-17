"""Take the sealed exam: run Bashi and a plain balance check on the 55 cases and score them.

Run: python sealed/run_sealed.py
Writes sealed/RESULTS.md and sealed/results.json. It builds one private graph, runs every
case, and deletes the graph afterwards. It never touches shop_a, shop_own or shop_real.

It refuses to run if the answer key no longer matches the fingerprint in KEY_HASH.txt.

Three arms:
  Bashi, confirmed links only   the decision rule as it ships, on the links the shop recorded
  Bashi with payment matching   the same rule after linking.py proposes links for loose payments
  Balance only                  all sales minus all payments of that customer, plus the request,
                                against the limit. It ignores promises and never refuses.
"""
import hashlib
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import linking  # noqa: E402
import real_shop  # noqa: E402
from db import get_db  # noqa: E402
from rules import CANNOT_TRACE, decide  # noqa: E402

ARMS = ("Bashi, confirmed links only", "Bashi with payment matching", "Balance only")


SETS = {"a": ("cases.json", "KEY_HASH.txt", "RESULTS.md", "results.json", "977f5bd"),
        "b": ("cases_b.json", "KEY_HASH_B.txt", "RESULTS_B.md", "results_b.json", "a5e2bd8")}


def which_set():
    return "b" if "b" in [a.lower() for a in sys.argv[1:]] else "a"


def load_key(which=None):
    cases_file, hash_file = SETS[which or which_set()][:2]
    with open(os.path.join(HERE, cases_file), encoding="utf-8") as fh:
        cases = json.load(fh)
    body = json.dumps(cases, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with open(os.path.join(HERE, hash_file), encoding="utf-8") as fh:
        sealed = fh.read().split()[-1]
    if digest != sealed:
        raise SystemExit("The answer key does not match its fingerprint. Not running.")
    return cases, digest


def export_of(cases):
    """The cases as an export in the shape the shop loader reads."""
    data = {"customers": [], "sales": [], "payments": [], "promises": []}
    for c in cases:
        q, cust = c["id"], "K-" + c["id"]
        data["customers"].append({"id": cust})
        for s in c["sales"]:
            data["sales"].append({"id": "%s-S%d" % (q, s["n"]), "kind": "sale", "customer": cust,
                                  "amount": s["amount"] if s["amount"] is not None else 1,
                                  "date": s["date"], "paid": 0})
        sale_amount = {s["n"]: s["amount"] for s in c["sales"]}
        for p in c["payments"]:
            row = {"id": "%s-P%d" % (q, p["n"]), "customer": cust, "amount": p["amount"],
                   "date": p["date"], "settles": None, "applied": 0}
            if p["linked"] and p["paid_for"]:
                row["settles"] = "%s-S%d" % (q, p["paid_for"])
                row["applied"] = min(p["amount"], sale_amount[p["paid_for"]])
            data["payments"].append(row)
        if c["other_payments"]:
            other = "O-" + q
            data["customers"].append({"id": other})
            for k, amt in enumerate(c["other_payments"], 1):
                data["payments"].append({"id": "%s-X%d" % (q, k), "customer": other, "amount": amt,
                                         "date": "2026-07-25", "settles": None, "applied": 0})
        for k, pr in enumerate(c["promises"], 1):
            data["promises"].append({"id": "%s-R%d" % (q, k), "customer": cust, "amount": pr["amount"],
                                     "date": "2026-06-01", "due": pr["due"], "kept": pr["kept"]})
    return data


def fix_up(g, cases):
    """Set the limit of each case, and blank the amounts that are meant to be missing."""
    g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid}) SET c.credit_limit = r.limit",
            {"rows": [{"cid": "K-" + c["id"], "limit": c["limit"]} for c in cases]})
    gaps = ["%s-S%d" % (c["id"], s["n"]) for c in cases for s in c["sales"] if s["amount"] is None]
    if gaps:
        g.query("UNWIND $ids AS i MATCH (t:Trade {id:i}) REMOVE t.amount", {"ids": gaps})


def ask_bashi(g, c):
    r = decide("K-" + c["id"], c["request"], graph=g, save=False, today=c["as_of"])
    return "REFUSE" if r["verdict"] == CANNOT_TRACE else r["verdict"]


def ask_balance(c):
    sold = sum(s["amount"] or 0 for s in c["sales"])
    paid = sum(p["amount"] for p in c["payments"])
    return "YES" if sold - paid + c["request"] <= c["limit"] else "NO"


def run(cases):
    db = get_db()
    name = "sealed_run_" + uuid.uuid4().hex[:8]
    answers = {a: {} for a in ARMS}
    try:
        real_shop.load_real(db, export_of(cases), graph_name=name)
        g = db.select_graph(name)
        fix_up(g, cases)
        for c in cases:
            answers[ARMS[0]][c["id"]] = ask_bashi(g, c)
        linking.infer_all(g, force=True)
        for c in cases:
            answers[ARMS[1]][c["id"]] = ask_bashi(g, c)
        for c in cases:
            answers[ARMS[2]][c["id"]] = ask_balance(c)
    finally:
        try:
            db.select_graph(name).delete()
        except Exception:
            pass
    return answers


def score(cases, answers):
    out = {}
    for arm in ARMS:
        right = wrong_yes = wrong_no = other = 0
        leaked = 0
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
        out[arm] = {"right": right, "wrong_approvals": wrong_yes, "naira_wrongly_approved": leaked,
                    "wrong_refusals": wrong_no, "other_wrong": other}
    return out


def by_class(cases, answers):
    rows = {}
    for c in cases:
        r = rows.setdefault(c["class"], {"n": 0, **{a: 0 for a in ARMS}})
        r["n"] += 1
        for a in ARMS:
            r[a] += answers[a][c["id"]] == c["correct"]
    return rows


def naira(n):
    return "N{:,}".format(n)


def write_report(cases, answers, scores, classes, digest):
    n = len(cases)
    which = which_set()
    lines = ["# Sealed test results", "",
             "This is a test I wrote. The %d cases and their correct answers were fixed, hashed and pushed "
             "(commit %s) before any system was run on them. Fingerprint (sha256): `%s`. "
             "`python sealed/run_sealed.py%s` re-checks that fingerprint and refuses to run if it differs." % (n, SETS[which][4], digest, " b" if which == "b" else ""),
             "", "I chose the cases to cover the situations Bashi was built for, so this shows what it does there. "
             "It is not a measure of accuracy on real shops. I also wrote Bashi, so I was not blind to how it behaves.", "",
             "## Result", "",
             "| Method | Right | Wrongly approved | Naira wrongly approved | Wrongly refused | Other wrong |",
             "|---|---|---|---|---|---|"]
    for a in ARMS:
        s = scores[a]
        lines.append("| %s | %d of %d | %d | %s | %d | %d |" % (
            a, s["right"], n, s["wrong_approvals"], naira(s["naira_wrongly_approved"]),
            s["wrong_refusals"], s["other_wrong"]))
    lines += ["", "## By kind of case", "", "| Kind | Cases | " + " | ".join(ARMS) + " |",
              "|---|---|" + "---|" * len(ARMS)]
    for k, r in classes.items():
        lines.append("| %s | %d | %s |" % (k, r["n"], " | ".join("%d" % r[a] for a in ARMS)))
    lines += ["", "## Every case a method got wrong", "",
              "| Case | Kind | Story | Correct | " + " | ".join(ARMS) + " |", "|---|---|---|---|" + "---|" * len(ARMS)]
    for c in cases:
        if any(answers[a][c["id"]] != c["correct"] for a in ARMS):
            lines.append("| %s | %s | %s | %s | %s |" % (
                c["id"], c["class"], c["story"], c["correct"],
                " | ".join(answers[a][c["id"]] + ("" if answers[a][c["id"]] == c["correct"] else " (wrong)") for a in ARMS)))
    lines += ["", "## What is not covered", "",
              "- Sales that were reversed or refunded: Bashi has no way to record a reversal yet, so there are no such cases.",
              "- The cases are small and tidy. Real records are messier, which is why the whole-shop view marks every matched link as inferred.", ""]
    with open(os.path.join(HERE, SETS[which_set()][2]), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main():
    cases, digest = load_key()
    answers = run(cases)
    scores = score(cases, answers)
    classes = by_class(cases, answers)
    write_report(cases, answers, scores, classes, digest)
    with open(os.path.join(HERE, SETS[which_set()][3]), "w", encoding="utf-8") as fh:
        json.dump({"fingerprint": digest, "scores": scores, "answers": answers}, fh, indent=1, sort_keys=True)
    for a in ARMS:
        print("%-30s right %2d/%d  wrong approvals %d (%s)  wrong refusals %d  other %d" % (
            a, scores[a]["right"], len(cases), scores[a]["wrong_approvals"],
            naira(scores[a]["naira_wrongly_approved"]), scores[a]["wrong_refusals"], scores[a]["other_wrong"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
