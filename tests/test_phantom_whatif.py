"""The phantom what-if: link unlinked payments on a throwaway copy and ask again.

Uses a private copy of the demo shop (the `graph` fixture). In it, C002's
payment P0004 (N12,000) was never linked to sale T0004 (N12,000): a phantom.
"""
import time

import pytest

import app as webapp
import whatif
from db import get_db
from rules import decide, evaluate, read_state


@pytest.fixture()
def client(graph, monkeypatch):
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": graph)
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": graph)
    monkeypatch.setitem(webapp._own_seen, "at", time.time())
    monkeypatch.setitem(webapp._own_seen, "ok", False)
    webapp.reset_limits()
    yield webapp.app.test_client()
    webapp.reset_limits()


def flip_request(graph, cid):
    """A request that is too big while the phantom counts as owed and fine once it is linked."""
    st = read_state(graph, cid)
    debt = evaluate(st, 1)["open_debt"]
    return st["customer"]["limit"] - (debt - 12000)


def copies():
    return {n for n in get_db().list_graphs() if n.startswith("shop_a_whatif_")}


def snapshot(graph):
    return (graph.query("MATCH ()-[r:SETTLES]->() RETURN count(r)").result_set,
            graph.query("MATCH (n) RETURN count(n)").result_set)


def test_before_and_after_differ_on_a_phantom(client, graph):
    req = flip_request(graph, "C002")
    did = decide("C002", req, graph=graph, save=True)["decision_id"]
    page = client.get("/receipt/" + did).get_data(as_text=True)
    assert "What if these payments are linked to their sales?" in page
    r = client.post("/phantom-whatif/" + did)
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["links"] == [{"trade": "T0004", "payment": "P0004", "amount": 12000}]
    assert j["before"]["answer"] == "NO" and j["after"]["answer"] == "YES"
    assert j["before"]["owed"] - j["after"]["owed"] == 12000
    assert j["changed"] is True and j["copy_deleted"] is True
    print("\nBEFORE", j["before"], "AFTER", j["after"])


def test_live_graph_unchanged_and_copy_deleted(client, graph):
    did = decide("C002", flip_request(graph, "C002"), graph=graph, save=True)["decision_id"]
    before, names = snapshot(graph), copies()
    assert client.post("/phantom-whatif/" + did).status_code == 200
    assert snapshot(graph) == before
    assert copies() == names


def test_no_button_without_phantoms(client, graph):
    did = decide("C001", 1000, graph=graph, save=True)["decision_id"]
    page = client.get("/receipt/" + did).get_data(as_text=True)
    assert "What if these payments are linked" not in page
    r = client.post("/phantom-whatif/" + did)
    assert r.status_code == 400


def test_unknown_receipt_and_rate_limit(client, graph):
    assert client.post("/phantom-whatif/D-NOPE").status_code == 404
    did = decide("C002", flip_request(graph, "C002"), graph=graph, save=True)["decision_id"]
    codes = [client.post("/phantom-whatif/" + did).status_code for _ in range(25)]
    assert 429 in codes
