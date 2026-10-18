"""Bashi agent: plain-English question in, checked answer out.

The model (if a key is set: ANTHROPIC_API_KEY first, else GEMINI_API_KEY) only chooses which lookups to run and words one
sentence. The YES/NO always comes from rules.decide, and every number, id and
name in the model's sentence is checked against the records it was given. If the
model is down, has no key, or its sentence fails the check, a fixed regex
parser and template wording answer instead, and the reply says which mode ran.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from dotenv import load_dotenv

import rules
from rules import CANNOT_TRACE, naira, read_state

load_dotenv()

MODEL = "claude-haiku-5-5"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
BASE_URL = os.environ.get("BASHI_BASE_URL", "http://127.0.0.1:5000")

# ------------------------------------------------------------------ parsing

_AMT = re.compile(
    r"(?<![A-Za-z0-9])(?:N|₦|NGN\s?)\s?(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)?(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])(\d[\d,]*(?:\.\d+)?)\s*(k|m|thousand|million)(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9-])(\d[\d,]{2,})(?![\d-])",
    re.I,
)
_MULT = {"k": 1000, "thousand": 1000, "m": 1000000, "million": 1000000}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_amounts(text):
    out = []
    for m in _AMT.finditer(text):
        num = m.group(1) or m.group(3) or m.group(5)
        suffix = (m.group(2) or m.group(4) or "").lower()
        try:
            val = float(num.replace(",", ""))
        except ValueError:
            continue
        val = int(round(val * _MULT.get(suffix, 1)))
        if val > 0:
            out.append(val)
    return out


def parse_due(text, today=None):
    today = today or date.today()
    low = text.lower()
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", low)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return None
    if "tomorrow" in low:
        return (today + timedelta(days=1)).isoformat()
    if "next week" in low:
        return (today + timedelta(days=7)).isoformat()
    m = re.search(r"\bin (\d{1,3}) days?\b", low)
    if m:
        return (today + timedelta(days=int(m.group(1)))).isoformat()
    for i, wd in enumerate(_WEEKDAYS):
        if re.search(r"\b%s\b" % wd, low):
            ahead = (i - today.weekday()) % 7 or 7
            return (today + timedelta(days=ahead)).isoformat()
    return None


def match_customers(text, customers):
    """Customers whose id or name words appear in the text. Best match only."""
    low = text.lower()
    ids = [c for c in customers if re.search(r"\b%s\b" % c["id"].lower(), low)]
    if len(ids) == 1:
        return ids
    words = set(re.findall(r"[a-z]+", low))
    scored = []
    for c in customers:
        toks = [t for t in re.findall(r"[a-z]+", c["name"].lower()) if len(t) >= 3]
        s = sum(1 for t in toks if t in words)
        if s:
            scored.append((s, c))
    if not scored:
        return []
    best = max(s for s, _ in scored)
    return [c for s, c in scored if s == best]


def parse_question(text, customers):
    low = text.lower()
    amounts = parse_amounts(text)
    cands = match_customers(text, customers)
    if re.search(r"\bpromis\w*", low):
        kind = "promise"
    elif amounts:
        kind = "decide"
    elif re.search(r"how much|most|maximum|max\b|up to|limit|afford|allowed", low):
        kind = "headroom"
    else:
        kind = "unclear"
    return {
        "kind": kind,
        "amount": amounts[0] if amounts else None,
        "due": parse_due(text) if kind == "promise" else None,
        "candidates": cands,
        "customer": cands[0] if len(cands) == 1 else None,
    }


# ------------------------------------------------------------------ graph helpers

def list_customers(graph):
    rows = graph.query(
        "MATCH (c:Customer) RETURN c.id, c.name, c.credit_limit ORDER BY c.id").result_set
    return [{"id": r[0], "name": r[1], "limit": r[2]} for r in rows]


def record_promise(graph, customer_id, amount, due, today=None):
    """Write a Promise node (episodic memory). It starts as kept=false with no
    BROKE link. The rule check adds the link once the due date has passed."""
    pid = rules.allocate_id(graph, "promise")
    graph.query(
        "MATCH (c:Customer {id:$cid}) "
        "CREATE (c)-[:PROMISED]->(:Promise {id:$pid, date:$d, due:$due, amount:$amt, kept:false})",
        {"cid": customer_id, "pid": pid, "d": (today or date.today()).isoformat(),
         "due": due, "amt": amount})
    return pid


def open_promises(state):
    return sorted(
        ({"id": k, "amount": v["amount"], "due": v["due"]}
         for k, v in state["promises"].items() if not v["broke"] and not v["kept"]),
        key=lambda p: p["id"])


# ------------------------------------------------------------------ one question

class Run:
    """Everything that happens for one question. Holds the trusted results."""

    def __init__(self, graph, question):
        self.graph = graph
        self.question = question
        rules.mark_overdue_promises(graph)
        self.customers = list_customers(graph)
        self.parsed = parse_question(question, self.customers)
        self.by_id = {c["id"]: c for c in self.customers}
        self.seen_ids = set()      # customer ids the model has looked up
        self.tool_results = []     # every result, for the claims check
        self.decision = None       # (customer_id, amount, result) from rules.decide
        self.promise = None        # {id, customer_id, amount, due}
        self.blocked = []

    # --- the arbiter: which customer / amount this question is really about
    def target_customer(self, model_cid=None):
        if self.parsed["customer"]:
            return self.parsed["customer"]["id"]
        if model_cid in self.seen_ids and model_cid in self.by_id:
            return model_cid
        return None

    def headroom(self, cid):
        st = read_state(self.graph, cid)
        if st is None:
            return None
        ev = rules.evaluate(st, 1)
        if ev["verdict"] == CANNOT_TRACE:
            return None
        return max(ev["limit"] - ev["open_debt"], 0)

    def target_amount(self, cid, model_amount=None):
        if self.parsed["kind"] == "headroom":
            room = self.headroom(cid)
            return room if room else 1
        if self.parsed["amount"]:
            return self.parsed["amount"]
        if isinstance(model_amount, int) and not isinstance(model_amount, bool) and model_amount > 0:
            return model_amount
        return None

    # --- tools (the only things the model can touch)
    def tool(self, name, args):
        try:
            out = self._tool(name, args or {})
        except Exception as e:
            out = {"error": "tool failed: " + type(e).__name__}
        self.tool_results.append(out)
        return out

    def _tool(self, name, args):
        if name == "find_customer":
            q = str(args.get("name", ""))
            hits = match_customers(q, self.customers)
            for c in hits:
                self.seen_ids.add(c["id"])
            return {"matches": [{"id": c["id"], "name": c["name"], "credit_limit": c["limit"]}
                                for c in hits]}
        cid = args.get("customer_id")
        if name in ("open_debt", "broken_promises", "run_decision", "record_promise"):
            if cid not in self.by_id:
                return {"error": "unknown customer id"}
        if name == "open_debt":
            st = read_state(self.graph, cid)
            ev = rules.evaluate(st, 1)
            if ev["verdict"] == CANNOT_TRACE:
                return {"customer_id": cid, "error": rules.CANNOT_TRACE_TEXT}
            return {"customer_id": cid, "open_debt": ev["open_debt"], "credit_limit": ev["limit"],
                    "room_left": max(ev["limit"] - ev["open_debt"], 0)}
        if name == "broken_promises":
            st = read_state(self.graph, cid)
            return {"customer_id": cid,
                    "broken": [{"id": k, "amount": v["amount"], "due": v["due"]}
                               for k, v in sorted(st["promises"].items()) if v["broke"]],
                    "open_promises": open_promises(st)}
        if name == "run_decision":
            return self._run_decision(cid, args.get("amount"))
        if name == "record_promise":
            return self._record_promise(cid, args.get("amount"), args.get("due"))
        return {"error": "unknown tool"}

    def _run_decision(self, cid, amount):
        if self.parsed["kind"] not in ("decide", "headroom", "unclear"):
            return {"error": "this question is not a credit request"}
        want_cid = self.target_customer(cid)
        want_amt = self.target_amount(want_cid, amount) if want_cid else None
        if want_cid is None or want_amt is None:
            return {"error": "customer or amount is not clear from the question"}
        if cid != want_cid or amount != want_amt:
            self.blocked.append(("run_decision", cid, amount))
            return {"error": "arguments do not match the question; use customer_id %s and amount %s"
                             % (want_cid, want_amt)}
        return self._decide(want_cid, want_amt)

    def _decide(self, cid, amount):
        if self.decision and self.decision[:2] == (cid, amount):
            res = self.decision[2]
        else:
            res = rules.decide(cid, amount, graph=self.graph, save=True)
            self.decision = (cid, amount, res)
        return {k: res[k] for k in ("verdict", "reason", "open_debt", "limit",
                                    "broken_promises", "decision_id")}

    def _record_promise(self, cid, amount, due):
        if self.parsed["kind"] != "promise":
            return {"error": "this question is not a promise"}
        want_cid = self.target_customer(cid)
        want_amt = self.parsed["amount"] or (amount if isinstance(amount, int) else None)
        want_due = self.parsed["due"] or (due if isinstance(due, str) and parse_due(due) == due else None)
        if want_cid is None or not want_amt or not want_due:
            return {"error": "customer, amount or due date is not clear from the question"}
        if (cid, amount, due) != (want_cid, want_amt, want_due):
            self.blocked.append(("record_promise", cid, amount))
            return {"error": "arguments do not match the question; use customer_id %s amount %s due %s"
                             % (want_cid, want_amt, want_due)}
        return self._promise(want_cid, want_amt, want_due)

    def _promise(self, cid, amount, due):
        if not self.promise:
            pid = record_promise(self.graph, cid, amount, due)
            self.promise = {"id": pid, "customer_id": cid, "amount": amount, "due": due}
        return dict(self.promise)

    # --- if the model did not do the job, the code does it
    def finish(self):
        k = self.parsed["kind"]
        cid = self.target_customer()
        if k == "promise" and not self.promise and cid and self.parsed["amount"] and self.parsed["due"]:
            self.tool_results.append(self._promise(cid, self.parsed["amount"], self.parsed["due"]))
        if k in ("decide", "headroom") and not self.decision and cid:
            amt = self.target_amount(cid)
            if amt:
                self.tool_results.append(self._decide(cid, amt))
        # model-guided path with no parser help (e.g. "forty five thousand"): no decision, no guess


# ------------------------------------------------------------------ wording

def receipt_url(decision_id):
    return "%s/receipt/%s" % (BASE_URL.rstrip("/"), decision_id)


def build_reply(run, middle=None):
    """Head and tail are always code-made. `middle` is an already-checked model sentence."""
    p = run.parsed
    if run.promise:
        pr = run.promise
        name = run.by_id[pr["customer_id"]]["name"]
        tail = "Saved as %s. It will be checked on %s, and counts as broken if still unpaid then." % (
            pr["id"], pr["due"])
        text = "Noted. %s promised to pay %s by %s. %s" % (
            name, naira(pr["amount"]), pr["due"], tail)
        return text if not middle else "Noted. %s %s" % (middle, tail)
    if run.decision:
        cid, amount, res = run.decision
        name = run.by_id[cid]["name"]
        if res["verdict"] == CANNOT_TRACE:
            return "I cannot decide this one: %s." % res["reason"]
        if p["kind"] == "headroom" and res["verdict"] == "YES":
            head = "YES up to %s." % naira(amount)
        elif res["verdict"] == "YES":
            head = "YES. %s can take %s on credit." % (name, naira(amount))
        elif p["kind"] == "headroom":
            head = "NO. %s cannot take any more credit right now." % name
        else:
            head = "NO. %s should not get %s on credit." % (name, naira(amount))
        st = read_state(run.graph, cid)
        ops = open_promises(st) if st else []
        extra = ""
        if ops:
            extra = " Promises on record: " + ", ".join(
                "%s %s due %s" % (o["id"], naira(o["amount"]), o["due"]) for o in ops) + "."
        parts = [head]
        if middle:
            parts.append(middle)
        parts.append("Path: %s.%s" % (res["reason"], extra))
        parts.append("Receipt %s: %s" % (res["decision_id"], receipt_url(res["decision_id"])))
        return " ".join(parts)
    # nothing to decide: say what is missing
    if len(p["candidates"]) > 1:
        return "Which customer? I found: " + ", ".join(
            "%s (%s)" % (c["name"], c["id"]) for c in p["candidates"]) + "."
    if not p["candidates"]:
        return "I could not find that customer. Use a name or an id from the customer list."
    if p["kind"] == "promise":
        return "I need an amount and a date, for example: Tunde promised to pay N10,000 on Friday."
    return "How much credit is %s asking for? For example: Can %s take N45,000 on credit?" % (
        p["candidates"][0]["name"].split()[0], p["candidates"][0]["name"].split()[0])


_VERDICT_WORDS = re.compile(
    r"\b(yes|no|not|never|approv\w*|declin\w*|reject\w*|grant\w*|allow\w*|den(y|ied)|refus\w*|"
    r"safe|risky|fine|ok|okay|should|can|cannot|can't|sure|good|great|trust\w*|welcome|"
    r"eligible|qualif\w*|ready)\b", re.I)
_ID = re.compile(r"\b[A-Z]{1,2}\d{3,4}\b")
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def check_claims(text, run):
    """Return None if every claim in the sentence matches the records, else why not."""
    if not text or len(text) > 400:
        return "empty or too long"
    if "http" in text.lower() or "\n" in text.strip():
        return "link or multiple lines"
    if _VERDICT_WORDS.search(text):
        return "verdict-style wording"
    facts = json.dumps(run.tool_results) + " " + json.dumps(
        {"parsed": run.parsed["amount"], "decision": run.decision[1] if run.decision else None,
         "promise": run.promise})
    if run.decision:
        facts += " " + run.decision[2]["reason"]
        facts += json.dumps({k: v for k, v in run.decision[2].items() if k != "evidence"})
    facts_nums = {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", facts) if n.replace(",", "").isdigit()}
    if not re.search(r"\d", text):
        return "no figure from the records"
    facts_dates = set(_DATE.findall(facts))
    facts_ids = set(_ID.findall(facts))
    for d in _DATE.findall(text):
        if d not in facts_dates:
            return "date not in records: " + d
    scrubbed = _DATE.sub(" ", text)
    for i in _ID.findall(scrubbed):
        if i not in facts_ids:
            return "id not in records: " + i
    scrubbed = _ID.sub(" ", scrubbed)
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?\s*(k|m)?\b", scrubbed, re.I):
        raw = m.group(0).strip()
        mult = _MULT.get((m.group(1) or "").lower(), 1)
        try:
            val = int(round(float(re.sub(r"[a-z\s,]", "", raw, flags=re.I)) * mult))
        except ValueError:
            return "unreadable number"
        if val not in facts_nums:
            return "amount not in records: %s" % raw
    # names: only the customer this answer is about
    subject = None
    if run.decision:
        subject = run.decision[0]
    elif run.promise:
        subject = run.promise["customer_id"]
    allowed = set(re.findall(r"[a-z]+", run.by_id[subject]["name"].lower())) if subject else set()
    for c in run.customers:
        for tok in re.findall(r"[a-z]+", c["name"].lower()):
            if len(tok) >= 3 and tok not in allowed and re.search(r"\b%s\b" % tok, text.lower()):
                return "other customer name: " + tok
    return None


SYSTEM = (
    "You help a small Nigerian shop owner with credit questions. You pick lookups; you never decide. "
    "For a credit question call find_customer, then open_debt and broken_promises if useful, then run_decision "
    "with the exact customer and amount from the question. For 'X promised to pay N.. on <day>' call "
    "find_customer then record_promise with an ISO due date. For 'how much can X take' call run_decision "
    "with amount = the credit limit minus open debt from open_debt (room_left). "
    "When done, reply with ONE short plain sentence that adds context from the tool results only "
    "(amounts and ids exactly as given). Do not say yes, no, approved, declined or any verdict, do not "
    "name anyone but the customer, do not add links. The shop's fixed rule check decides, not you."
)

TOOLS = [
    {"name": "find_customer", "description": "Find customers by name or id.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "open_debt", "description": "Open debt, credit limit and room left for one customer.",
     "input_schema": {"type": "object", "properties": {"customer_id": {"type": "string"}},
                      "required": ["customer_id"]}},
    {"name": "broken_promises", "description": "Broken and open promises to pay for one customer.",
     "input_schema": {"type": "object", "properties": {"customer_id": {"type": "string"}},
                      "required": ["customer_id"]}},
    {"name": "run_decision",
     "description": "Run the fixed credit rule check for a customer and amount in naira. Saves a receipt.",
     "input_schema": {"type": "object", "properties": {"customer_id": {"type": "string"},
                                                       "amount": {"type": "integer"}},
                      "required": ["customer_id", "amount"]}},
    {"name": "record_promise", "description": "Record that a customer promised to pay an amount by a date.",
     "input_schema": {"type": "object",
                      "properties": {"customer_id": {"type": "string"}, "amount": {"type": "integer"},
                                     "due": {"type": "string", "description": "ISO date YYYY-MM-DD"}},
                      "required": ["customer_id", "amount", "due"]}},
]


class GeminiClient:
    """Plain HTTPS client for Google's Gemini API. Same two jobs as the Claude route:
    choose lookups and word one sentence. The key goes in a header, never in the
    address, and is never printed."""

    provider = "gemini"

    def __init__(self, api_key, model=None, timeout=25.0):
        self.api_key = api_key
        self.model = model or GEMINI_MODEL
        self.timeout = timeout
        self.served = None   # the exact model version Google says answered

    def generate(self, contents):
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": contents,
            "tools": [{"functionDeclarations": [
                {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}
                for t in TOOLS]}],
            "generationConfig": {"maxOutputTokens": 2048, "temperature": 0},
        }
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % self.model,
            data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key})
        data = None
        for attempt in range(3):   # Google sometimes answers 503 "high demand"; retry briefly
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode())
                break
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 503) or attempt == 2:
                    raise
                time.sleep(1.5 * (attempt + 1))
        self.served = data.get("modelVersion") or self.served
        return data

    @property
    def label(self):
        return "Google " + (self.served or self.model)


def make_client():
    """A model client, or None when no key is set. Claude first, then Gemini.
    Keys are never printed."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        return anthropic.Anthropic(timeout=25.0, max_retries=1)
    if os.environ.get("GEMINI_API_KEY"):
        return GeminiClient(os.environ["GEMINI_API_KEY"])
    return None


def model_label(client):
    if getattr(client, "provider", "") == "gemini":
        return client.label
    return "Claude " + MODEL


def run_gemini(client, run):
    contents = [{"role": "user", "parts": [{"text": run.question}]}]
    for _ in range(7):
        data = client.generate(contents)
        content = data["candidates"][0]["content"]
        parts = content.get("parts") or []
        contents.append({"role": "model", "parts": parts})
        if data["candidates"][0].get("finishReason") == "MAX_TOKENS":
            return ""   # cut-off sentence: never show it
        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if calls:
            replies = []
            for c in calls:
                out = run.tool(c.get("name", ""), dict(c.get("args") or {}))
                replies.append({"functionResponse": {"name": c.get("name", ""), "response": out}})
            contents.append({"role": "user", "parts": replies})
            continue
        return " ".join(p["text"] for p in parts if p.get("text") and not p.get("thought")).strip()
    return ""


def run_model(client, run):
    if getattr(client, "provider", "") == "gemini":
        return run_gemini(client, run)
    msgs = [{"role": "user", "content": run.question}]
    for _ in range(7):
        resp = client.messages.create(model=MODEL, max_tokens=400, system=SYSTEM,
                                      tools=TOOLS, messages=msgs)
        msgs.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "tool_use":
            results = []
            for b in resp.content:
                if b.type == "tool_use":
                    out = run.tool(b.name, dict(b.input or {}))
                    results.append({"type": "tool_result", "tool_use_id": b.id,
                                    "content": json.dumps(out)})
            msgs.append({"role": "user", "content": results})
            continue
        return " ".join(b.text for b in resp.content if b.type == "text").strip()
    return ""


def ask(question, graph=None, client=None):
    """Answer one question. Returns a dict; `reply` is the text for the shop owner."""
    if graph is None:
        from db import get_graph
        graph = get_graph()
    run = Run(graph, question)
    mode, note, middle = "fallback", "", None
    if client is None:
        try:
            client = make_client()
        except Exception as e:
            client, note = None, "model unavailable: " + type(e).__name__
        if client is None and not note:
            note = "no API key set"
    model_text = ""
    if client is not None:
        try:
            model_text = run_model(client, run)
            mode = "model"
        except Exception as e:  # never show details, they could contain request data
            note = "model unavailable: " + type(e).__name__
    run.finish()
    if mode == "model":
        why = check_claims(model_text, run) if (run.decision or run.promise) else "nothing to word"
        if why is None:
            middle = model_text
        else:
            mode, note = "fallback", "model wording rejected (%s)" % why
    reply = build_reply(run, middle)
    label = model_label(client) if mode == "model" else "built-in parser and fixed wording"
    d = run.decision
    return {
        "mode": mode, "note": note, "answered_by": label,
        "reply": reply + "\n[answered by: %s]" % label,
        "verdict": d[2]["verdict"] if d else None,
        "decision_id": d[2]["decision_id"] if d else None,
        "receipt_url": receipt_url(d[2]["decision_id"]) if d and d[2]["decision_id"] else None,
        "customer_id": d[0] if d else (run.promise or {}).get("customer_id"),
        "amount": d[1] if d else None,
        "promise_id": run.promise["id"] if run.promise else None,
        "blocked_model_calls": len(run.blocked),
    }


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "Can Tunde take N45,000 on credit?"
    out = ask(q)
    print(out["reply"])
    if out["note"]:
        print("(%s)" % out["note"])
