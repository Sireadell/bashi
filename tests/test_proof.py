"""The /proof page: check an untouched copy, then a copy with one digit changed.

Works on a private copy of the demo shop (the `graph` fixture), deleted afterwards.
"""
import time

import pytest

import app as webapp
import whatif
from db import get_db
from rules import decide


@pytest.fixture()
def client(graph, monkeypatch):
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": graph)
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": graph)
    monkeypatch.setitem(webapp._own_seen, "at", time.time())
    monkeypatch.setitem(webapp._own_seen, "ok", False)
    webapp.reset_limits()
    yield webapp.app.test_client()
    webapp.reset_limits()


@pytest.fixture()
def did(graph):
    return decide("C001", 45000, graph=graph, save=True)["decision_id"]


def copies():
    return {n for n in get_db().list_graphs() if n.startswith("shop_a_whatif_")}


def evidence_amounts(graph):
    return graph.query("MATCH (n) WHERE n:Trade OR n:Payment RETURN n.id, n.amount ORDER BY n.id").result_set


def test_page_loads_and_lists_receipt(client, did):
    r = client.get("/proof")
    assert r.status_code == 200
    assert did in r.get_data(as_text=True)


def test_untouched_copy_passes(client, did):
    r = client.post("/proof/run", json={"decision": did, "mode": "untouched"})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["passed"] is True and j["problems"] == [] and j["changed"] is None
    assert j["copy_deleted"] is True


def test_tampered_copy_fails_and_live_graph_unchanged(client, graph, did):
    before = evidence_amounts(graph)
    names_before = copies()
    r = client.post("/proof/run", json={"decision": did, "mode": "tamper"})
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["passed"] is False and j["problems"]
    c = j["changed"]
    assert c["before"] != c["after"] and abs(c["before"] - c["after"]) < 10
    assert j["copy_deleted"] is True
    assert evidence_amounts(graph) == before          # live graph untouched
    assert copies() == names_before                   # throwaway copy gone
    again = client.post("/proof/run", json={"decision": did, "mode": "untouched"}).get_json()
    assert again["passed"] is True                    # still verifies after the tamper run


def test_bad_input(client):
    assert client.post("/proof/run", json={}).status_code == 400
    assert client.post("/proof/run", json={"decision": "D9999999"}).status_code == 404


def test_write_limit(client, did, monkeypatch):
    monkeypatch.setattr(webapp, "PER_IP_LIMIT", 2)
    codes = [client.post("/proof/run", json={"decision": "D9999999"}).status_code for _ in range(3)]
    assert codes == [404, 404, 429]
