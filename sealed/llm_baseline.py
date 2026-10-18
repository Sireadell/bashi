"""AI without the graph: give a language model the same sealed cases as flat records and score it.

Run: python sealed/llm_baseline.py b            (the 200 set-B cases)
     python sealed/llm_baseline.py a            (the 55 set-A cases)
     python sealed/llm_baseline.py b --model gemini-flash-latest

Needs GEMINI_API_KEY in .env (GEMINI_MODEL picks the model, as in agent.py). Temperature 0.
Writes sealed/llm_results_<set>_<model>.json with every raw answer, and prints the score.

What the model gets, per case, is a spreadsheet-style export of that one customer: a table of
sales (number, date, amount), a table of payments (number, date, amount), a table of promises
(amount, made, due, kept), the credit limit, the check date and the request. It gets no links:
nothing says which payment paid which sale. It also gets the full shop rule in words, the same
rule the answer key is computed from (see make_key_b.py), so the only thing it lacks is the links.
The prompt is PROMPT below, written once and not tuned. It refuses to run if the key's
fingerprint does not match, the same check run_sealed.py does.
"""
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()
load_dotenv(os.path.join(ROOT, "..", "..", "..", ".env"))   # main checkout, when run from a worktree

from run_sealed import load_key  # noqa: E402

PROMPT = """You help a small shop decide whether to sell to a customer on credit.

The shop's rule:
1. If any sale has no amount recorded, answer CANNOT TRACE.
2. What the customer owes is, for each sale, its amount minus the payments that paid for that sale, never below zero. Extra money paid on one sale does not clear another sale.
3. A promise to pay is broken if it was not kept and its due date is before the check date.
4. Answer NO if there is a broken promise, or if what the customer owes plus the new request is more than the credit limit. Otherwise answer YES.

Below are this customer's records, exported from the shop's book as plain tables.

Check date: {as_of}
Credit limit: N{limit}
New request: N{request} on credit

Sales (number, date, amount):
{sales}

Payments received from this customer (number, date, amount):
{payments}

Promises to pay (amount, date made, due date, kept):
{promises}

Reply with JSON only, in this shape: {{"answer": "YES" or "NO" or "CANNOT TRACE", "reason": "one sentence"}}"""


def table(rows):
    return "\n".join(rows) if rows else "(none)"


def prompt_of(c):
    sales = ["S%d, %s, %s" % (s["n"], s["date"], "" if s["amount"] is None else "N%d" % s["amount"])
             for s in c["sales"]]
    pays = ["P%d, %s, N%d" % (p["n"], p["date"], p["amount"]) for p in c["payments"]]
    proms = ["N%d, 2026-06-01, %s, %s" % (p["amount"], p["due"], "yes" if p["kept"] else "no")
             for p in c["promises"]]
    return PROMPT.format(as_of=c["as_of"], limit=c["limit"], request=c["request"],
                         sales=table(sales), payments=table(pays), promises=table(proms))


def ask(model, key, text):
    body = {"contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 8192,
                                 "responseMimeType": "application/json"}}
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model,
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    for attempt in range(8):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 503) or attempt == 7:
                raise
            time.sleep(min(60, 5 * (attempt + 1)))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 7:
                raise
            time.sleep(5)


def parse(data):
    """The model's answer as YES, NO or REFUSE (CANNOT TRACE). Anything unreadable is UNREADABLE."""
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = " ".join(p["text"] for p in parts if p.get("text") and not p.get("thought")).strip()
    except (KeyError, IndexError, TypeError):
        return "UNREADABLE", ""
    try:
        ans = str(json.loads(text.strip("` \njson")).get("answer", "")).upper().strip()
    except (ValueError, AttributeError):
        ans = text.upper()
    if "CANNOT" in ans:
        return "REFUSE", text
    if ans.startswith("YES"):
        return "YES", text
    if ans.startswith("NO"):
        return "NO", text
    return "UNREADABLE", text


def main():
    which = "b" if "b" in [a.lower() for a in sys.argv[1:]] else "a"
    model = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    if "--model" in sys.argv:
        model = sys.argv[sys.argv.index("--model") + 1]
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set.")
    cases, digest = load_key(which)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Answers already received are kept in a side file, so a run cut short by the rate limit resumes.
    partial = os.path.join(HERE, ".llm_partial_%s_%s.json" % (which, model))
    raw = {}
    if os.path.exists(partial):
        with open(partial, encoding="utf-8") as fh:
            raw = json.load(fh)
    lock = threading.Lock()

    def one(c):
        if c["id"] in raw:
            return
        data = ask(model, key, prompt_of(c))
        got, text = parse(data)
        with lock:
            raw[c["id"]] = {"answer": got, "raw": text, "served_model": data.get("modelVersion"),
                            "finish": (data.get("candidates") or [{}])[0].get("finishReason")}
            with open(partial, "w", encoding="utf-8") as fh:
                json.dump(raw, fh)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(one, cases))

    right = wrong_yes = wrong_no = other = leaked = 0
    classes = {}
    for c in cases:
        got, want = raw[c["id"]]["answer"], c["correct"]
        r = classes.setdefault(c["class"], {"n": 0, "right": 0})
        r["n"] += 1
        if got == want:
            right += 1
            r["right"] += 1
        elif got == "YES":
            wrong_yes += 1
            leaked += c["request"]
        elif want == "YES":
            wrong_no += 1
        else:
            other += 1
    scores = {"right": right, "wrong_approvals": wrong_yes, "naira_wrongly_approved": leaked,
              "wrong_refusals": wrong_no, "other_wrong": other}
    served = sorted({v["served_model"] for v in raw.values() if v["served_model"]})
    out = {"set": which, "fingerprint": digest, "model_asked": model, "models_served": served,
           "temperature": 0, "started_utc": started,
           "finished_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "prompt_template": PROMPT, "scores": scores, "by_class": classes,
           "answers": {k: raw[k] for k in sorted(raw)}}
    path = os.path.join(HERE, "llm_results_%s_%s.json" % (which, model))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    os.remove(partial)
    print("%s on set %s (%d cases): right %d, wrong approvals %d (N%s), wrong refusals %d, other %d"
          % (model, which, len(cases), right, wrong_yes, "{:,}".format(leaked), wrong_no, other))
    for k, r in classes.items():
        print("  %-18s %d/%d" % (k, r["right"], r["n"]))
    print("served:", served, "->", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
