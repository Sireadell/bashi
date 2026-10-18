"""Tests for the demo-case cache in app.py. No database: the finder, the graph and the
decision are replaced with fakes, so these run in a second."""
import pytest

import app as webapp


@pytest.fixture(autouse=True)
def clean_cache():
    webapp.reset_limits()
    yield
    webapp.reset_limits()


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def time(self):
        return self.now


@pytest.fixture()
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(webapp.time, "time", c.time)
    return c


def counting_finder(result):
    calls = []

    def finder(*args, **kwargs):
        calls.append((args, kwargs))
        return dict(result) if result is not None else None
    finder.calls = calls
    return finder


CASE = {"customer": "C007", "amount": 45000, "remove": "PR002", "kind": "promise"}


def test_second_lookup_reuses_the_cached_case(clock):
    finder = counting_finder(CASE)
    first = webapp.cached_case("shop_own", finder, "g", only_source="invented")
    second = webapp.cached_case("shop_own", finder, "g", only_source="invented")
    assert first == second == CASE
    assert len(finder.calls) == 1


def test_cached_case_is_a_copy_so_callers_cannot_change_it(clock):
    finder = counting_finder(CASE)
    webapp.cached_case("shop_own", finder, "g")
    got = webapp.cached_case("shop_own", finder, "g")
    got["customer"] = "HACKED"
    assert webapp.cached_case("shop_own", finder, "g")["customer"] == "C007"


def test_reset_limits_clears_the_cache(clock):
    finder = counting_finder(CASE)
    webapp.cached_case("shop_own", finder, "g")
    assert webapp._case_cache
    webapp.reset_limits()
    assert not webapp._case_cache
    webapp.cached_case("shop_own", finder, "g")
    assert len(finder.calls) == 2


def test_a_cached_case_expires_after_the_ttl(clock):
    finder = counting_finder(CASE)
    webapp.cached_case("shop_own", finder, "g")
    clock.now += webapp.CASE_TTL - 1
    webapp.cached_case("shop_own", finder, "g")
    assert len(finder.calls) == 1          # still fresh one second before the limit
    clock.now += 1
    webapp.cached_case("shop_own", finder, "g")
    assert len(finder.calls) == 2          # expired exactly at the TTL


def test_a_refreshed_case_gets_a_new_clock(clock):
    finder = counting_finder(CASE)
    webapp.cached_case("shop_own", finder, "g")
    clock.now += webapp.CASE_TTL
    webapp.cached_case("shop_own", finder, "g")
    clock.now += webapp.CASE_TTL - 1
    webapp.cached_case("shop_own", finder, "g")
    assert len(finder.calls) == 2


def test_nothing_found_is_not_cached(clock):
    finder = counting_finder(None)
    assert webapp.cached_case("shop_own", finder, "g") is None
    assert webapp.cached_case("shop_own", finder, "g") is None
    assert len(finder.calls) == 2
    assert not webapp._case_cache


def test_different_shops_and_filters_are_cached_separately(clock):
    finder = counting_finder(CASE)
    webapp.cached_case("shop_own", finder, "g", only_source="invented")
    webapp.cached_case("shop_real", finder, "g", only_source="invented")
    webapp.cached_case("shop_own", finder, "g", only_source="real_audit")
    assert len(finder.calls) == 3


# ---------------------------------------------------------------- through the /demo route

@pytest.fixture()
def route(monkeypatch):
    """The /demo route on a pretend own shop. Records every decide() call."""
    state = {"finds": 0, "decisions": [], "case": dict(CASE)}

    def find_demo_case(g, only_source=None):
        state["finds"] += 1
        return dict(state["case"]) if state["case"] else None

    def decide(customer, amount, graph=None, **kw):
        state["decisions"].append((customer, amount, graph))
        return {"decision_id": "D%04d" % len(state["decisions"])}

    monkeypatch.setattr(webapp, "find_demo_case", find_demo_case)
    monkeypatch.setattr(webapp, "decide", decide)
    monkeypatch.setattr(webapp, "own_available", lambda: True)
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": "graph:" + name)
    monkeypatch.setattr(webapp, "prune_decisions", lambda g: None)
    state["client"] = webapp.app.test_client()
    return state


def test_second_demo_click_reuses_the_case_but_decides_fresh(route, clock):
    r1 = route["client"].post("/demo")
    r2 = route["client"].post("/demo")
    assert r1.status_code == r2.status_code == 302
    assert route["finds"] == 1                       # the slow search ran once
    assert len(route["decisions"]) == 2              # but each click made its own decision
    assert r1.headers["Location"] != r2.headers["Location"]
    assert "try=PR002" in r1.headers["Location"]


def test_demo_click_after_the_ttl_searches_again(route, clock):
    route["client"].post("/demo")
    clock.now += webapp.CASE_TTL
    route["client"].post("/demo")
    assert route["finds"] == 2


def test_reset_limits_makes_the_next_click_search_again(route, clock):
    route["client"].post("/demo")
    webapp.reset_limits()
    route["client"].post("/demo")
    assert route["finds"] == 2


def test_falls_back_to_the_tunde_case_when_no_case_is_found(route, clock):
    route["case"] = None
    r = route["client"].post("/demo")
    assert r.status_code == 302 and "try=PR001" in r.headers["Location"]
    customer, amount, graph = route["decisions"][0]
    assert (customer, amount) == ("C001", 45000)
    assert graph == "graph:shop_a"


def test_falls_back_to_the_tunde_case_when_the_search_fails(route, clock, monkeypatch):
    def boom(g, only_source=None):
        raise RuntimeError("database down")
    monkeypatch.setattr(webapp, "find_demo_case", boom)
    r = route["client"].post("/demo")
    assert r.status_code == 302 and "try=PR001" in r.headers["Location"]
    assert route["decisions"][0][:2] == ("C001", 45000)


def test_get_demo_never_searches_or_decides(route, clock):
    r = route["client"].get("/demo")
    assert r.status_code == 302
    assert route["finds"] == 0 and route["decisions"] == []
