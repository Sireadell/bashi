"""The agent door: one set of functions behind both the JSON routes (/api/...)
and the MCP tools (/mcp and mcp_stdio.py), so the two can never drift apart.

Nothing here calls an AI model. A decision is the plain rules in rules.py.
Every function returns a plain dict, or raises ApiError with a status code and
a message that is safe to show. Database errors are never passed on.
"""
import json
import re

CANNOT_TRACE_WORDS = "CANNOT TRACE"
MAX_AMOUNT = 1_000_000_000_000          # N1 trillion, far above any shop sale
MAX_REMOVE = 10
_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_DECISION_ID = re.compile(r"^D\d{1,9}$")
SHOP_NAMES = {"shop_a": "demo", "shop_own": "own"}

SERVER_NAME = "Bashi"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-06-18"


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def _app():
    # Imported late: app.py imports this module, and this one needs its graph helpers.
    import app
    return app


# ---------------------------------------------------------------- input checks

def check_customer(value):
    if not isinstance(value, str) or not _ID.match(value.strip()):
        raise ApiError(400, "customer must be a customer id from the customer list "
                            "(letters, numbers, dash or underscore). Use list_customers to see them.")
    return value.strip()


def check_amount(value):
    if isinstance(value, bool):
        raise ApiError(400, "amount must be a positive whole number of naira, for example 45000.")
    if isinstance(value, str):
        cleaned = value.replace(",", "").replace("N", "").strip()
        if not cleaned.isdigit():
            raise ApiError(400, "amount must be a positive whole number of naira, for example 45000.")
        value = int(cleaned)
    elif isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int) or value <= 0:
        raise ApiError(400, "amount must be a positive whole number of naira, for example 45000.")
    if value > MAX_AMOUNT:
        raise ApiError(400, "amount is too large. The most Bashi will check is N%s." % format(MAX_AMOUNT, ","))
    return value


def check_decision_id(value):
    if not isinstance(value, str) or not _DECISION_ID.match(value.strip()):
        raise ApiError(400, "decision id must look like D0001.")
    return value.strip()


def check_remove(value):
    """One record id, a comma separated string, or a list. Returns a list of ids."""
    if isinstance(value, str):
        value = [v for v in value.split(",") if v.strip()]
    if not isinstance(value, list) or not value:
        raise ApiError(400, "remove must name at least one record id, for example PR001.")
    if len(value) > MAX_REMOVE:
        raise ApiError(400, "remove can name at most %d records." % MAX_REMOVE)
    out = []
    for v in value:
        if not isinstance(v, str) or not _ID.match(v.strip()):
            raise ApiError(400, "remove must hold record ids such as PR001 or T0003.")
        out.append(v.strip())
    return out


# ---------------------------------------------------------------- which shop

def resolve_shop(shop):
    """None means the same default as the web page: the own shop when loaded, else the demo shop.
    Returns (key, graph name)."""
    a = _app()
    if shop is None or shop == "":
        key = "own" if a.own_available() else "demo"
    elif shop in SHOP_NAMES:
        key = SHOP_NAMES[shop]
        if key == "own" and not a.own_available():
            raise ApiError(400, "shop_own is not loaded right now. Use shop_a (the demo shop).")
    else:
        raise ApiError(400, "shop must be shop_a (demo data) or shop_own (the founder's own shop, names removed).")
    return key, a.GRAPH_OF[key]


def _graph(name):
    return _app().get_graph(name)


def find_decision(decision_id):
    """(shop key, graph) holding this decision, or None. The own shop is tried first when loaded."""
    a = _app()
    order = (["own"] if a.own_available() else []) + ["demo"]
    for key in order:
        try:
            g = _graph(a.GRAPH_OF[key])
            if a.load_decision(decision_id, g) is not None:
                return key, g
        except Exception:
            continue
    return None


def _links(decision_id, base_url):
    return {"receipt_url": "%s/receipt/%s" % (base_url, decision_id),
            "receipt_json_url": "%s/api/receipt/%s" % (base_url, decision_id),
            "verify_url": "%s/api/verify/%s" % (base_url, decision_id)}


def _answer(verdict):
    return CANNOT_TRACE_WORDS if verdict == "CANNOT_TRACE" else verdict


def _reasons(text):
    out = []
    for part in (text or "").split("; "):
        part = part.strip()
        if part:
            out.append(part[0].upper() + part[1:])
    return out


def _guard(fn):
    """Run fn; turn anything unexpected into one safe message."""
    try:
        return fn()
    except ApiError:
        raise
    except ValueError as e:
        raise ApiError(404, "unknown decision") from e
    except Exception as e:
        raise ApiError(503, "Bashi could not finish that just now. Try again in a minute.") from e


# ---------------------------------------------------------------- the five actions

def decide_credit(customer, amount, shop=None, base_url=""):
    customer, amount = check_customer(customer), check_amount(amount)
    key, gname = resolve_shop(shop)

    def run():
        a = _app()
        g = _graph(gname)
        if not g.query("MATCH (c:Customer {id:$c}) RETURN c.id", {"c": customer}).result_set:
            raise ApiError(404, "No customer %s in this shop. Use list_customers to see the ids." % customer)
        res = a.decide(customer, amount, graph=g)
        try:
            a.prune_decisions(g)          # the same 300-decision cap the web page keeps
        except Exception:
            pass
        out = {"answer": _answer(res["verdict"]), "customer": customer, "amount": amount,
               "shop": "shop_own" if key == "own" else "shop_a",
               "reason": res["reason"], "reasons": _reasons(res["reason"]),
               "open_debt": res["open_debt"], "limit": res["limit"],
               "broken_promises": res["broken_promises"],
               "decision_id": res["decision_id"], "fingerprint": res["fingerprint"],
               "evidence_ids": [e["id"] for e in res["evidence"]],
               "warnings": ["%s counts as owed, but unlinked payment %s has the same amount (%s). "
                            "The debt is left as recorded." % (p["trade"], p["payment"], a.naira(p["amount"]))
                            for p in res.get("possible_phantoms", [])]}
        if res["decision_id"]:
            out.update(_links(res["decision_id"], base_url))
        else:
            out.update(receipt_url=None, receipt_json_url=None, verify_url=None)
        return out
    return _guard(run)


def get_receipt(decision_id, base_url=""):
    decision_id = check_decision_id(decision_id)

    def run():
        a = _app()
        found = find_decision(decision_id)
        data = a.build_receipt(*found, decision_id) if found else None
        if data is None:
            raise ApiError(404, "No decision %s. Receipts are kept for the most recent 300 decisions." % decision_id)
        dec = data["dec"]
        out = {"id": dec["id"], "answer": _answer(dec["verdict"]),
               "customer": {"id": dec["customer_id"], "name": dec["customer_name"], "limit": dec["limit"]},
               "amount": dec["request"], "reason": dec["reason"], "reasons": _reasons(dec["reason"]),
               "open_debt": data["open_debt"], "created": dec["created"], "as_of": dec["as_of"],
               "fingerprint": dec["fingerprint"],
               "rules": [{"id": r, "text": a.RULES.get(r, "")} for r in json.loads(dec["rule_ids"] or "[]")],
               "sales": data["trades"], "payments": data["payments"], "promises": data["promises"],
               "unlinked_payments_that_may_match_a_sale": data["orphans"],
               "evidence_ids": [x["id"] for k in ("trades", "payments", "promises") for x in data[k]],
               "check": data["verify"], "data_label": data["banner"]}
        out.update(_links(decision_id, base_url))
        return out
    return _guard(run)


def verify_decision(decision_id):
    decision_id = check_decision_id(decision_id)

    def run():
        a = _app()
        found = find_decision(decision_id)
        if not found:
            raise ApiError(404, "No decision %s. Receipts are kept for the most recent 300 decisions." % decision_id)
        g = found[1]
        row = g.query("MATCH (d:Decision {id:$d}) RETURN d.id, d.customer_id, d.request, d.verdict, "
                      "d.fingerprint, d.snapshot", {"d": decision_id}).result_set
        if not row:
            raise ApiError(404, "No decision %s." % decision_id)
        ok, problems = _verify(g, tuple(row[0]))
        detail = ("Every record matches what was saved, and running the rule again gives the same answer."
                  if ok else "; ".join(problems))
        return {"id": decision_id, "verified": bool(ok), "detail": detail}
    return _guard(run)


def _verify(g, d):
    from verify import verify_decision as replay
    return replay(g, d)


def what_if_remove_evidence(decision_id, remove):
    decision_id, remove = check_decision_id(decision_id), check_remove(remove)

    def run():
        a = _app()
        found = find_decision(decision_id)
        if not found:
            raise ApiError(404, "No decision %s. Receipts are kept for the most recent 300 decisions." % decision_id)
        key, g = found
        used = {r[0] for r in g.query(
            "MATCH (:Decision {id:$d})-[:USED_EVIDENCE]->(e) RETURN e.id", {"d": decision_id}).result_set}
        unused = [r for r in remove if r not in used]
        if unused:
            raise ApiError(400, "Decision %s did not use %s. Its records: %s."
                           % (decision_id, ", ".join(unused), ", ".join(sorted(used)) or "none"))
        res = a.whatif(decision_id, remove, graph_name=a.GRAPH_OF[key])
        return {"decision_id": decision_id, "removed": res["removed"],
                "original_answer": _answer(res["original_verdict"]),
                "new_answer": _answer(res["new_verdict"]),
                "changed": res["changed"], "new_reason": res["new_reason"],
                "new_open_debt": res["new_open_debt"],
                "note": res["note"], "real_graph_untouched": True}
    return _guard(run)


def list_customers(shop=None):
    key, gname = resolve_shop(shop)

    def run():
        a = _app()
        rows = _graph(gname).query(
            "MATCH (c:Customer) RETURN c.id, c.name, c.credit_limit, c.source ORDER BY c.id").result_set
        return {"shop": "shop_own" if key == "own" else "shop_a", "data_label": a.PRACTICE_LABEL if key == "demo" else a.OWN_LABEL,
                "customers": [{"id": r[0], "name": r[1], "credit_limit": r[2], "tag": a.TAG.get(r[3])} for r in rows]}
    return _guard(run)


# ---------------------------------------------------------------- MCP tools

SHOP_PROP = {"type": "string", "enum": ["shop_a", "shop_own"],
             "description": "Which shop. shop_a is the demo shop (synthetic data). shop_own is the founder's "
                            "own shop with names removed. Leave out to use the same default as the website."}

TOOLS = [
    {"name": "decide_credit",
     "description": "Ask whether a customer can take an amount on credit. Returns YES, NO or CANNOT TRACE with "
                    "the reasons in plain words, a decision id, a receipt link a person can open, a verify link "
                    "the agent can re-check, and the ids of the records used. Fixed rules, no AI guess. "
                    "It saves the decision so it can be re-checked.",
     "inputSchema": {"type": "object", "properties": {
         "customer": {"type": "string", "description": "Customer id, for example C001. See list_customers."},
         "amount": {"type": "integer", "minimum": 1, "maximum": MAX_AMOUNT,
                    "description": "Amount in whole naira, for example 45000."},
         "shop": SHOP_PROP}, "required": ["customer", "amount"], "additionalProperties": False}},
    {"name": "get_receipt",
     "description": "Get the full receipt for a saved decision: the answer, the rules, and every sale, payment "
                    "and promise it used, with their ids.",
     "inputSchema": {"type": "object", "properties": {
         "decision_id": {"type": "string", "description": "Decision id, for example D0001."}},
         "required": ["decision_id"], "additionalProperties": False}},
    {"name": "verify_decision",
     "description": "Re-check one saved decision. Bashi re-reads the records it used and runs the rule again. "
                    "Returns verified true only if nothing was changed since and the answer is the same.",
     "inputSchema": {"type": "object", "properties": {
         "decision_id": {"type": "string", "description": "Decision id, for example D0001."}},
         "required": ["decision_id"], "additionalProperties": False}},
    {"name": "what_if_remove_evidence",
     "description": "Ask what the answer would be if a record had never existed, for example a broken promise. "
                    "Runs on a throwaway copy that is deleted straight after. The real shop is never changed.",
     "inputSchema": {"type": "object", "properties": {
         "decision_id": {"type": "string", "description": "Decision id, for example D0001."},
         "remove": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": MAX_REMOVE,
                    "description": "Record ids the decision used, for example [\"PR001\"]."}},
         "required": ["decision_id", "remove"], "additionalProperties": False}},
    {"name": "list_customers",
     "description": "List the customers in a shop with their ids, names and credit limits.",
     "inputSchema": {"type": "object", "properties": {"shop": SHOP_PROP}, "additionalProperties": False}},
]

WRITE_TOOLS = {"decide_credit", "what_if_remove_evidence"}   # these save or copy data, so the strict limit applies


def run_tool(name, args, base_url=""):
    """Run one tool. Returns the result dict, or raises ApiError."""
    if not isinstance(args, dict):
        raise ApiError(400, "arguments must be an object")
    if name == "decide_credit":
        return decide_credit(args.get("customer"), args.get("amount"), args.get("shop"), base_url)
    if name == "get_receipt":
        return get_receipt(args.get("decision_id"), base_url)
    if name == "verify_decision":
        return verify_decision(args.get("decision_id"))
    if name == "what_if_remove_evidence":
        return what_if_remove_evidence(args.get("decision_id"), args.get("remove"))
    if name == "list_customers":
        return list_customers(args.get("shop"))
    raise ApiError(404, "unknown tool " + str(name)[:60])


def server_info(base_url=""):
    return {"name": SERVER_NAME, "version": SERVER_VERSION, "protocol": PROTOCOL_VERSION,
            "about": "Bashi answers one question for a shop: can this customer take this amount on credit? "
                     "It gives YES or NO with a receipt that links the exact records used, and anyone can re-check it.",
            "endpoint": base_url + "/mcp", "transport": "streamable HTTP, JSON replies, no sessions",
            "tools": [{"name": t["name"], "description": t["description"]} for t in TOOLS],
            "docs": base_url + "/AGENTS.md"}


def _rpc_error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def handle_rpc(msg, base_url="", guard=None):
    """Handle one JSON-RPC message. Returns the reply dict, or None when no reply is due
    (a notification). guard(tool_name) may return a message to refuse a tool call."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        return _rpc_error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid request")
    method, rid = msg["method"], msg.get("id")
    if "id" not in msg:                       # a notification: nothing to answer
        return None
    params = msg.get("params") or {}
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": "Use list_customers to find a customer id, then decide_credit. Keep the "
                            "decision id: get_receipt, verify_decision and what_if_remove_evidence all take it."}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return _rpc_error(rid, -32602, "tools/call needs a tool name")
        name = params["name"]
        if name not in {t["name"] for t in TOOLS}:
            return _rpc_error(rid, -32602, "Unknown tool: " + name[:60])
        refused = guard(name) if guard else None
        try:
            if refused:
                raise ApiError(429, refused)
            result = run_tool(name, params.get("arguments") or {}, base_url)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                "structuredContent": result, "isError": False}}
        except ApiError as e:
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": e.message}], "isError": True}}
    return _rpc_error(rid, -32601, "Method not found: " + method[:60])
