"""AI without the graph, on the 30 locked family cases (set F: 20, set G: 10).

Run once: python sealed/llm_baseline_family.py
Same model setup as llm_baseline.py (GEMINI_MODEL or gemini-flash-latest, temperature 0, same
API call and answer reader). Per case the model gets a flat list: the accounts and what each owes,
the people (what each owns and which account each collects for or pays for), the family pairs,
the credit limit of the asking account, and the request. It also gets the shop rules in words,
the family rule included. It gets no graph. The prompt is written once and not tuned.
Refuses to run if either answer key no longer matches its fingerprint.
Writes sealed/llm_results_family_<model>.json and prints the score. Scoring is done in the
script against the locked keys; RESULTS_LLM_FAMILY.md is written from that file.
"""
import hashlib
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
load_dotenv(os.path.join(ROOT, "..", "..", "..", ".env"))

from llm_baseline import ask, parse  # noqa: E402  (same call, same answer reader)

SETS = [("F", "cases_family.json", "KEY_HASH_FAMILY.txt"), ("G", "cases_family_g.json", "KEY_HASH_FAMILY_G.txt")]

PROMPT = """You help a small shop decide whether to sell to a customer on credit.

The shop's rules:
1. Say NO if what the asking account owes, plus the new request, is more than its credit limit.
2. Say NO if the customer has any broken promise to pay. (There are no promises in this case.)
3. Accounts can be linked through people. A person can own accounts. A person also collects goods for, or pays for, exactly one account. Two people can be family. Start at the asking account and follow every one of these links, any number of steps, in any direction: account to a person who owns it or collects or pays for it, person to the other accounts they own or buy for, person to their family. Every other account you reach is linked. If the asking account is linked to other accounts, say NO when what ALL the linked accounts owe together (the asking account included), plus the new request, is more than the asking account's credit limit. If it is linked to no other account, rule 1 alone decides.
4. Otherwise answer YES.

Below are the records of this shop, as plain lists.

Asking account: {ask}
Check date: {as_of}
Credit limit of the asking account: N{limit}
New request: N{request} on credit

Accounts (account, amount owed now):
{accounts}

People (person, role, account they collect for or pay for, accounts they own):
{people}

Family pairs (person, person):
{family}

Reply with JSON only, in this shape: {{"answer": "YES" or "NO" or "CANNOT TRACE", "reason": "one sentence"}}"""


def load(fname, hname):
    with open(os.path.join(HERE, fname), encoding="utf-8") as fh:
        cases = json.load(fh)
    digest = hashlib.sha256(json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    with open(os.path.join(HERE, hname), encoding="utf-8") as fh:
        if fh.read().split()[-1] != digest:
            raise SystemExit("The answer key for %s does not match its fingerprint. Not running." % fname)
    return cases


def prompt_of(c):
    accts = ["%s, N%d" % (a["id"], a["owed"]) for a in c["accounts"]]
    people = ["%s, %s, %s, %s" % (p["id"], p["role"], p["buys_for"], ", ".join(p["owns"]) or "(owns none)")
              for p in c["people"]]
    fam = ["%s, %s" % (a, b) for a, b in c["family"]]
    t = lambda rows: "\n".join(rows) if rows else "(none)"
    return PROMPT.format(ask=c["ask"], as_of=c["as_of"], limit=c["limit"], request=c["request"],
                         accounts=t(accts), people=t(people), family=t(fam))


def main():
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set.")
    cases = []
    for label, f, h in SETS:
        for c in load(f, h):
            c["set"] = label
            cases.append(c)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    raw, lock = {}, threading.Lock()

    def one(c):
        data = ask(model, key, prompt_of(c))   # ask() retries network errors and 429/500/503 itself
        got, text = parse(data)
        with lock:
            raw[c["id"]] = {"answer": got, "raw": text, "served_model": data.get("modelVersion"),
                            "finish": (data.get("candidates") or [{}])[0].get("finishReason")}

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, cases))

    score = {"right": 0, "wrong_approvals": 0, "naira_wrongly_approved": 0, "wrong_refusals": 0, "other_wrong": 0}
    rows = []
    for c in cases:
        got, want = raw[c["id"]]["answer"], c["correct"]
        if got == want:
            score["right"] += 1
        elif got == "YES":
            score["wrong_approvals"] += 1
            score["naira_wrongly_approved"] += c["request"]
        elif want == "YES":
            score["wrong_refusals"] += 1
        else:
            score["other_wrong"] += 1
        rows.append({"id": c["id"], "set": c["set"], "depth": c["depth"], "limit": c["limit"],
                     "request": c["request"], "network_owed": c["network_owed"], "correct": want,
                     "ai": got, "alone": c["alone_says"], "reason": raw[c["id"]]["raw"]})
    out = {"model_asked": model, "models_served": sorted({v["served_model"] for v in raw.values() if v["served_model"]}),
           "temperature": 0, "started_utc": started,
           "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "prompt_template": PROMPT, "scores": score, "cases": rows}
    path = os.path.join(HERE, "llm_results_family_%s.json" % model)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(model, score, "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
