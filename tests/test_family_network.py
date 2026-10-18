"""Family network: a deep walk over people links that changes the credit answer.

CUST-17 (invented) owes N0 on its own. Following owner, buyer and family links reaches five
more accounts, up to 7 links away, that owe N100,000 between them, so a N40,000 request is NO.
Removing the one family link (FAM-1) on a throwaway copy turns it back to YES.
"""
import copy
import uuid

import pytest

import app as webapp
import own_shop
import whatif
from db import get_db
from own_audit_seed import SEED
from rules import RULES, decide, read_network, read_state
from verify import verify_decision

COOKIE = {"Cookie": f"{webapp.SHOP_COOKIE}=demo"}
WHO, ASK = "CUST-17", 40000
TEMP = []


def load(data):
    db = get_db()
    name = "shop_own_test_" + uuid.uuid4().hex[:8]
    own_shop.load_seed(db, data, graph_name=name)
    g = db.select_graph(name)
    TEMP.append(g)
    return g, name


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    while TEMP:
        try:
            TEMP.pop().delete()
        except Exception:
            pass


@pytest.fixture(scope="module")
def shared():
    """One loaded copy for the read-only tests in this file."""
    db = get_db()
    name = "shop_own_test_" + uuid.uuid4().hex[:8]
    own_shop.load_seed(db, SEED, graph_name=name)
    g = db.select_graph(name)
    yield g, name
    try:
        g.delete()
    except Exception:
        pass


def _row(g, did):
    return g.query("MATCH (d:Decision {id:$d}) RETURN d.id, d.customer_id, d.request, d.verdict, "
                   "d.fingerprint, d.snapshot", {"d": did}).result_set[0]


def test_walk_reaches_every_account_once_with_its_depth(shared):
    g, _ = shared
    net, family = read_network(g, WHO)
    assert {a: (v["debt"], v["hops"]) for a, v in net.items()} == {
        "CUST-18": (20000, 2), "CUST-19": (10000, 4), "CUST-20": (15000, 5),
        "CUST-21": (25000, 5), "CUST-22": (30000, 7)}
    assert WHO not in net and len(net) == len(set(net))
    assert list(family) == ["FAM-1"]
    steps = [s["text"] for s in net["CUST-22"]["steps"]]
    assert steps[0] == "CUST-17 is owned by Buyer 7" and "Buyer 8 is family of Buyer 9" in steps
    assert steps[-1] == "Buyer 10 owns CUST-22"


def test_family_rule_says_no_where_the_account_alone_owes_nothing(shared):
    g, _ = shared
    r = decide(WHO, ASK, graph=g, save=False)
    assert r["open_debt"] == 0 and r["verdict"] == "NO"
    assert r["network_debt"] == 100000
    assert r["reason"].startswith("family network rule: this account and 5 linked accounts owe N100,000")
    assert "R_FAMILY" in RULES


def test_account_without_people_links_is_unchanged(shared):
    g, _ = shared
    for cid in ("CUST-03", "CUST-13"):
        state = read_state(g, cid)
        assert "network" not in state
        r = decide(cid, 10000, graph=g, save=False)
        assert "family network" not in r["reason"] and r["network_debt"] is None


def test_sealed_and_practice_shop_have_no_people_links(graph):
    assert graph.query("MATCH (b:Buyer) RETURN count(b)").result_set[0][0] == 0
    assert graph.query("MATCH (f:Family) RETURN count(f)").result_set[0][0] == 0


def test_what_if_on_the_family_link_flips_to_yes(monkeypatch):
    g, name = load(SEED)
    monkeypatch.setattr(whatif, "get_graph", lambda n="shop_a": g)
    r = decide(WHO, ASK, graph=g)
    assert "FAM-1" in [e["id"] for e in r["evidence"]]
    w = whatif.whatif(r["decision_id"], ["FAM-1"], graph_name=name)
    assert (w["original_verdict"], w["new_verdict"], w["changed"]) == ("NO", "YES", True)
    assert "N30,000" in w["new_reason"]
    assert g.query("MATCH (f:Family {id:'FAM-1'}) RETURN count(f)").result_set[0][0] == 1


def test_fingerprint_verifies_and_catches_a_change_far_away():
    g, _ = load(SEED)
    r = decide(WHO, ASK, graph=g)
    ok, problems = verify_decision(g, _row(g, r["decision_id"]))
    assert ok, problems
    g.query("MATCH (:Customer {id:'CUST-22'})-[:MADE]->(t:Trade) SET t.amount = t.amount + 1")
    ok, problems = verify_decision(g, _row(g, r["decision_id"]))
    assert not ok and any("CUST-22" in p for p in problems)


def test_removing_the_family_link_in_the_data_breaks_the_old_receipt():
    g, _ = load(SEED)
    r = decide(WHO, ASK, graph=g)
    g.query("MATCH (f:Family {id:'FAM-1'}) DETACH DELETE f")
    ok, problems = verify_decision(g, _row(g, r["decision_id"]))
    assert not ok and any("FAM-1" in p for p in problems)


def test_family_link_must_join_known_buyers():
    bad = copy.deepcopy(SEED)
    bad["family"][0]["b"] = "BUY-99"
    with pytest.raises(ValueError):
        own_shop.prepare(bad)


def test_receipt_shows_the_family_network_block(monkeypatch):
    g, _ = load(SEED)
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": g)
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": g)
    webapp.reset_limits()
    r = decide(WHO, ASK, graph=g)
    html = webapp.app.test_client().get("/receipt/" + r["decision_id"], headers=COOKIE).get_data(as_text=True)
    box = html.split('id="family-network"')[1].split("</section>")[0]
    assert "5 linked accounts, 7 links deep" in box and "N100,000" in box
    assert "The family network rule says NO." in box and 'data-remove="FAM-1"' in box
    assert "invented" in box and "—" not in box and "<svg" in box
    assert "A balance check alone says" in html
    webapp.reset_limits()


def test_agent_door_names_the_rule_and_accepts_the_family_link(monkeypatch):
    import time
    import agent_api
    g, _ = load(SEED)
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": g)
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": g)
    monkeypatch.setitem(webapp._own_seen, "at", time.time())
    monkeypatch.setitem(webapp._own_seen, "ok", False)
    webapp.reset_limits()
    out = agent_api.decide_credit(WHO, ASK, shop="shop_a")
    assert out["answer"] == "NO" and "family network rule" in out["reason"]
    assert out["family_network_debt"] == 100000 and "FAM-1" in out["evidence_ids"]
    rec = agent_api.get_receipt(out["decision_id"])
    assert rec["family_network"]["links_deep"] == 7 and "FAM-1" in rec["evidence_ids"]
    w = agent_api.what_if_remove_evidence(out["decision_id"], "FAM-1")
    assert (w["original_answer"], w["new_answer"]) == ("NO", "YES")
    webapp.reset_limits()
