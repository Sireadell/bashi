"""Tests for safe ids, what-if copies, keepalive repair, write limits and overdue promises."""
import threading
import time

import pytest

import agent
import app as webapp
import keepalive
import verify
import whatif
from db import get_db
from rules import allocate_id, decide, mark_overdue_promises, prune_decisions

PROMISE = ("MATCH (c:Customer {id:'C003'}) CREATE (c)-[:PROMISED]->"
           "(:Promise {id:$id, date:'2026-10-01', due:$due, amount:5000, kept:$kept})")


def in_threads(n, fn):
    out, errs = [], []

    def run():
        try:
            out.append(fn())
        except Exception as e:  # collected so the test can fail with the cause
            errs.append(e)
    ts = [threading.Thread(target=run) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not errs, errs
    return out


# ---------------------------------------------------------------- 1 ids

def test_parallel_decisions_get_unique_ids_and_one_evidence_set(graph):
    results = in_threads(6, lambda: decide("C003", 10000, graph=graph))
    ids = [r["decision_id"] for r in results]
    assert len(set(ids)) == 6 and all(i and len(i) == 5 for i in ids)
    for r in results:
        n = graph.query("MATCH (:Decision {id:$d})-[:USED_EVIDENCE]->(e) RETURN count(e)",
                        {"d": r["decision_id"]}).result_set[0][0]
        assert n == len(r["evidence"])
    assert graph.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0] == 6


def test_parallel_promise_ids_are_unique(graph):
    ids = in_threads(6, lambda: agent.record_promise(graph, "C003", 5000, "2026-12-01"))
    assert len(set(ids)) == 6
    assert min(ids) > "PR007"


def test_ids_continue_on_a_graph_with_no_counter(graph):
    graph.query("MATCH (k:Counter) DELETE k")
    assert decide("C003", 10000, graph=graph)["decision_id"] == "D0001"
    graph.query("MATCH (k:Counter) DELETE k")
    assert decide("C003", 10000, graph=graph)["decision_id"] == "D0002"
    graph.query("MATCH (k:Counter) DELETE k")
    assert allocate_id(graph, "promise") == "PR008"


# ---------------------------------------------------------------- 2 what-if copies

def test_two_whatifs_on_one_decision_do_not_collide(graph, monkeypatch):
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": graph)
    did = decide("C001", 45000, graph=graph)["decision_id"]
    res = in_threads(2, lambda: whatif.whatif(did, ["PR001"]))
    assert all(r["original_verdict"] == "NO" and r["new_verdict"] == "YES" for r in res)
    left = [n for n in get_db().list_graphs() if n.startswith("shop_a_whatif_%s_" % did)]
    assert left == []


def test_stale_whatif_copies_are_swept(graph):
    db = get_db()
    old = "shop_a_whatif_D9999_%d_aaaaaa" % (int(time.time()) - 3600)
    fresh = "shop_a_whatif_D9998_%d_bbbbbb" % int(time.time())
    graph.copy(old)
    graph.copy(fresh)
    try:
        whatif._sweep["at"] = 0.0
        removed = whatif.sweep_stale_copies(db)
        assert old in removed and fresh not in removed
        assert fresh in db.list_graphs()
    finally:
        for n in (old, fresh):
            try:
                db.select_graph(n).delete()
            except Exception:
                pass


# ---------------------------------------------------------------- 3 keepalive

def test_keepalive_rebuilds_a_lost_graph(monkeypatch):
    monkeypatch.delenv("BASHI_URL", raising=False)
    counts, seeded = [0, 25], []
    monkeypatch.setattr(keepalive, "keep_own_shop", lambda: None)
    monkeypatch.setattr(keepalive, "tiny_read", lambda: counts.pop(0))
    import startup
    monkeypatch.setattr(startup, "ensure_seeded", lambda: seeded.append(1))
    assert keepalive.once() == 0 and seeded == [1]


def test_keepalive_fails_when_repair_fails(monkeypatch):
    monkeypatch.delenv("BASHI_URL", raising=False)
    monkeypatch.setattr(keepalive, "keep_own_shop", lambda: None)
    monkeypatch.setattr(keepalive, "tiny_read", lambda: 0)
    import startup
    monkeypatch.setattr(startup, "ensure_seeded", lambda: True)
    assert keepalive.once() == 1


def test_keepalive_leaves_a_healthy_graph_alone(monkeypatch):
    monkeypatch.delenv("BASHI_URL", raising=False)
    monkeypatch.setattr(keepalive, "keep_own_shop", lambda: None)
    monkeypatch.setattr(keepalive, "tiny_read", lambda: 25)
    import startup
    monkeypatch.setattr(startup, "ensure_seeded", lambda: pytest.fail("must not reseed"))
    assert keepalive.once() == 0


# ---------------------------------------------------------------- 4 public writes

@pytest.fixture()
def client(graph, monkeypatch):
    monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": graph)
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": graph)
    webapp.reset_limits()
    yield webapp.app.test_client()
    webapp.reset_limits()


def count_decisions(g):
    return g.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0]


def test_demo_get_writes_nothing_and_post_does(client, graph):
    r = client.get("/demo")
    assert r.status_code == 302 and count_decisions(graph) == 0
    r = client.post("/demo")
    assert r.status_code == 302 and "/receipt/D" in r.headers["Location"]
    assert count_decisions(graph) == 1
    page = client.get("/").get_data(as_text=True)
    assert 'method="post" action="/demo"' in page


def test_writes_are_rate_limited_with_429(client, graph, monkeypatch):
    monkeypatch.setattr(webapp, "PER_IP_LIMIT", 3)
    assert [client.post("/demo").status_code for _ in range(3)] == [302, 302, 302]
    r = client.post("/demo")
    assert r.status_code == 429 and "Slow down" in r.get_data(as_text=True)
    assert client.post("/", data={"customer": "C001", "amount": "45000"}).status_code == 429
    r = client.post("/whatif/D0001", json={"remove": ["PR001"]})
    assert r.status_code == 429 and "error" in r.get_json()
    assert client.get("/").status_code == 200   # reading is never limited
    # another visitor is not affected
    other = client.post("/demo", headers={"X-Forwarded-For": "9.9.9.9"})
    assert other.status_code == 302


def test_site_wide_limit(client, monkeypatch):
    monkeypatch.setattr(webapp, "SITE_LIMIT", 2)
    codes = [client.post("/demo", headers={"X-Forwarded-For": "1.1.1.%d" % i}).status_code
             for i in range(3)]
    assert codes == [302, 302, 429]


def test_oldest_decisions_are_pruned_and_data_kept(graph):
    ids = [decide("C003", 10000, graph=graph)["decision_id"] for _ in range(5)]
    before = graph.query("MATCH (n) WHERE NOT n:Decision RETURN count(n)").result_set[0][0]
    assert prune_decisions(graph, keep=3) == 2
    left = [r[0] for r in graph.query("MATCH (d:Decision) RETURN d.id ORDER BY d.id").result_set]
    assert left == sorted(ids)[2:]
    after = graph.query("MATCH (n) WHERE NOT n:Decision RETURN count(n)").result_set[0][0]
    assert before == after
    assert prune_decisions(graph, keep=3) == 0


def test_tunde_journey_through_the_site(client, graph):
    r = client.post("/demo")
    receipt = r.headers["Location"]
    did = receipt.rsplit("/", 1)[1]
    page = client.get(receipt).get_data(as_text=True)
    assert "NO" in page and "PR001" in page
    res = client.post("/whatif/" + did, json={"remove": ["PR001"]}).get_json()
    assert res["original_verdict"] == "NO" and res["new_verdict"] == "YES" and res["changed"]


# ---------------------------------------------------------------- 5 overdue promises

def bdecide(graph, today):
    return decide("C003", 10000, graph=graph, today=today)


def test_promise_due_yesterday_flips_yes_to_no(graph):
    graph.query(PROMISE, {"id": "PRX1", "due": "2026-10-13", "kept": False})
    assert bdecide(graph, "2026-10-13")["verdict"] == "YES"   # due today is not late yet
    r = bdecide(graph, "2026-10-14")
    assert r["verdict"] == "NO" and r["broken_promises"] == ["PRX1"]
    assert "PRX1" in r["reason"]


def test_promise_due_next_week_does_not_break(graph):
    graph.query(PROMISE, {"id": "PRX2", "due": "2026-10-21", "kept": False})
    assert bdecide(graph, "2026-10-14")["verdict"] == "YES"
    assert bdecide(graph, "2026-10-22")["verdict"] == "NO"


def test_kept_promise_never_breaks(graph):
    graph.query(PROMISE, {"id": "PRX3", "due": "2026-09-01", "kept": True})
    assert bdecide(graph, "2026-10-14")["verdict"] == "YES"
    n = graph.query("MATCH ()-[b:BROKE]->(:Promise {id:'PRX3'}) RETURN count(b)").result_set[0][0]
    assert n == 0


def test_marking_is_idempotent_and_leaves_planted_promises(graph):
    graph.query(PROMISE, {"id": "PRX4", "due": "2026-10-01", "kept": False})
    q = "MATCH ()-[b:BROKE]->(p:Promise) RETURN count(b), count(DISTINCT p)"
    assert graph.query(q).result_set[0] == [3, 3]
    mark_overdue_promises(graph, "2026-10-14")
    mark_overdue_promises(graph, "2026-10-15")
    assert graph.query(q).result_set[0] == [4, 4]


def test_old_decisions_still_verify_after_a_promise_falls_overdue(graph, monkeypatch):
    graph.query(PROMISE, {"id": "PRX5", "due": "2026-10-13", "kept": False})
    early = bdecide(graph, "2026-10-12")
    late = bdecide(graph, "2026-10-14")
    assert early["verdict"] == "YES" and late["verdict"] == "NO"
    cols = ("MATCH (d:Decision) RETURN d.id, d.customer_id, d.request, d.verdict, "
            "d.fingerprint, d.snapshot ORDER BY d.id")
    for row in graph.query(cols).result_set:
        ok, problems = verify.verify_decision(graph, row)
        assert ok, problems
    # a what-if on the early decision reads the data as it stood then
    monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": graph)
    res = whatif.whatif(early["decision_id"], [])
    assert res["new_verdict"] == "YES" and not res["changed"]


def test_promise_reply_says_when_it_is_checked(graph, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = agent.ask("Tunde promised to pay N10,000 on Friday", graph=graph)
    due = graph.query("MATCH (p:Promise {id:$i}) RETURN p.due", {"i": r["promise_id"]}).result_set[0][0]
    assert ("will be checked on %s, and counts as broken if still unpaid then" % due) in r["reply"]
