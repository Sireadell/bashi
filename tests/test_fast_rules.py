"""Fast judge subset: the two rules, the fingerprint and the payment matching, all on
in-memory data. No database, no network, no keys.

    python -m pytest tests/test_fast_rules.py tests/test_demo_cache.py -q
"""
import copy
import itertools

import pytest

import linking
import own_shop
import rules
from rules import CANNOT_TRACE, evaluate, fingerprint, snapshot_of


def make_state(limit=100000, trades=None, payments=None, settles=None, promises=None):
    return {
        "customer": {"id": "C900", "limit": limit},
        "trades": {k: {"amount": v, "date": "2026-05-01"} for k, v in (trades or {}).items()},
        "payments": {k: {"amount": v, "date": "2026-05-10"} for k, v in (payments or {}).items()},
        "settles": dict(settles or {}),
        "promises": {k: {"amount": 1000, "due": "2026-06-01", "kept": False, "broke": b}
                     for k, b in (promises or {}).items()},
    }


# ---------------------------------------------------------------- rule 1: the limit

def test_within_limit_is_yes():
    r = evaluate(make_state(trades={"T1": 40000}), 45000)
    assert r["verdict"] == "YES" and r["open_debt"] == 40000 and r["rules_failed"] == []


def test_exactly_at_the_limit_is_yes():
    assert evaluate(make_state(limit=50000, trades={"T1": 5000}), 45000)["verdict"] == "YES"


def test_one_naira_over_the_limit_is_no():
    r = evaluate(make_state(limit=50000, trades={"T1": 5001}), 45000)
    assert r["verdict"] == "NO" and r["rules_failed"] == ["R_LIMIT"]


def test_payments_reduce_open_debt():
    s = make_state(limit=50000, trades={"T1": 30000}, payments={"P1": 30000},
                   settles={"P1>T1": 30000})
    r = evaluate(s, 45000)
    assert r["verdict"] == "YES" and r["open_debt"] == 0


# ---------------------------------------------------------------- rule 2: broken promises

def test_a_broken_promise_alone_makes_it_no():
    r = evaluate(make_state(promises={"PR1": True}), 1000)
    assert r["verdict"] == "NO" and r["rules_failed"] == ["R_BROKEN_PROMISE"]
    assert r["broken_promises"] == ["PR1"]


def test_a_kept_promise_does_not_count():
    assert evaluate(make_state(promises={"PR1": False}), 1000)["verdict"] == "YES"


def test_both_rules_can_fail_together():
    r = evaluate(make_state(limit=10, promises={"PR1": True}), 1000)
    assert r["rules_failed"] == ["R_LIMIT", "R_BROKEN_PROMISE"]
    assert "broken promise" in r["reason"] and "above the limit" in r["reason"]


# ---------------------------------------------------------------- refusing to guess

@pytest.mark.parametrize("amount", [0, -5, 1.5, "45000", None, True])
def test_bad_request_amounts_cannot_be_traced(amount):
    r = evaluate(make_state(), amount)
    assert r["verdict"] == CANNOT_TRACE and r["open_debt"] is None


def test_missing_limit_cannot_be_traced():
    assert evaluate(make_state(limit=None), 1000)["verdict"] == CANNOT_TRACE


def test_missing_trade_amount_cannot_be_traced():
    assert evaluate(make_state(trades={"T1": None}), 1000)["verdict"] == CANNOT_TRACE


def test_a_payment_larger_than_its_sale_cannot_be_traced():
    s = make_state(trades={"T1": 100}, payments={"P1": 500}, settles={"P1>T1": 500})
    assert evaluate(s, 10)["verdict"] == CANNOT_TRACE


def test_a_payment_used_for_more_than_it_paid_cannot_be_traced():
    s = make_state(trades={"T1": 400, "T2": 400}, payments={"P1": 500},
                   settles={"P1>T1": 400, "P1>T2": 400})
    assert evaluate(s, 10)["verdict"] == CANNOT_TRACE


def test_evaluate_does_not_change_the_state_it_is_given():
    s = make_state(limit=10, trades={"T1": 5}, promises={"PR1": True})
    before = copy.deepcopy(s)
    evaluate(s, 1000)
    assert s == before


def test_same_state_same_answer():
    s = make_state(trades={"T1": 40000}, promises={"PR1": True})
    assert evaluate(s, 45000) == evaluate(copy.deepcopy(s), 45000)


# ---------------------------------------------------------------- the fingerprint

def fp(state, amount=45000):
    return fingerprint(snapshot_of(state), evaluate(state, amount)["verdict"], amount)


def test_fingerprint_is_stable_and_order_independent():
    a = make_state(trades={"T1": 100, "T2": 200})
    b = make_state(trades={"T2": 200, "T1": 100})
    assert fp(a) == fp(b) == fp(copy.deepcopy(a))
    assert len(fp(a)) == 64


def test_fingerprint_changes_when_any_record_changes():
    base = make_state(trades={"T1": 40000}, payments={"P1": 100}, settles={"P1>T1": 100},
                      promises={"PR1": True})
    seen = {fp(base)}
    for edit in (
        lambda s: s["trades"]["T1"].update(amount=40001),
        lambda s: s["trades"]["T1"].update(date="2026-05-02"),
        lambda s: s["payments"]["P1"].update(amount=101),
        lambda s: s["settles"].update({"P1>T1": 99}),
        lambda s: s["promises"]["PR1"].update(broke=False),
        lambda s: s["customer"].update(limit=100001),
    ):
        s = copy.deepcopy(base)
        edit(s)
        seen.add(fp(s))
    assert len(seen) == 7          # the original plus six different edits, no two alike


def test_fingerprint_changes_with_the_amount_and_the_verdict():
    s = make_state(trades={"T1": 40000})
    snap = snapshot_of(s)
    assert fingerprint(snap, "YES", 100) != fingerprint(snap, "YES", 101)
    assert fingerprint(snap, "YES", 100) != fingerprint(snap, "NO", 100)


def test_inferred_method_is_part_of_the_fingerprint():
    s = make_state(trades={"T1": 100}, payments={"P1": 100}, settles={"P1>T1": 100})
    a = fp(s)
    s["inferred"] = {"P1>T1": "exact"}
    b = fp(s)
    s["inferred"] = {"P1>T1": "oldest_first"}
    assert len({a, b, fp(s)}) == 3


def test_evidence_list_names_every_record_used():
    s = make_state(trades={"T2": 1, "T1": 1}, payments={"P1": 1}, promises={"PR1": False})
    assert rules.evidence_list(s) == [
        {"label": "Trade", "id": "T1"}, {"label": "Trade", "id": "T2"},
        {"label": "Payment", "id": "P1"}, {"label": "Promise", "id": "PR1"}]


# ---------------------------------------------------------------- what-if on memory

def test_removing_the_broken_promise_flips_no_to_yes():
    s = make_state(trades={"T1": 1000}, promises={"PR1": True})
    assert evaluate(s, 45000)["verdict"] == "NO"
    assert evaluate(own_shop._without(s, "PR1"), 45000)["verdict"] == "YES"
    assert "PR1" in s["promises"]            # the original is untouched


def test_removing_a_sale_removes_its_payment_links():
    s = make_state(trades={"T1": 500}, payments={"P1": 500}, settles={"P1>T1": 500})
    out = own_shop._without(s, "T1")
    assert out["trades"] == {} and out["settles"] == {} and out["payments"] == {}


def test_find_demo_case_picks_the_broken_promise_first(monkeypatch):
    states = {
        "C1": make_state(trades={"T1": 1000}),                       # already YES
        "C2": make_state(trades={"T1": 1000}, promises={"PR9": True}),
    }
    monkeypatch.setattr(rules, "mark_overdue_promises", lambda g: None)
    monkeypatch.setattr(rules, "read_state", lambda g, cid: states.get(cid))

    class FakeGraph:
        def query(self, q, params=None):
            return type("R", (), {"result_set": [[c] for c in sorted(states)]})()

    case = own_shop.find_demo_case(FakeGraph())
    assert case["customer"] == "C2" and case["remove"] == "PR9" and case["kind"] == "promise"


# ---------------------------------------------------------------- linking payments to sales

def test_exact_match_first_then_oldest_first():
    links, left = linking.plan_customer(
        [("T1", 300, "2026-05-01"), ("T2", 400, "2026-05-02")],
        [("P1", 400, "2026-05-05")])
    assert links == [("P1", "T2", 400, "exact")] and left == 0


def test_no_sale_or_payment_is_used_for_more_than_its_amount():
    trades = [("T%d" % i, 100 * (i + 1), "2026-05-%02d" % (i + 1)) for i in range(8)]
    pays = [("P%d" % i, 150 * (i + 1), "2026-06-%02d" % (i + 1)) for i in range(6)]
    links, left = linking.plan_customer(trades, pays)
    by_t, by_p = {}, {}
    for p, t, amt, _ in links:
        by_t[t] = by_t.get(t, 0) + amt
        by_p[p] = by_p.get(p, 0) + amt
    assert all(by_t[t] <= a for t, a, _ in trades if t in by_t)
    assert all(by_p[p] <= a for p, a, _ in pays if p in by_p)
    assert sum(by_p.values()) + left == sum(a for _, a, _ in pays)


def test_linking_is_deterministic_whatever_the_input_order():
    trades = [("T1", 300, "2026-05-01"), ("T2", 400, "2026-05-02"), ("T3", 250, "2026-05-03")]
    pays = [("P1", 500, "2026-05-05"), ("P2", 250, "2026-05-06")]
    first = linking.plan_customer(trades, pays)
    for t, p in itertools.product(itertools.permutations(trades), itertools.permutations(pays)):
        assert linking.plan_customer(list(t), list(p)) == first


def test_linked_state_feeds_straight_into_the_rule():
    """Matching then deciding, all in memory: a customer who paid off their sale is clear."""
    trades = [("T1", 30000, "2026-05-01")]
    pays = [("P1", 30000, "2026-05-09")]
    links, _ = linking.plan_customer(trades, pays)
    s = make_state(limit=50000, trades={"T1": 30000}, payments={"P1": 30000},
                   settles={"%s>%s" % (p, t): a for p, t, a, _ in links})
    r = evaluate(s, 45000)
    assert r["verdict"] == "YES" and r["open_debt"] == 0
