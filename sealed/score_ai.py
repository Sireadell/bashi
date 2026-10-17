"""Score a plain AI model's answers on a sealed set. No graph and no Bashi code is involved.

Steps anyone can repeat:
  1. python sealed/score_ai.py prompts          writes sealed/ai_prompt_a.txt and sealed/ai_prompt_b.txt
                                                (the shop's rules in words plus one text ledger per case, no answers)
  2. Give a prompt file to any AI model and ask it for a JSON object {case id: "YES" | "NO" | "REFUSE"}.
  3. python sealed/score_ai.py score a answers_a.json "model name"     (or b ...)
                                                checks the key fingerprint, scores, writes sealed/RESULTS_ai_only[_b].md
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_sealed import load_key, naira  # noqa: E402


RULE = """You decide whether a small shop may sell on credit to one customer.
Rules of the shop:
1. If any sale has no usable amount, answer REFUSE (do not guess).
2. What the customer owes is the sum over their sales of what is still unpaid. Money from the customer's own payments counts against their sales. Money paid by other customers never counts.
3. A promise to pay is broken if it was not kept and its due date is before today's date.
4. Answer NO if the customer has a broken promise, or if what they owe plus the new request is more than their credit limit. Otherwise answer YES. Owing exactly up to the limit is allowed.
Answer with one word only: YES, NO or REFUSE."""


def ledger(c):
    lines = ["Today: %s" % c["as_of"], "Credit limit: %d" % c["limit"], "New credit request: %d" % c["request"], "", "Sales:"]
    for s in c["sales"]:
        lines.append("  sale %d: %s on %s" % (s["n"], "NO AMOUNT RECORDED" if s["amount"] is None else s["amount"], s["date"]))
    if not c["sales"]:
        lines.append("  none")
    lines.append("Payments by this customer:")
    for p in c["payments"]:
        tied = " (recorded as paying sale %d)" % p["paid_for"] if p["linked"] and p["paid_for"] else " (not tied to any sale)"
        lines.append("  payment %d: %d on %s%s" % (p["n"], p["amount"], p["date"], tied))
    if not c["payments"]:
        lines.append("  none")
    lines.append("Promises to pay:")
    for pr in c["promises"]:
        lines.append("  %d promised by %s, %s" % (pr["amount"], pr["due"], "kept" if pr["kept"] else "not kept"))
    if not c["promises"]:
        lines.append("  none")
    if c["other_payments"]:
        lines.append("Payments by OTHER customers (not this one): %s" % ", ".join(str(a) for a in c["other_payments"]))
    return "\n".join(lines)


def prompts():
    for w in ("a", "b"):
        cases, _ = load_key(w)
        out = [RULE, "", "Below are %d separate customers. Treat each one on its own. "
               "Answer each with one word: YES, NO or REFUSE." % len(cases), ""]
        for c in cases:
            out += ["=== CASE %s ===" % c["id"], ledger(c), ""]
        with open(os.path.join(HERE, "ai_prompt_%s.txt" % w), "w", encoding="utf-8") as fh:
            fh.write("\n".join(out))
        print("wrote ai_prompt_%s.txt (%d cases)" % (w, len(cases)))


def score(which, path, label):
    cases, digest = load_key(which)
    with open(path, encoding="utf-8") as fh:
        answers = json.load(fh)
    missing = [c["id"] for c in cases if c["id"] not in answers]
    if missing:
        raise SystemExit("Missing answers: %s" % missing[:5])
    right = sum(answers[c["id"]] == c["correct"] for c in cases)
    wrong_yes = [c for c in cases if answers[c["id"]] == "YES" and c["correct"] != "YES"]
    wrong_no = [c for c in cases if answers[c["id"]] != "YES" and c["correct"] == "YES"]
    other = [c for c in cases if answers[c["id"]] != c["correct"] and c not in wrong_yes and c not in wrong_no]
    leaked = sum(c["request"] for c in wrong_yes)
    classes = {}
    for c in cases:
        r = classes.setdefault(c["class"], [0, 0])
        r[0] += 1
        r[1] += answers[c["id"]] == c["correct"]
    tag = "_b" if which == "b" else ""
    lines = ["# Sealed test: plain AI model, no graph (%s set)" % which.upper(), "",
             "The same %d cases as the main sealed test (fingerprint `%s`, checked before scoring). Model: %s. "
             "It was given the shop's rule in words and a text ledger per customer (`ai_prompt_%s.txt`), with payments marked "
             "as tied to a sale only where the shop tied them. It had no graph and none of Bashi's code, one try per case. "
             "Answers are in `results_ai_only%s.json`." % (len(cases), digest, label, which, tag), "",
             "| Method | Right | Wrongly approved | Naira wrongly approved | Wrongly refused | Other wrong |", "|---|---|---|---|---|---|",
             "| Plain AI model | %d of %d | %d | %s | %d | %d |" % (right, len(cases), len(wrong_yes), naira(leaked), len(wrong_no), len(other)),
             "", "## By kind of case", "", "| Kind | Cases | Right |", "|---|---|---|"]
    for k, (n, r) in classes.items():
        lines.append("| %s | %d | %d |" % (k, n, r))
    lines += ["", "## Every case it got wrong", "", "| Case | Kind | Story | Correct | AI said |", "|---|---|---|---|---|"]
    for c in cases:
        if answers[c["id"]] != c["correct"]:
            lines.append("| %s | %s | %s | %s | %s |" % (c["id"], c["class"], c["story"], c["correct"], answers[c["id"]]))
    lines += ["", "One model, one prompt, one run. A different model or prompt could score differently.", ""]
    with open(os.path.join(HERE, "RESULTS_ai_only%s.md" % tag), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    with open(os.path.join(HERE, "results_ai_only%s.json" % tag), "w", encoding="utf-8") as fh:
        json.dump({"fingerprint": digest, "model": label, "answers": answers}, fh, indent=1, sort_keys=True)
    print("%s: right %d/%d  wrong approvals %d (%s)  wrong refusals %d  other %d" % (
        label, right, len(cases), len(wrong_yes), naira(leaked), len(wrong_no), len(other)))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["prompts"]:
        prompts()
    elif a[:1] == ["score"] and len(a) == 4:
        score(a[1], a[2], a[3])
    else:
        raise SystemExit(__doc__)
