"""One shop, many buyers: who collected and who paid, shown on the receipt.

The decision stays per shop. A per-person balance would say NO (one buyer owing, the
other overpaid); the shop as a whole says YES. Graphs with no buyers are unchanged.
"""
import copy
import uuid

import pytest

import app as webapp
import own_shop
import whatif
from buyers import buyer_view, read_buyers
from db import get_db
from own_audit_seed import SEED
from rules import decide, read_state, snapshot_of
from verify import verify_decision

COOKIE = {"Cookie": f"{webapp.SHOP_COOKIE}=demo"}
SHOP, ASK = "CUST-13", 45000
TEMP = []


def load(data):
    db = get_db()
    name = "shop_own_test_" + uuid.uuid4().hex[:8]
    own_shop.load_seed(db, data, graph_name=name)
    g = db.select_graph(name)
    TEMP.append(g)
    return g


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    while TEMP:
        try:
            TEMP.pop().delete()
        except Exception:
            pass


@pytest.fixture()
def own():
    return load(SEED)


@pytest.fixture()
def client(own, monkeypatch):
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": own)
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": own)
    webapp.reset_limits()
    yield webapp.app.test_client()
    webapp.reset_limits()


def test_seed_has_two_invented_buyers_with_generic_labels():
    assert [b["label"] for b in SEED["buyers"]] == ["Buyer %d" % i for i in range(1, 7)]
    assert {c["source"] for c in SEED["customers"] if c["id"] == SHOP} == {"invented"}
    assert own_shop.find_leaks(SEED) == []


def test_graph_links_buyers_to_the_shop_sales_and_payments(own):
    q = lambda c: own.query(c).result_set[0][0]
    assert q("MATCH (:Buyer)-[:BUYS_FOR]->(:Customer {id:'CUST-13'}) RETURN count(*)") == 2
    assert q("MATCH (:Buyer {id:'BUY-1'})-[:COLLECTED]->(:Trade) RETURN count(*)") == 3
    assert q("MATCH (:Buyer)-[:PAID]->(:Payment) RETURN count(*)") == 3


def test_shop_says_yes_where_one_person_check_says_no(own):
    r = decide(SHOP, ASK, graph=own, save=False)
    assert r["verdict"] == "YES" and r["open_debt"] == 0
    state = read_state(own, SHOP)
    v = buyer_view(read_buyers(own, SHOP), state, ASK, r["verdict"])
    by = {p["name"]: p for p in v["people"]}
    assert by["Buyer 1"]["balance"] == 70000 and by["Buyer 2"]["balance"] == -70000
    assert v["person_answer"] == "NO" and v["wrong"] is True
    assert v["different"] == 2


def test_payment_by_another_buyer_settles_the_sale(own):
    state = read_state(own, SHOP)
    assert sum(state["settles"].values()) == sum(t["amount"] for t in state["trades"].values())
    assert decide(SHOP, ASK, graph=own, save=False)["possible_phantoms"] == []


def test_buyer_links_do_not_change_fingerprint_or_answer(own):
    plain = copy.deepcopy(SEED)
    plain["buyers"] = []
    for row in plain["sales"] + plain["payments"]:
        row.pop("buyer", None)
    g2 = load(plain)
    a = decide(SHOP, ASK, graph=own, save=False)
    b = decide(SHOP, ASK, graph=g2, save=False)
    assert a["fingerprint"] == b["fingerprint"] and a["verdict"] == b["verdict"]
    assert not any("Buyer" in k for k in snapshot_of(read_state(own, SHOP)))


def test_graph_without_buyers_has_no_buyer_view(own):
    assert read_buyers(own, "CUST-03") is None
    assert buyer_view(None, {}, 1, "YES") is None


def test_receipt_shows_who_collected_who_paid_and_the_line(own, client):
    res = decide(SHOP, ASK, graph=own)
    html = client.get("/receipt/" + res["decision_id"], headers=COOKIE).get_data(as_text=True)
    assert 'id="shop-buyers"' in html and "Collected by" in html and "Paid by" in html
    assert "2 payments were made by a different person from the one who collected the goods; " \
           "all are linked to the same shop." in html
    assert "Checking Buyer 1 alone says" in html and "A per-person check gives the wrong answer" in html
    graph_part = html.split('id="evidence-graph"')[1].split("</svg>")[0]
    assert "Buyer 1" in graph_part and "Buyer 2" in graph_part
    assert "\u2014" not in html.split('id="shop-buyers"')[1].split("</section>")[0]
    ok, problems = verify_decision(own, (res["decision_id"], SHOP, ASK, res["verdict"],
                                         res["fingerprint"], own.query(
        "MATCH (d:Decision {id:$i}) RETURN d.snapshot", {"i": res["decision_id"]}).result_set[0][0]))
    assert ok, problems


def test_receipt_for_a_shop_without_buyers_has_no_buyer_section(own, client):
    res = decide("CUST-03", 1000, graph=own)
    html = client.get("/receipt/" + res["decision_id"], headers=COOKIE).get_data(as_text=True)
    assert "shop-buyers" not in html and "Collected by" not in html


def test_buyer_must_act_for_the_shop_that_owns_the_record():
    bad = copy.deepcopy(SEED)
    bad["sales"][0]["buyer"] = "BUY-1"
    with pytest.raises(ValueError):
        own_shop.prepare(bad)


def test_buyer_paid_links_do_not_hide_another_shops_phantom_debt(own):
    """Buyer-[:PAID]->Payment must not look like a payment tied to a customer."""
    assert len(decide("CUST-02", 1000, graph=own, save=False)["possible_phantoms"]) == 1


# ---------------------------------------------------------------- collectors only, personal accounts

def test_collector_shop_has_no_payer_claims(own, client):
    res = decide("CUST-14", 10000, graph=own)
    html = client.get("/receipt/" + res["decision_id"], headers=COOKIE).get_data(as_text=True)
    box = html.split('id="shop-buyers"')[1].split("</section>")[0]
    assert "Sales collected" in box and "Buyer 3" in box
    assert "different person" not in box and "alone says" not in box and '<th class="n">Paid' not in box


def test_personal_account_shows_the_other_account_and_its_debt(own, client):
    from buyers import read_exposure
    assert read_exposure(own, "CUST-15") == [{"who": "Buyer 3", "account": "CUST-14", "sales": 5, "debt": 43360}]
    res = decide("CUST-15", 10000, graph=own)
    html = client.get("/receipt/" + res["decision_id"], headers=COOKIE).get_data(as_text=True)
    assert "Also collects goods for another account that owes N43,360." in html
    assert "invented" in html.split('id="other-accounts"')[1].split("</section>")[0]


def test_exposure_never_changes_the_answer(own):
    plain = copy.deepcopy(SEED)
    for b in plain["buyers"]:
        b.pop("owns", None)
    g2 = load(plain)
    for amount in (10000, 90000):
        a, b = decide("CUST-15", amount, graph=own, save=False), decide("CUST-15", amount, graph=g2, save=False)
        assert (a["verdict"], a["fingerprint"]) == (b["verdict"], b["fingerprint"])


def test_account_without_owner_has_no_exposure(own):
    from buyers import read_exposure
    assert read_exposure(own, "CUST-03") == [] and read_exposure(own, "CUST-14") == []
