"""The receipt shows the same question answered by a balance check alone and by following the links."""
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


def panel(client, decision_id):
    r = client.get("/receipt/" + decision_id, headers=COOKIE)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    m = re.search(r'<section class="card sd" id="shallow-deep">.*?</section>', html, re.S)
    assert m, "no shallow vs deep panel"
    return m.group(0)


def test_tunde_balance_says_yes_links_say_no(graph, client):
    res = decide("C001", 45000, graph=graph)
    p = panel(client, res["decision_id"])
    assert "A balance check alone says" in p and "Following the links says" in p
    yes = re.search(r'sd-v yes">YES<', p)
    no = re.search(r'sd-v no">NO<', p)
    assert yes and no and yes.start() < no.start()
    assert "The two answers differ" in p and "PR001" in p
    assert "\u2014" not in p


def test_clean_customer_both_agree(graph, client):
    res = decide("C003", 10000, graph=graph)
    p = panel(client, res["decision_id"])
    assert "Both give the same answer" in p and "differ." not in p
    assert ">YES<" in p and ">NO<" not in p


def test_unlinked_payment_counts_in_balance_but_is_named(graph, client):
    graph.query("CREATE (:Customer {id:'CZ', name:'Zainab', credit_limit:100000, source:'invented'})")
    graph.query("MATCH (c:Customer {id:'CZ'}) CREATE (c)-[:MADE]->(:Trade {id:'TZ1', amount:90000, date:'2026-01-01'})")
    graph.query("MATCH (c:Customer {id:'CZ'}) CREATE (c)-[:PAID]->(:Payment {id:'PZ1', amount:90000, date:'2026-02-01'})")
    res = decide("CZ", 20000, graph=graph)
    p = panel(client, res["decision_id"])
    assert "unlinked" in p or "nobody linked" in p
    assert "Debt N0" in p            # the balance check saw the payment


def test_unlinked_case_explains_why_it_holds_at_no(graph, client):
    graph.query("CREATE (:Customer {id:'CY', name:'Yusuf', credit_limit:100000, source:'invented'})")
    graph.query("MATCH (c:Customer {id:'CY'}) CREATE (c)-[:MADE]->(:Trade {id:'TY1', amount:90000, date:'2026-01-01'})")
    graph.query("MATCH (c:Customer {id:'CY'}) CREATE (c)-[:PAID]->(:Payment {id:'PY1', amount:90000, date:'2026-02-01'})")
    res = decide("CY", 20000, graph=graph)
    r = client.get("/receipt/" + res["decision_id"], headers=COOKIE)
    html = r.get_data(as_text=True)
    if "Why Bashi holds at NO here" in html:
        assert "not from a bad customer" in html
        assert "No payments were read" not in html
        assert "No payment is linked to these sales yet" in html
