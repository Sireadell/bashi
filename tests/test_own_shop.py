"""Tests for the own-shop seed, the loader, the shop picker, the demo buttons, health and keepalive.

Loader and page tests use a tiny FAKE seed. The real seed (own_audit_seed.py) is checked
for leaks and loaded into a private graph.
"""
import copy
import os
import uuid

import pytest

import app as webapp
import keepalive
import own_shop
import startup
import whatif
from db import OWN_GRAPH, get_db
from own_audit_seed import SEED
from rules import decide

R, I = "real_audit", "invented"

FAKE = {
    "customers": [{"id": "CUST-A", "source": R}, {"id": "CUST-01", "source": I}, {"id": "CUST-02", "source": I}],
    "sales": [
        {"id": "TR-1", "kind": "sale", "customer": "CUST-A", "amount": 50000, "date": "2026-05-04", "paid": 50000, "source": R},
        {"id": "TI-001", "kind": "sale", "customer": "CUST-01", "amount": 20000, "date": "2026-07-01", "paid": 20000, "source": I},
        {"id": "TI-002", "kind": "sale", "customer": "CUST-02", "amount": 30000, "date": "2026-09-05", "paid": 0, "source": I},
    ],
    "payments": [
        {"id": "PY-R1", "customer": "CUST-A", "amount": 50000, "date": "2026-05-04", "settles": None, "applied": 0, "source": R},
        {"id": "PY-001", "customer": "CUST-01", "amount": 20000, "date": "2026-07-05", "settles": "TI-001", "applied": 20000, "source": I},
    ],
    "promises": [
        {"id": "PR001", "customer": "CUST-01", "amount": 10000, "date": "2026-08-01", "due": "2026-01-01", "kept": False, "source": I},
    ],
}

TEMP_GRAPHS = []


def load_temp(data):
    db = get_db()
    name = "shop_own_test_" + uuid.uuid4().hex[:8]
    own_shop.load_seed(db, data, graph_name=name)
    g = db.select_graph(name)
    TEMP_GRAPHS.append(g)
    return g


@pytest.fixture(autouse=True)
def _drop_temp_graphs():
    yield
    while TEMP_GRAPHS:
        try:
            TEMP_GRAPHS.pop().delete()
        except Exception:
            pass


@pytest.fixture()
def own_graph():
    return load_temp(FAKE)


# ---------------------------------------------------------------- the seed itself

def test_seed_has_no_personal_information():
    assert own_shop.find_leaks(SEED) == []


def test_seed_keys_are_only_codes_amounts_dates_and_flags():
    allowed = {"id", "source", "kind", "customer", "amount", "date", "paid", "settles", "applied", "due", "kept"}
    for rows in SEED.values():
        for row in rows:
            assert set(row) <= allowed, set(row) - allowed


def test_seed_real_part_is_the_eight_audited_trades():
    real = [s for s in SEED["sales"] if s["source"] == R]
    assert len(real) == 8 and sum(s["amount"] for s in real) == 388340
    assert all(s["paid"] == s["amount"] for s in real)               # each sale said paid
    pays = [p for p in SEED["payments"] if p["source"] == R]
    assert len(pays) == 8 and all(p["settles"] is None for p in pays)  # payment not linked
    assert {c["id"] for c in SEED["customers"] if c["source"] == R} == {"CUST-A", "CUST-B", "CUST-C", "CUST-D"}


def test_seed_invented_part_has_one_broken_promise_and_one_phantom():
    inv_c = [c for c in SEED["customers"] if c["source"] == I]
    assert len(inv_c) == 12
    broken = [p for p in SEED["promises"] if not p["kept"]]
    assert [p["customer"] for p in broken] == ["CUST-01"]
    phantoms = [p for p in SEED["payments"] if p["source"] == I and p["settles"] is None]
    assert [p["customer"] for p in phantoms] == ["CUST-02"]
    assert not [p for p in SEED["promises"] if p["source"] == R]


def test_seed_loads_and_every_real_trade_raises_the_phantom_flag():
    g = load_temp(SEED)
    q = lambda c: g.query(c).result_set[0][0]
    assert q("MATCH (n:Customer) RETURN count(n)") == 16
    assert q("MATCH (n:Trade {source:'real_audit'}) RETURN count(n)") == 8
    assert q("MATCH (n:Payment) WHERE NOT (n)-[:SETTLES]->(:Trade) RETURN count(n)") == 9   # 8 real + 1 invented
    assert q("MATCH (c:Customer) WHERE c.source IS NULL RETURN count(c)") == 0
    for cid, debt in (("CUST-A", 1330), ("CUST-B", 343210), ("CUST-C", 300), ("CUST-D", 43500)):
        r = decide(cid, 1000, graph=g, save=False)
        assert r["open_debt"] == debt, cid
    assert len(decide("CUST-B", 1000, graph=g, save=False)["possible_phantoms"]) == 3
    assert len(decide("CUST-02", 1000, graph=g, save=False)["possible_phantoms"]) == 1
    assert decide("CUST-03", 1000, graph=g, save=False)["possible_phantoms"] == []


def test_seed_demo_and_real_cases():
    g = load_temp(SEED)
    case = own_shop.find_demo_case(g, only_source=I)
    assert case == {"customer": "CUST-02", "amount": 90000, "remove": "TI-005", "kind": "sale",
                    "payment": "PY-005"}
    assert own_shop.find_real_case(g) == {"customer": "CUST-B", "amount": 10000}


# ---------------------------------------------------------------- preparing rows

def test_prepare_assumes_a_limit_from_the_biggest_sale():
    rows = own_shop.prepare(FAKE)
    assert {c["id"]: c["credit_limit"] for c in rows["customers"]} == \
        {"CUST-A": 100000, "CUST-01": 100000, "CUST-02": 100000}
    assert own_shop.credit_limit(130000) == 150000
    assert own_shop.credit_limit(0) == 100000


def test_leak_check_catches_names_phones_notes_and_long_text():
    for bad in ({"name": "x"}, {"Phone": "1"}, {"a": {"home_address": "x"}}, {"x": [{"note": "n"}]},
                {"x": "a" * 21}, {"x": ["short", "b" * 40]}):
        assert own_shop.find_leaks(bad), bad
    assert own_shop.find_leaks(FAKE) == []
    assert own_shop.find_leaks({"x": "a" * 20}) == []


def test_prepare_refuses_data_with_personal_information():
    bad = copy.deepcopy(FAKE)
    bad["customers"][0]["name"] = "Someone"
    with pytest.raises(ValueError, match="not anonymous"):
        own_shop.prepare(bad)


@pytest.mark.parametrize("mutate", [
    lambda d: d["sales"][0].update(customer="CUST-09"),
    lambda d: d["payments"][1].update(settles="T-9999"),
    lambda d: d["sales"][0].update(amount=12.5),
    lambda d: d["customers"].append({"id": "CUST-A", "source": R}),
    lambda d: d["sales"][0].pop("source"),
    lambda d: d["customers"][0].update(source="made up"),
])
def test_prepare_rejects_broken_links_amounts_and_sources(mutate):
    bad = copy.deepcopy(FAKE)
    mutate(bad)
    with pytest.raises(ValueError):
        own_shop.prepare(bad)


def test_bad_data_never_touches_the_graph():
    bad = copy.deepcopy(FAKE)
    bad["customers"][0]["phone"] = "0"
    db = get_db()
    name = "shop_own_test_" + uuid.uuid4().hex[:8]
    with pytest.raises(ValueError):
        own_shop.load_seed(db, bad, graph_name=name)
    assert name not in db.list_graphs()


# ---------------------------------------------------------------- the loaded graph

def test_loaded_graph_matches_the_data_and_carries_sources(own_graph):
    q = lambda c: own_graph.query(c).result_set[0][0]
    assert q("MATCH (n:Customer) RETURN count(n)") == 3
    assert q("MATCH (n:Trade) RETURN count(n)") == 3
    assert q("MATCH (n:Payment) RETURN count(n)") == 2
    assert q("MATCH ()-[r:SETTLES]->() RETURN count(r)") == 1
    assert q("MATCH (n:Promise) RETURN count(n)") == 1
    assert q("MATCH (c:Customer {source:'real_audit'}) RETURN count(c)") == 1
    assert q("MATCH (c:Customer) WHERE c.name <> c.id RETURN count(c)") == 0


def test_needs_load_detects_missing_empty_and_old_graphs():
    db = get_db()
    assert own_shop.needs_load(db, "shop_own_does_not_exist") is True
    g = load_temp(FAKE)
    assert own_shop.needs_load(db, g.name) is False
    g.query("MATCH (c:Customer {id:'CUST-A'}) REMOVE c.source")
    assert own_shop.needs_load(db, g.name) is True


def test_rules_work_on_the_loaded_shop(own_graph):
    r = decide("CUST-A", 10000, graph=own_graph, save=False)
    assert r["verdict"] == "YES" and r["open_debt"] == 50000      # sale said paid, but the payment is not linked
    assert decide("CUST-A", 60000, graph=own_graph, save=False)["verdict"] == "NO"
    r = decide("CUST-01", 5000, graph=own_graph)
    assert r["verdict"] == "NO" and r["broken_promises"] == ["PR001"] and r["decision_id"] == "D1001"


def test_whatif_and_replay_work_on_the_loaded_shop(own_graph, monkeypatch):
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": own_graph)
    did = decide("CUST-01", 5000, graph=own_graph)["decision_id"]
    res = whatif.whatif(did, ["PR001"], graph_name=OWN_GRAPH)
    assert res["original_verdict"] == "NO" and res["new_verdict"] == "YES" and res["changed"]
    from verify import verify_decision
    d = whatif.load_decision(did, own_graph)
    ok, problems = verify_decision(own_graph, (d["id"], d["customer_id"], d["request"], d["verdict"],
                                               d["fingerprint"], d["snapshot"]))
    assert ok, problems


# ---------------------------------------------------------------- the shop picker

@pytest.fixture()
def picker(graph, own_graph, monkeypatch):
    """The web app with shop_a replaced by a seeded copy and shop_own by the fake own shop."""
    shops = {"shop_a": graph, OWN_GRAPH: own_graph}
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": shops[name])
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": shops[name])
    monkeypatch.setitem(webapp._own_seen, "at", 1e18)
    monkeypatch.setitem(webapp._own_seen, "ok", True)
    webapp.reset_limits()
    yield webapp.app.test_client()
    webapp.reset_limits()


def pick(client, which):
    client.post("/shop", data={"shop": which})


def test_own_shop_is_the_default_and_says_which_part_is_real(picker):
    page = picker.get("/").get_data(as_text=True)
    assert own_shop.LABEL_TEXT in page and "CUST-01" in page
    assert "Real part:" in page and "Invented part:" in page and "assumed" in page
    assert "Practice shop (invented data)" in page and "selected>My own shop" in page
    assert "CUST-A), real," in page and "CUST-01), invented," in page      # tags in the customer list
    assert "Tunde" not in page


def test_practice_shop_can_be_picked_and_is_labelled(picker):
    pick(picker, "demo")
    page = picker.get("/").get_data(as_text=True)
    assert "Demo data, all synthetic" in page and "Tunde" in page
    assert own_shop.LABEL_TEXT not in page and "Real part:" not in page
    pick(picker, "own")
    assert own_shop.LABEL_TEXT in picker.get("/").get_data(as_text=True)


def test_own_shop_answer_receipt_tag_and_whatif(picker):
    page = picker.post("/", data={"customer": "CUST-01", "amount": "5000"}).get_data(as_text=True)
    assert "NO" in page and "/receipt/D1001" in page
    receipt = picker.get("/receipt/D1001").get_data(as_text=True)
    assert "PR001" in receipt and "Verified" in receipt and "(invented)" in receipt
    res = picker.post("/whatif/D1001", json={"remove": ["PR001"]}).get_json()
    assert res["new_verdict"] == "YES"


def test_receipt_is_found_even_if_the_other_shop_is_selected(picker):
    picker.post("/", data={"customer": "CUST-01", "amount": "5000"})
    pick(picker, "demo")
    assert "PR001" in picker.get("/receipt/D1001").get_data(as_text=True)


def test_missing_own_shop_falls_back_to_the_practice_shop(picker, monkeypatch):
    monkeypatch.setitem(webapp._own_seen, "ok", False)
    page = picker.get("/").get_data(as_text=True)
    assert "Demo data, all synthetic" in page and "Tunde" in page
    assert "Practice shop" not in page and "My own shop" not in page and "Real part:" not in page
    picker.set_cookie("bashi_shop", "own")
    assert "Tunde" in picker.get("/").get_data(as_text=True)


def test_own_available_needs_real_own_shop_customers(own_graph, graph, monkeypatch):
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": own_graph)
    monkeypatch.setitem(webapp._own_seen, "at", 0.0)
    assert webapp.own_available() is True
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": graph)   # a copy of the practice shop
    monkeypatch.setitem(webapp._own_seen, "at", 0.0)
    assert webapp.own_available() is False


# ---------------------------------------------------------------- the demo buttons

def test_demo_case_search_finds_a_no_that_one_record_flips(own_graph, monkeypatch):
    case = own_shop.find_demo_case(own_graph, only_source=I)
    assert case == {"customer": "CUST-01", "amount": 45000, "remove": "PR001", "kind": "promise"}
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": own_graph)
    did = decide(case["customer"], case["amount"], graph=own_graph)["decision_id"]
    res = whatif.whatif(did, [case["remove"]], graph_name=OWN_GRAPH)
    assert res["original_verdict"] == "NO" and res["new_verdict"] == "YES"


def test_demo_case_search_ignores_real_customers_when_asked():
    data = copy.deepcopy(FAKE)
    data["promises"] = []
    g = load_temp(data)
    assert own_shop.find_demo_case(g, only_source=I)["customer"] != "CUST-A"
    assert own_shop.find_demo_case(g, only_source=R)["customer"] == "CUST-A"


def test_demo_case_search_returns_none_when_nothing_flips():
    data = {"customers": [{"id": "CUST-01", "source": I}], "promises": [], "payments": [],
            "sales": [{"id": "TI-001", "kind": "sale", "customer": "CUST-01", "amount": 5000,
                       "date": "2026-09-01", "paid": 5000, "source": I}]}
    assert own_shop.find_demo_case(load_temp(data), only_source=I) is None


def test_real_case_is_none_without_real_customers():
    data = copy.deepcopy(FAKE)
    data["customers"] = [c for c in data["customers"] if c["source"] == I]
    data["sales"] = [s for s in data["sales"] if s["source"] == I]
    data["payments"] = [p for p in data["payments"] if p["source"] == I]
    assert own_shop.find_real_case(load_temp(data)) is None


def test_demo_button_on_the_own_shop_uses_the_invented_flip_customer(picker):
    r = picker.post("/demo")
    assert r.status_code == 302 and "/receipt/D1001" in r.headers["Location"] and "try=PR001" in r.headers["Location"]
    page = picker.get(r.headers["Location"]).get_data(as_text=True)
    assert "Try it:" in page and "(invented)" in page
    assert picker.post("/whatif/D1001", json={"remove": ["PR001"]}).get_json()["new_verdict"] == "YES"


def test_real_audit_button_opens_the_phantom_debt_receipt(picker):
    page = picker.get("/").get_data(as_text=True)
    assert "See the real audit case" in page
    r = picker.post("/demo/real")
    assert r.status_code == 302 and "/receipt/D1001" in r.headers["Location"]
    page = picker.get(r.headers["Location"]).get_data(as_text=True)
    assert "(real)" in page and "Possible phantom debt" in page and "TR-1" in page and "PY-R1" in page


def test_real_audit_button_is_own_shop_only(picker):
    pick(picker, "demo")
    assert "See the real audit case" not in picker.get("/").get_data(as_text=True)
    r = picker.post("/demo/real")
    assert r.status_code == 302 and "/receipt/" not in r.headers["Location"]
    assert picker.get("/demo/real").status_code == 302


def test_demo_button_on_the_practice_shop_is_the_tunde_case(picker):
    pick(picker, "demo")
    r = picker.post("/demo")
    assert r.status_code == 302 and "try=PR001" in r.headers["Location"]
    page = picker.get(r.headers["Location"]).get_data(as_text=True)
    assert "Tunde" in page and "NO" in page


def test_demo_button_falls_back_to_tunde_when_the_own_shop_has_no_case(picker, monkeypatch):
    monkeypatch.setattr(webapp, "find_demo_case", lambda g, only_source=None: None)
    r = picker.post("/demo")
    assert r.status_code == 302 and "try=PR001" in r.headers["Location"]
    assert "Tunde" in picker.get(r.headers["Location"]).get_data(as_text=True)


def test_receipt_hint_ignores_ids_that_are_not_on_the_receipt(picker):
    r = picker.post("/demo")
    page = picker.get(r.headers["Location"].split("?")[0] + "?try=%3Cb%3Ex%3C%2Fb%3E").get_data(as_text=True)
    assert "Try it:" not in page and "<b>x</b>" not in page


# ---------------------------------------------------------------- health, startup and keepalive

def test_health_reports_both_shops(picker):
    j = picker.get("/health").get_json()
    assert j["ok"] is True and j["customers"] == 25 and j["own_customers"] == 3


def test_health_stays_ok_when_only_one_shop_answers(picker, monkeypatch):
    real = webapp.get_graph

    def flaky(name="shop_a"):
        if name == OWN_GRAPH:
            raise RuntimeError("gone")
        return real(name)
    monkeypatch.setattr(webapp, "get_graph", flaky)
    j = picker.get("/health").get_json()
    assert j["ok"] is True and j["own_customers"] == 0


def test_health_fails_when_neither_shop_answers(picker, monkeypatch):
    def boom(name="shop_a"):
        raise RuntimeError("down")
    monkeypatch.setattr(webapp, "get_graph", boom)
    r = picker.get("/health")
    assert r.status_code == 503 and r.get_json()["ok"] is False


def test_startup_loads_the_own_shop_only_when_needed(monkeypatch):
    loaded = []
    monkeypatch.setattr(startup, "get_db", lambda: "db")
    monkeypatch.setattr(own_shop, "load_seed", lambda db: loaded.append(db))
    monkeypatch.setattr(own_shop, "needs_load", lambda db: True)
    assert startup.ensure_own_shop() is True and loaded == ["db"]
    monkeypatch.setattr(own_shop, "needs_load", lambda db: False)
    assert startup.ensure_own_shop() is False and loaded == ["db"]


class _FakeDb:
    def list_graphs(self):
        return []


def test_keepalive_rebuilds_a_lost_own_shop(monkeypatch):
    import db as dbmod
    monkeypatch.setattr(keepalive, "tiny_read", lambda: 25)
    monkeypatch.delenv("BASHI_URL", raising=False)
    monkeypatch.setattr(dbmod, "get_db", lambda: _FakeDb())
    monkeypatch.setattr(own_shop, "needs_load", lambda db: True)
    called = []
    monkeypatch.setattr(startup, "ensure_own_shop", lambda: called.append(1))
    assert keepalive.once() == 0 and called == [1]


def test_keepalive_never_fails_because_of_the_own_shop(monkeypatch):
    import db as dbmod
    monkeypatch.setattr(keepalive, "tiny_read", lambda: 25)
    monkeypatch.delenv("BASHI_URL", raising=False)

    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(dbmod, "get_db", boom)
    assert keepalive.once() == 0


# ---------------------------------------------------------------- banner on receipts

def test_real_banner_only_on_receipts_of_real_customers(picker):
    picker.post("/", data={"customer": "CUST-A", "amount": "5000"})        # D1001, real
    picker.post("/", data={"customer": "CUST-01", "amount": "5000"})       # D1002, invented
    real = picker.get("/receipt/D1001").get_data(as_text=True)
    invented = picker.get("/receipt/D1002").get_data(as_text=True)
    assert ">%s<" % own_shop.LABEL_TEXT in real and "Invented customer, not real data" not in real
    assert "Invented customer, not real data" in invented and own_shop.LABEL_TEXT not in invented


def test_record_page_banner_follows_the_record_source(picker):
    picker.post("/", data={"customer": "CUST-A", "amount": "5000"})
    picker.post("/", data={"customer": "CUST-01", "amount": "5000"})
    real = picker.get("/record/Trade/TR-1?d=D1001").get_data(as_text=True)
    invented = picker.get("/record/Trade/TI-001?d=D1002").get_data(as_text=True)
    assert ">%s<" % own_shop.LABEL_TEXT in real
    assert "Invented customer, not real data" in invented and own_shop.LABEL_TEXT not in invented


def test_practice_shop_receipt_keeps_the_practice_banner_even_when_own_is_selected(picker):
    pick(picker, "demo")
    r = picker.post("/demo")
    pick(picker, "own")
    page = picker.get(r.headers["Location"]).get_data(as_text=True)
    assert "Demo data, all synthetic" in page and own_shop.LABEL_TEXT not in page


# ---------------------------------------------------------------- tamper and verify on a chosen graph

import json  # noqa: E402

import db as dbmod  # noqa: E402
import tamper  # noqa: E402
import verify  # noqa: E402


class _Db:
    """Stands in for the database connection: hands out the graphs it was given."""
    def __init__(self, **graphs):
        self.graphs = graphs

    def list_graphs(self):
        return list(self.graphs)

    def select_graph(self, name):
        return self.graphs[name]


@pytest.fixture()
def tamper_env(own_graph, graph, monkeypatch, tmp_path):
    monkeypatch.setattr(tamper, "STATE", str(tmp_path / "state.json"))
    fake = _Db(shop_own=own_graph, shop_a=graph)
    monkeypatch.setattr(dbmod, "get_db", lambda: fake)
    return fake


def test_graph_argument_parsing():
    assert dbmod.pop_graph_arg(["TR-2", "300000", "--graph", "shop_own"]) == ("shop_own", ["TR-2", "300000"])
    assert dbmod.pop_graph_arg(["--graph=shop_a", "--restore"]) == ("shop_a", ["--restore"])
    assert dbmod.pop_graph_arg(["T1", "5"]) == (None, ["T1", "5"])


def test_tools_default_to_the_own_shop_when_loaded_else_the_practice_shop(tamper_env, own_graph, graph):
    assert dbmod.resolve_graph_name(tamper_env) == "shop_own"
    assert dbmod.resolve_graph_name(tamper_env, "shop_a") == "shop_a"
    assert dbmod.resolve_graph_name(_Db(shop_a=graph)) == "shop_a"           # no own graph
    assert dbmod.resolve_graph_name(_Db(shop_own=graph, shop_a=graph)) == "shop_a"   # not an own shop


def test_tamper_demo_on_a_real_audit_trade(tamper_env, own_graph, capsys):
    did = decide("CUST-A", 10000, graph=own_graph)["decision_id"]
    assert verify.main([]) == 0 and "Graph: shop_own" in capsys.readouterr().out
    assert tamper.main(["tamper.py", "TR-1", "80000"]) == 0
    out = capsys.readouterr().out
    assert "Graph: shop_own" in out and "Trade TR-1 amount changed N50,000 -> N80,000" in out
    assert "--graph shop_own" in out
    assert verify.main(["--graph", "shop_own"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  " + did in out and "Trade TR-1 amount changed N50,000 -> N80,000" in out
    assert tamper.main(["tamper.py", "--restore", "--graph", "shop_own"]) == 0
    assert "Restored Trade TR-1 amount to N50,000" in capsys.readouterr().out
    assert verify.main(["--graph", "shop_own"]) == 0
    assert "PASS  " + did in capsys.readouterr().out


def test_tamper_state_is_kept_per_graph(tamper_env, own_graph, graph):
    tamper.tamper(own_graph, "TR-1", 80000)
    tamper.tamper(graph, "T0002", 12345)
    saved = json.load(open(tamper.STATE))
    assert saved == {own_graph.name: {"TR-1": 50000}, graph.name: {"T0002": saved[graph.name]["T0002"]}}
    tamper.restore(own_graph)
    assert own_graph.query("MATCH (t:Trade {id:'TR-1'}) RETURN t.amount").result_set[0][0] == 50000
    assert json.load(open(tamper.STATE)).keys() == {graph.name}      # the other graph's change is still saved
    tamper.restore(graph)
    assert not os.path.exists(tamper.STATE)


def test_old_flat_state_file_still_restores_on_the_practice_graph(tamper_env, graph):
    amt = graph.query("MATCH (t:Trade {id:'T0002'}) RETURN t.amount").result_set[0][0]
    graph.query("MATCH (t:Trade {id:'T0002'}) SET t.amount = 1")
    with open(tamper.STATE, "w") as f:
        json.dump({"T0002": amt}, f)
    class AsPracticeShop:   # the test graph is a copy; the old file always meant the practice shop
        name = "shop_a"
        query = staticmethod(graph.query)
    assert tamper.restore(AsPracticeShop()) == {"T0002": amt}
    assert graph.query("MATCH (t:Trade {id:'T0002'}) RETURN t.amount").result_set[0][0] == amt


def test_rules_tool_accepts_a_graph_name(tamper_env, capsys):
    import rules
    assert rules.main(["rules.py", "CUST-01", "5000", "--no-save", "--graph", "shop_own"]) == 0
    out = capsys.readouterr().out
    assert "Graph: shop_own" in out and "Verdict:      NO" in out and "PR001" in out
