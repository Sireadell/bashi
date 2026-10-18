import tamper
import verify
from rules import decide

DECISION_COLS = ("MATCH (d:Decision) RETURN d.id, d.customer_id, d.request, d.verdict, "
                 "d.fingerprint, d.snapshot ORDER BY d.id")


def run_verify(g):
    return [(row[0],) + verify.verify_decision(g, row) for row in g.query(DECISION_COLS).result_set]


def test_tunde_is_no_because_of_pr001(graph):
    r = decide("C001", 45000, graph=graph)
    assert r["verdict"] == "NO"
    assert r["open_debt"] == 10000 and r["limit"] == 60000
    assert 10000 + 45000 <= 60000  # the limit rule alone would say YES
    assert r["broken_promises"] == ["PR001"]
    assert "PR001" in r["reason"]
    assert {"label": "Promise", "id": "PR001"} in r["evidence"]
    assert r["decision_id"] and len(r["fingerprint"]) == 64
    linked = graph.query("MATCH (:Decision {id:$d})-[:USED_EVIDENCE]->(e) RETURN count(e)",
                         {"d": r["decision_id"]}).result_set[0][0]
    assert linked == len(r["evidence"]) == 5
    rules = graph.query("MATCH (:Decision {id:$d})-[:APPLIED_RULE]->(r) RETURN r.id",
                        {"d": r["decision_id"]}).result_set
    assert {x[0] for x in rules} == {"R_LIMIT", "R_BROKEN_PROMISE", "R_FAMILY"}


def test_removing_pr001_flips_to_yes(graph):
    # Clearing the broken promise means the shop marks it kept; deleting only the
    # link would be undone, because an unkept promise past its due date counts as broken.
    graph.query("MATCH (:Customer {id:'C001'})-[b:BROKE]->(p:Promise {id:'PR001'}) DELETE b SET p.kept = true")
    r = decide("C001", 45000, graph=graph, save=False)
    assert r["verdict"] == "YES"
    assert r["broken_promises"] == []
    assert r["decision_id"] is None


def test_over_limit_is_no(graph):
    r = decide("C001", 55000, graph=graph, save=False)  # 10,000 + 55,000 > 60,000
    assert r["verdict"] == "NO"
    assert "above the limit" in r["reason"]


def test_clean_customer_gets_yes(graph):
    r = decide("C003", 10000, graph=graph)
    assert r["verdict"] == "YES" and r["open_debt"] == 0


def test_debt_follows_settles_without_double_counting(graph):
    # One payment split across two trades must count each part once.
    graph.query("CREATE (:Customer {id:'CX', credit_limit:100000})")
    for tid, amt in (("TX1", 10000), ("TX2", 20000)):
        graph.query("MATCH (c:Customer {id:'CX'}) CREATE (c)-[:MADE]->(:Trade {id:$i, amount:$a, date:'2026-01-01'})",
                    {"i": tid, "a": amt})
    graph.query("CREATE (:Payment {id:'PX', amount:20000, date:'2026-02-01'})")
    for tid, amt in (("TX1", 10000), ("TX2", 10000)):
        graph.query("MATCH (p:Payment {id:'PX'}), (t:Trade {id:$i}) CREATE (p)-[:SETTLES {amount:$a}]->(t)",
                    {"i": tid, "a": amt})
    r = decide("CX", 1000, graph=graph, save=False)
    assert r["open_debt"] == 10000
    ids = [e["id"] for e in r["evidence"]]
    assert len(ids) == len(set(ids))  # each record cited once


def test_phantom_debt_is_counted_and_flagged_not_hidden(graph):
    r = decide("C002", 5000, graph=graph, save=False)
    assert r["open_debt"] == 12000  # debt stays as recorded
    assert r["possible_phantoms"] == [{"trade": "T0004", "payment": "P0004", "amount": 12000}]


def test_untraceable_amount_is_refused(graph):
    # Payments add up to more than the trade: the debt number cannot be trusted.
    graph.query("MATCH (p:Payment {id:'P0001'})-[s:SETTLES]->(:Trade {id:'T0001'}) SET s.amount = 99999, p.amount = 99999")
    r = decide("C001", 45000, graph=graph)
    assert r["verdict"] == "CANNOT_TRACE"
    assert "cannot trace this amount" in r["reason"]
    assert r["open_debt"] is None and r["decision_id"] is None
    assert graph.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0] == 0


def test_missing_trade_amount_is_refused(graph):
    graph.query("MATCH (t:Trade {id:'T0002'}) REMOVE t.amount")
    assert decide("C001", 45000, graph=graph, save=False)["verdict"] == "CANNOT_TRACE"


def test_bad_request_is_refused(graph):
    assert decide("C001", -5, graph=graph, save=False)["verdict"] == "CANNOT_TRACE"


def test_verify_passes_on_untouched_graph(graph):
    decide("C001", 45000, graph=graph)
    decide("C003", 10000, graph=graph)
    results = run_verify(graph)
    assert len(results) == 2 and all(ok for _, ok, _ in results)


def test_tamper_makes_verify_fail_and_names_the_record(graph):
    decide("C001", 45000, graph=graph)
    old = tamper.tamper(graph, "T0002", 50000)
    assert old == 20000
    (did, ok, problems), = run_verify(graph)
    assert not ok
    assert any("Trade T0002 amount changed N20,000 -> N50,000" in p for p in problems)
    tamper.restore(graph)
    (did, ok, problems), = run_verify(graph)
    assert ok and problems == []


def test_tamper_that_flips_the_answer_is_caught_by_replay(graph):
    decide("C003", 10000, graph=graph)
    graph.query("MATCH (t:Trade {id:'T0005'}) SET t.amount = 500000")
    (did, ok, problems), = run_verify(graph)
    assert not ok
    assert any("Trade T0005 amount changed" in p for p in problems)
    assert any("Re-running the rule now gives NO" in p for p in problems)


def test_removing_broken_promise_link_is_caught(graph):
    decide("C001", 45000, graph=graph)
    graph.query("MATCH (:Customer {id:'C001'})-[b:BROKE]->(:Promise {id:'PR001'}) DELETE b")
    (did, ok, problems), = run_verify(graph)
    assert not ok
    assert any("Promise PR001 broke changed True -> False" in p for p in problems)


def test_editing_the_decision_itself_is_caught(graph):
    r = decide("C001", 45000, graph=graph)
    graph.query("MATCH (d:Decision {id:$d}) SET d.verdict='YES'", {"d": r["decision_id"]})
    (did, ok, problems), = run_verify(graph)
    assert not ok
    assert any("itself was edited" in p for p in problems)
