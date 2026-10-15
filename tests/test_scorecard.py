"""Scorecard tests. Run on a private copy of the shop, so nothing live is touched."""
import scorecard


def test_questions_are_fixed_and_cover_everyone(graph):
    cust, qs1 = scorecard.make_questions(graph)
    _, qs2 = scorecard.make_questions(graph)
    assert qs1 == qs2
    assert len(qs1) == 40
    assert {c for c, _ in qs1} == set(cust)
    assert ("C001", 45000) in qs1


def test_scorecard_run_saves_nothing_and_finds_known_cases(graph):
    before = graph.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0]
    res = scorecard.run(graph)
    after = graph.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0]
    assert before == after
    assert res["questions"] == 40 and res["same"] + res["differ"] == 40
    tunde = next(r for r in res["rows"] if r["customer"] == "C001" and r["request"] == 45000)
    assert tunde["bashi"] == "NO" and tunde["balance_only"] == "YES" and "PR001" in tunde["why"]
    assert next(r for r in res["rows"] if r["customer"] == "C003")["bashi"] == "YES"
