"""The receipt page draws the decision's evidence as a small SVG graph.
Every test runs on a throwaway copy of the practice shop (the `graph` fixture)."""
import re

import pytest

import app as webapp
import whatif
from rules import decide

COOKIE = {"Cookie": f"{webapp.SHOP_COOKIE}=demo"}


@pytest.fixture()
def client(graph, monkeypatch):
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": graph)
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": graph)
    webapp.reset_limits()
    yield webapp.app.test_client()
    webapp.reset_limits()


def receipt_html(client, decision_id):
    r = client.get("/receipt/" + decision_id, headers=COOKIE)
    assert r.status_code == 200
    return r.get_data(as_text=True)


def svg_of(html):
    m = re.search(r"<svg class=\"eg-svg\".*?</svg>", html, re.S)
    assert m, "no evidence graph on the receipt"
    return m.group(0)


def test_graph_names_the_decision_customer_and_every_record(graph, client):
    res = decide("C001", 45000, graph=graph)
    html = receipt_html(client, res["decision_id"])
    svg = svg_of(html)
    assert res["decision_id"] in svg and "NO" in svg and "C001" in svg
    for e in res["evidence"]:
        assert e["id"] in svg, e                      # every record the answer used is drawn
    assert "PR001" in svg and "BROKEN" in svg          # the broken promise is marked with a word
    assert "settles" in svg                            # at least one payment-to-sale line


def test_nodes_open_the_record_pages(graph, client):
    res = decide("C001", 45000, graph=graph)
    svg = svg_of(receipt_html(client, res["decision_id"]))
    d = res["decision_id"]
    assert f'/record/Promise/PR001?d={d}' in svg
    links = re.findall(r'href="(/record/[A-Za-z]+/[^"]+)"', svg)
    assert links and all(f"d={d}" in x for x in links)
    for x in links:
        assert client.get(x, headers=COOKIE).status_code == 200


def test_graph_sits_beside_the_existing_receipt_pieces(graph, client):
    res = decide("C001", 45000, graph=graph)
    html = receipt_html(client, res["decision_id"])
    assert 'id="whatif-panel"' in html and "data-remove=" in html
    assert "Credit sales and what is still owed" in html and "evidence_graph.css" in html
    assert html.index('id="whatif-panel"') < html.index('id="evidence-graph"')


def test_unlinked_payment_is_flagged_as_possible_phantom_debt(graph, client):
    graph.query("CREATE (:Customer {id:'CZ', name:'Zainab', credit_limit:100000, source:'invented'})")
    graph.query("MATCH (c:Customer {id:'CZ'}) CREATE (c)-[:MADE]->(:Trade {id:'TZ1', amount:12345, date:'2026-01-01'})")
    graph.query("MATCH (c:Customer {id:'CZ'}) CREATE (c)-[:PAID]->(:Payment {id:'PZ1', amount:12345, date:'2026-02-01'})")
    res = decide("CZ", 1000, graph=graph)
    html = receipt_html(client, res["decision_id"])
    assert "Possible phantom debt" in html              # the existing card is still there
    svg = svg_of(html)
    assert "PZ1" in svg and "TZ1" in svg and "unlinked" in svg
    assert 'class="eg-edge orphan"' in svg
    assert "possible phantom debt" in html.split('id="evidence-graph"')[1].lower()


def test_clean_customer_still_draws_a_graph(graph, client):
    res = decide("C003", 10000, graph=graph)
    svg = svg_of(receipt_html(client, res["decision_id"]))
    assert res["decision_id"] in svg and "C003" in svg and "BROKEN" not in svg


def test_no_dots_and_no_outside_scripts_or_libraries(graph, client):
    res = decide("C001", 45000, graph=graph)
    svg = svg_of(receipt_html(client, res["decision_id"]))
    assert "<circle" not in svg and "<script" not in svg and "http" not in svg
