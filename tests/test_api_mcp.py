"""The agent door: JSON routes under /api, the MCP endpoint at /mcp, and the stdio server.

Every test works on a private copy of the demo shop (the `graph` fixture), deleted afterwards.
"""
import io
import json
import time

import pytest

import agent_api
import app as webapp
import mcp_stdio
import whatif
from db import get_db


@pytest.fixture()
def client(graph, monkeypatch):
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": graph)
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": graph)
    # Pretend the own shop is not loaded, so the default shop is the demo copy.
    monkeypatch.setitem(webapp._own_seen, "at", time.time())
    monkeypatch.setitem(webapp._own_seen, "ok", False)
    webapp.reset_limits()
    yield webapp.app.test_client()
    webapp.reset_limits()


def whatif_copies():
    return {n for n in get_db().list_graphs() if n.startswith("shop_a_whatif_")}


def decide_tunde(client):
    r = client.post("/api/decide", json={"customer": "C001", "amount": 45000})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


def rpc(client, method, params=None, rid=1):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body)


def call(client, name, arguments):
    r = rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert r.status_code == 200
    return r.get_json()["result"]


# ---------------------------------------------------------------- JSON routes: happy paths

def test_decide_gives_answer_reasons_links_and_evidence(client, graph):
    out = decide_tunde(client)
    assert out["answer"] == "NO" and out["shop"] == "shop_a"
    assert any("PR001" in r for r in out["reasons"])
    assert out["decision_id"].startswith("D") and len(out["fingerprint"]) == 64
    assert "PR001" in out["evidence_ids"]
    assert out["receipt_url"].endswith("/receipt/" + out["decision_id"])
    assert out["verify_url"].endswith("/api/verify/" + out["decision_id"])
    assert out["receipt_url"].startswith("http")
    assert graph.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0] == 1


def test_decide_yes_and_explicit_shop(client):
    r = client.post("/api/decide", json={"customer": "C003", "amount": "10,000", "shop": "shop_a"})
    assert r.status_code == 200 and r.get_json()["answer"] in ("YES", "NO")


def test_receipt_json_matches_the_decision(client):
    out = decide_tunde(client)
    r = client.get("/api/receipt/" + out["decision_id"])
    assert r.status_code == 200
    rec = r.get_json()
    assert rec["id"] == out["decision_id"] and rec["answer"] == "NO"
    assert rec["customer"]["id"] == "C001" and rec["amount"] == 45000
    assert rec["fingerprint"] == out["fingerprint"]
    assert {x["id"] for x in rec["promises"]} >= {"PR001"}
    assert sorted(rec["evidence_ids"]) == sorted(out["evidence_ids"])
    assert rec["check"]["ok"] is True
    assert {r_["id"] for r_ in rec["rules"]} == {"R_LIMIT", "R_BROKEN_PROMISE"}
    assert "synthetic" in rec["data_label"]


def test_verify_passes_then_fails_when_a_record_is_changed(client, graph):
    out = decide_tunde(client)
    r = client.get("/api/verify/" + out["decision_id"])
    assert r.status_code == 200
    v = r.get_json()
    assert v["id"] == out["decision_id"] and v["verified"] is True and v["detail"]
    graph.query("MATCH (:Customer {id:'C001'})-[:MADE]->(t:Trade) WITH t LIMIT 1 SET t.amount = t.amount + 1")
    bad = client.get("/api/verify/" + out["decision_id"]).get_json()
    assert bad["verified"] is False and "changed" in bad["detail"]


def test_whatif_flips_the_answer_and_deletes_its_copy(client):
    out = decide_tunde(client)
    before = whatif_copies()
    r = client.get("/api/whatif/%s?remove=PR001" % out["decision_id"])
    assert r.status_code == 200
    res = r.get_json()
    assert res["original_answer"] == "NO" and res["new_answer"] == "YES" and res["changed"] is True
    assert res["removed"] == ["PR001"] and res["real_graph_untouched"] is True
    assert whatif_copies() == before


def test_customers_route(client):
    r = client.get("/api/customers")
    assert r.status_code == 200
    body = r.get_json()
    assert body["shop"] == "shop_a" and len(body["customers"]) == 25
    assert {"id", "name", "credit_limit"} <= set(body["customers"][0])


# ---------------------------------------------------------------- JSON routes: bad input

@pytest.mark.parametrize("body", [
    {}, {"customer": "C001"}, {"amount": 5}, {"customer": "C001", "amount": 0},
    {"customer": "C001", "amount": -5}, {"customer": "C001", "amount": "abc"},
    {"customer": "C001", "amount": 1.5}, {"customer": "C001", "amount": True},
    {"customer": "C001", "amount": 10 ** 15}, {"customer": "bad id!", "amount": 5},
    {"customer": 7, "amount": 5}, {"customer": "C001", "amount": 5, "shop": "nope"},
])
def test_decide_rejects_bad_input_with_400(client, graph, body):
    r = client.post("/api/decide", json=body)
    assert r.status_code == 400 and r.get_json()["error"]
    assert graph.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0] == 0


def test_decide_rejects_non_json_and_unknown_customer(client):
    assert client.post("/api/decide", data="hello").status_code == 400
    assert client.post("/api/decide", json=[1, 2]).status_code == 400
    r = client.post("/api/decide", json={"customer": "NOPE99", "amount": 100})
    assert r.status_code == 404 and "list_customers" in r.get_json()["error"]


def test_bad_input_does_not_use_up_a_write(client, monkeypatch):
    monkeypatch.setattr(webapp, "PER_IP_LIMIT", 2)
    for _ in range(5):
        assert client.post("/api/decide", json={"customer": "C001"}).status_code == 400
    assert client.post("/api/decide", json={"customer": "C001", "amount": 100}).status_code == 200


def test_unknown_and_malformed_ids(client):
    for path in ("/api/receipt/D9999", "/api/verify/D9999", "/api/whatif/D9999?remove=PR001"):
        r = client.get(path)
        assert r.status_code == 404 and r.get_json()["error"], path
    for path in ("/api/receipt/xyz", "/api/verify/..%2f", "/api/whatif/xyz?remove=PR001"):
        assert client.get(path).status_code in (400, 404), path


def test_whatif_bad_remove(client):
    out = decide_tunde(client)
    did = out["decision_id"]
    assert client.get("/api/whatif/" + did).status_code == 400
    assert client.get("/api/whatif/%s?remove=bad%%20id" % did).status_code == 400
    r = client.get("/api/whatif/%s?remove=NOTUSED" % did)
    assert r.status_code == 400 and "did not use" in r.get_json()["error"]
    too_many = ",".join("PR%03d" % i for i in range(11))
    assert client.get("/api/whatif/%s?remove=%s" % (did, too_many)).status_code == 400


def test_errors_are_json_and_never_show_database_text(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("redis connection refused at secret-host:6379")
    monkeypatch.setattr(webapp, "get_graph", boom)
    r = client.get("/api/customers")
    assert r.status_code == 503
    text = r.get_data(as_text=True)
    assert "secret-host" not in text and "redis" not in text.lower()
    assert r.get_json()["error"]
    assert client.get("/api/nothing-here").get_json()["error"]


# ---------------------------------------------------------------- limits

def test_writes_return_429_and_reads_are_lighter(client, monkeypatch):
    monkeypatch.setattr(webapp, "PER_IP_LIMIT", 2)
    out = decide_tunde(client)
    assert client.post("/api/decide", json={"customer": "C001", "amount": 5}).status_code == 200
    r = client.post("/api/decide", json={"customer": "C001", "amount": 5})
    assert r.status_code == 429 and "Too many" in r.get_json()["error"]
    assert client.get("/api/whatif/%s?remove=PR001" % out["decision_id"]).status_code == 429
    assert client.get("/api/receipt/" + out["decision_id"]).status_code == 200   # reads still fine
    other = client.post("/api/decide", json={"customer": "C001", "amount": 5},
                        headers={"X-Forwarded-For": "8.8.4.4"})
    assert other.status_code == 200


def test_site_wide_write_limit(client, monkeypatch):
    monkeypatch.setattr(webapp, "SITE_LIMIT", 1)
    codes = [client.post("/api/decide", json={"customer": "C003", "amount": 100},
                         headers={"X-Forwarded-For": "2.2.2.%d" % i}).status_code for i in range(2)]
    assert codes == [200, 429]


def test_read_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr(webapp, "READ_LIMIT", 2)
    assert [client.get("/api/customers").status_code for _ in range(3)] == [200, 200, 429]


def test_decision_cap_is_kept(client, graph, monkeypatch):
    monkeypatch.setattr(agent_api._app(), "prune_decisions",
                        lambda g, keep=2: __import__("rules").prune_decisions(g, keep=2))
    for _ in range(4):
        decide_tunde(client)
    assert graph.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0] == 2


# ---------------------------------------------------------------- MCP

def test_mcp_get_describes_the_server(client):
    r = client.get("/mcp")
    assert r.status_code == 200
    body = r.get_json()
    assert body["name"] == "Bashi" and len(body["tools"]) == 5


def test_mcp_initialize(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "t", "version": "1"}})
    res = r.get_json()
    assert res["jsonrpc"] == "2.0" and res["id"] == 1
    assert res["result"]["protocolVersion"] == "2025-06-18"
    assert res["result"]["serverInfo"]["name"] == "Bashi"
    assert "tools" in res["result"]["capabilities"]


def test_mcp_notification_ping_and_unknown_method(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and r.get_data() == b""
    assert rpc(client, "ping").get_json()["result"] == {}
    assert rpc(client, "nope/nothing").get_json()["error"]["code"] == -32601
    assert client.post("/mcp", data="not json").status_code == 400
    assert client.post("/mcp", json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}]).status_code == 400
    assert client.post("/mcp", json={"id": 1}).get_json()["error"]["code"] == -32600


def test_mcp_tools_list_has_all_five(client):
    tools = rpc(client, "tools/list").get_json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["decide_credit", "get_receipt", "verify_decision",
                                          "what_if_remove_evidence", "list_customers"]
    for t in tools:
        assert t["description"] and t["inputSchema"]["type"] == "object"


def test_mcp_every_tool_call(client):
    made = call(client, "decide_credit", {"customer": "C001", "amount": 45000})
    assert made["isError"] is False
    out = made["structuredContent"]
    assert out["answer"] == "NO" and json.loads(made["content"][0]["text"])["decision_id"] == out["decision_id"]
    did = out["decision_id"]
    rec = call(client, "get_receipt", {"decision_id": did})["structuredContent"]
    assert rec["id"] == did and rec["answer"] == "NO"
    ver = call(client, "verify_decision", {"decision_id": did})["structuredContent"]
    assert ver["verified"] is True
    before = whatif_copies()
    wi = call(client, "what_if_remove_evidence", {"decision_id": did, "remove": ["PR001"]})["structuredContent"]
    assert wi["new_answer"] == "YES" and wi["changed"] is True
    assert whatif_copies() == before
    custs = call(client, "list_customers", {})["structuredContent"]
    assert len(custs["customers"]) == 25


def test_mcp_tool_errors_use_is_error(client):
    for name, args in [("decide_credit", {"customer": "C001", "amount": -1}),
                       ("decide_credit", {"customer": "NOPE99", "amount": 100}),
                       ("get_receipt", {"decision_id": "D9999"}),
                       ("verify_decision", {"decision_id": "D9999"}),
                       ("what_if_remove_evidence", {"decision_id": "D9999", "remove": ["PR001"]}),
                       ("list_customers", {"shop": "nope"})]:
        res = call(client, name, args)
        assert res["isError"] is True and res["content"][0]["text"], (name, args)
    bad = rpc(client, "tools/call", {"name": "no_such_tool", "arguments": {}}).get_json()
    assert bad["error"]["code"] == -32602
    assert rpc(client, "tools/call", {}).get_json()["error"]["code"] == -32602


def test_mcp_write_tools_are_limited(client, monkeypatch):
    monkeypatch.setattr(webapp, "PER_IP_LIMIT", 1)
    assert call(client, "decide_credit", {"customer": "C001", "amount": 5})["isError"] is False
    limited = call(client, "decide_credit", {"customer": "C001", "amount": 5})
    assert limited["isError"] is True and "Too many" in limited["content"][0]["text"]
    assert call(client, "list_customers", {})["isError"] is False


def test_routes_and_mcp_agree(client):
    a = client.post("/api/decide", json={"customer": "C001", "amount": 45000}).get_json()
    b = call(client, "decide_credit", {"customer": "C001", "amount": 45000})["structuredContent"]
    for key in ("answer", "reasons", "fingerprint", "evidence_ids", "open_debt", "limit", "shop"):
        assert a[key] == b[key], key
    ra = client.get("/api/receipt/" + a["decision_id"]).get_json()
    rb = call(client, "get_receipt", {"decision_id": a["decision_id"]})["structuredContent"]
    assert ra == rb
    va = client.get("/api/verify/" + a["decision_id"]).get_json()
    vb = call(client, "verify_decision", {"decision_id": a["decision_id"]})["structuredContent"]
    assert va == vb
    wa = client.get("/api/whatif/%s?remove=PR001" % a["decision_id"]).get_json()
    wb = call(client, "what_if_remove_evidence",
              {"decision_id": a["decision_id"], "remove": ["PR001"]})["structuredContent"]
    assert wa == wb
    assert client.get("/api/customers").get_json() == call(client, "list_customers", {})["structuredContent"]


# ---------------------------------------------------------------- stdio and docs

def test_stdio_server_speaks_the_same_tools(client):
    lines = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "decide_credit", "arguments": {"customer": "C001", "amount": 45000}}},
    ]) + "\nnot json\n"
    out = io.StringIO()
    mcp_stdio.serve(io.StringIO(lines), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, 2, 3, None]      # the notification got no reply
    assert len(replies[1]["result"]["tools"]) == 5
    assert replies[2]["result"]["structuredContent"]["answer"] == "NO"
    assert replies[3]["error"]["code"] == -32700


def test_docs_are_served(client):
    r = client.get("/llms.txt")
    assert r.status_code == 200 and "/api/decide" in r.get_data(as_text=True)
    assert r.mimetype == "text/plain"
    r = client.get("/AGENTS.md")
    assert r.status_code == 200 and "/mcp" in r.get_data(as_text=True)


def test_new_files_have_no_em_dashes_or_forbidden_words():
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("agent_api.py", "mcp_stdio.py", "AGENTS.md", "llms.txt"):
        text = open(os.path.join(root, name), encoding="utf-8").read()
        assert "—" not in text, name
        # the public site address (it ends in onrender.com) is allowed, as on README line 1
        assert "render" not in text.lower().replace("onrender.com", "") or name.endswith(".py"), name
