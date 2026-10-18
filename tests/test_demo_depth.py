"""The demo button: the case it opens on, how few trips it makes to the database, and that
what it saves is unchanged. Uses a private copy of the invented seed, never the live shop."""
import json
import uuid

import pytest

import app as webapp
import own_shop
import whatif
from db import OWN_GRAPH, get_db
from own_audit_seed import SEED
from rules import decide

I = "invented"


@pytest.fixture()
def seeded():
    db = get_db()
    name = "shop_own_test_" + uuid.uuid4().hex[:8]
    own_shop.load_seed(db, SEED, graph_name=name)
    g = db.select_graph(name)
    yield g
    try:
        g.delete()
    except Exception:
        pass


def counting(g, monkeypatch):
    calls = []
    real = type(g).query

    def q(self, *a, **k):
        calls.append(a[0])
        return real(self, *a, **k)
    monkeypatch.setattr(type(g), "query", q)
    return calls


def test_demo_prefers_a_no_that_rests_on_an_unlinked_payment(seeded):
    case = own_shop.find_demo_case(seeded, only_source=I)
    assert case["kind"] == "sale" and case["payment"].startswith("PY-")
    assert case["remove"] == "TI-005" and case["payment"] == "PY-005"


def test_the_hint_still_flips_the_answer(seeded, monkeypatch):
    case = own_shop.find_demo_case(seeded, only_source=I)
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": seeded)
    res = decide(case["customer"], case["amount"], graph=seeded)
    assert res["verdict"] == "NO"
    assert case["remove"] in [e["id"] for e in res["evidence"]]
    assert [p["payment"] for p in res["possible_phantoms"]] == [case["payment"]]
    flip = whatif.whatif(res["decision_id"], [case["remove"]], graph_name=OWN_GRAPH)
    assert flip["original_verdict"] == "NO" and flip["new_verdict"] == "YES"


def test_a_decision_takes_few_trips_to_the_database(seeded, monkeypatch):
    calls = counting(seeded, monkeypatch)
    res = decide("CUST-01", 45000, graph=seeded)
    assert res["decision_id"] and len(calls) <= 6, calls


def test_saved_decision_has_every_link_and_still_verifies(seeded, monkeypatch):
    res = decide("CUST-01", 45000, graph=seeded)
    did = res["decision_id"]
    used = {r[0] for r in seeded.query(
        "MATCH (:Decision {id:$d})-[:USED_EVIDENCE]->(e) RETURN e.id", {"d": did}).result_set}
    assert used == {e["id"] for e in res["evidence"]}
    rules = {r[0] for r in seeded.query(
        "MATCH (:Decision {id:$d})-[:APPLIED_RULE]->(r:Rule) RETURN r.id", {"d": did}).result_set}
    assert rules == {"R_LIMIT", "R_BROKEN_PROMISE", "R_FAMILY"}
    about = seeded.query("MATCH (:Decision {id:$d})-[:ABOUT]->(c) RETURN c.id", {"d": did}).result_set
    assert about == [["CUST-01"]]
    assert seeded.query("MATCH (r:Rule) RETURN count(r)").result_set[0][0] == 3
    snap = seeded.query("MATCH (d:Decision {id:$d}) RETURN d.snapshot", {"d": did}).result_set[0][0]
    assert json.loads(snap)["Customer:CUST-01"]



def test_a_second_decision_does_not_duplicate_the_rules(seeded):
    decide("CUST-01", 45000, graph=seeded)
    decide("CUST-02", 90000, graph=seeded)
    assert seeded.query("MATCH (r:Rule) RETURN count(r)").result_set[0][0] == 3


def test_demo_route_opens_on_the_deep_case(seeded, monkeypatch):
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": seeded)
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": seeded)
    monkeypatch.setitem(webapp._own_seen, "at", 1e18)
    monkeypatch.setitem(webapp._own_seen, "ok", True)
    webapp._case_cache.clear()
    webapp.reset_limits()
    r = webapp.app.test_client().post("/demo")
    webapp._case_cache.clear()
    assert r.status_code == 302 and "try=TI-005" in r.headers["Location"]
