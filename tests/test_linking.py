"""Tests for linking.py (matching payments to sales) and the real-shop loader.

The matching rules are pure, so most tests need no database. The graph tests use a
tiny invented shop in a private graph that is deleted afterwards.
"""
import uuid

import pytest

import linking
import real_shop
from db import get_db
from rules import decide, read_state, snapshot_of
from verify import verify_decision


# ---------------------------------------------------------------- the rules, no database

def test_exact_payment_settles_the_matching_sale():
    links, unapplied = linking.plan_customer(
        [("T1", 5000, "2026-05-01"), ("T2", 1000, "2026-05-02")],
        [("P1", 1000, "2026-05-03")])
    assert links == [("P1", "T2", 1000, "exact")]
    assert unapplied == 0


def test_oldest_sale_is_settled_first_and_a_payment_can_split():
    links, unapplied = linking.plan_customer(
        [("T1", 300, "2026-05-01"), ("T2", 400, "2026-05-02")],
        [("P1", 500, "2026-05-05")])
    assert links == [("P1", "T1", 300, "oldest_first"), ("P1", "T2", 200, "oldest_first")]
    assert unapplied == 0


def test_a_payment_never_settles_a_later_sale():
    links, unapplied = linking.plan_customer(
        [("T1", 700, "2026-06-10")], [("P1", 700, "2026-06-01")])
    assert links == []
    assert unapplied == 700          # reported, never used on a later sale


def test_leftover_money_is_reported_as_unapplied():
    links, unapplied = linking.plan_customer(
        [("T1", 200, "2026-05-01")], [("P1", 500, "2026-05-02")])
    assert sum(l[2] for l in links) == 200
    assert unapplied == 300


def test_no_sale_or_payment_is_used_for_more_than_its_amount():
    trades = [("T%d" % i, 100 * (i + 1), "2026-05-%02d" % (i + 1)) for i in range(8)]
    pays = [("P%d" % i, 150 * (i + 1), "2026-06-%02d" % (i + 1)) for i in range(6)]
    links, _ = linking.plan_customer(trades, pays)
    by_t, by_p = {}, {}
    for pid, tid, amt, _m in links:
        by_t[tid] = by_t.get(tid, 0) + amt
        by_p[pid] = by_p.get(pid, 0) + amt
    amount_t = {t[0]: t[1] for t in trades}
    amount_p = {p[0]: p[1] for p in pays}
    assert all(by_t[t] <= amount_t[t] for t in by_t)
    assert all(by_p[p] <= amount_p[p] for p in by_p)


def test_same_input_gives_the_same_links():
    trades = [("T1", 100, "2026-05-01"), ("T2", 100, "2026-05-01"), ("T3", 250, "2026-05-02")]
    pays = [("P1", 100, "2026-05-03"), ("P2", 300, "2026-05-04")]
    assert linking.plan_customer(trades, pays) == linking.plan_customer(list(reversed(trades)), list(reversed(pays)))


# ---------------------------------------------------------------- the graph

EXPORT = {
    "customers": [{"id": "CUST-001"}, {"id": "CUST-002"}],
    "sales": [
        {"id": "T-0001", "kind": "manual_credit", "customer": "CUST-001", "amount": 5000, "date": "2026-05-01", "paid": 0},
        {"id": "T-0002", "kind": "manual_credit", "customer": "CUST-001", "amount": 3000, "date": "2026-05-10", "paid": 0},
        {"id": "T-0003", "kind": "manual_credit", "customer": "CUST-002", "amount": 5000, "date": "2026-05-02", "paid": 0},
    ],
    "payments": [
        {"id": "P-0001", "customer": "CUST-001", "amount": 5000, "date": "2026-05-20", "settles": None, "applied": 0},
        {"id": "P-0002", "customer": "CUST-002", "amount": 1000, "date": "2026-05-21", "settles": None, "applied": 0},
    ],
    "promises": [],
}


@pytest.fixture()
def shop():
    db = get_db()
    name = "test_real_" + uuid.uuid4().hex[:8]
    real_shop.load_real(db, EXPORT, graph_name=name)
    g = db.select_graph(name)
    yield g
    try:
        g.delete()
    except Exception:
        pass


def test_loader_tags_every_record_real_and_keeps_the_customer_of_each_payment(shop):
    assert shop.query("MATCH (c:Customer) WHERE c.source <> 'real_shop' RETURN count(c)").result_set[0][0] == 0
    assert shop.query("MATCH (:Customer {id:'CUST-002'})-[:PAID]->(p:Payment) RETURN p.id").result_set == [["P-0002"]]


def test_loader_refuses_data_with_a_name():
    bad = dict(EXPORT, customers=[{"id": "CUST-001", "name": "A Person"}])
    with pytest.raises(ValueError):
        real_shop.load_real(get_db(), bad, graph_name="test_real_refused")


def test_matching_is_saved_as_inferred_links_and_changes_the_debt(shop):
    assert decide("CUST-001", 1000, graph=shop, save=False)["open_debt"] == 8000      # nothing linked yet
    res = linking.infer_all(shop)
    assert res["links"] == 2 and res["exact"] == 1
    d = decide("CUST-001", 1000, graph=shop, save=False)
    assert d["open_debt"] == 3000                                                   # T-0001 settled
    st = read_state(shop, "CUST-001")
    assert st["inferred"] == {"P-0001>T-0001": "exact"}
    assert st["settles"]["P-0001>T-0001"] == 5000
    # a confirmed link is never created by matching
    assert shop.query("MATCH ()-[r:SETTLES]->() RETURN count(r)").result_set[0][0] == 0


def test_a_customers_payment_is_never_used_on_another_customers_sale(shop):
    linking.infer_all(shop)
    st = read_state(shop, "CUST-002")
    assert st["inferred"] == {"P-0002>T-0003": "oldest_first"}
    assert st["settles"]["P-0002>T-0003"] == 1000


def test_replay_passes_then_fails_when_an_inferred_link_is_changed(shop):
    linking.infer_all(shop)
    d = decide("CUST-001", 1000, graph=shop)
    assert d["decision_id"]
    row = shop.query("MATCH (d:Decision {id:$i}) RETURN d.id, d.customer_id, d.request, d.verdict, "
                     "d.fingerprint, d.snapshot", {"i": d["decision_id"]}).result_set[0]
    ok, problems = verify_decision(shop, tuple(row))
    assert ok, problems
    shop.query("MATCH ()-[r:INFERRED_SETTLES]->() SET r.amount = 1")
    ok, problems = verify_decision(shop, tuple(row))
    assert not ok


def test_rematching_is_refused_once_a_decision_relies_on_the_links(shop):
    linking.infer_all(shop)
    decide("CUST-001", 1000, graph=shop)
    with pytest.raises(RuntimeError):
        linking.infer_all(shop)
    assert linking.infer_all(shop, force=True)["links"] == 2


def test_dry_run_saves_nothing(shop):
    res = linking.infer_all(shop, dry_run=True)
    assert res["links"] == 2
    assert shop.query("MATCH ()-[r:INFERRED_SETTLES]->() RETURN count(r)").result_set[0][0] == 0


def test_graphs_without_inferred_links_snapshot_exactly_as_before(shop):
    st = read_state(shop, "CUST-001")
    assert st["inferred"] == {}
    assert not any("inferred" in v for v in snapshot_of(st).values())
