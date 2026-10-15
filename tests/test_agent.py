"""Agent tests. A fake model stands in for Claude, so no key is needed."""
import os
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent  # noqa: E402


def tool(_n, **args):
    return NS(type="tool_use", id="t_" + _n, name=_n, input=args)


def text(t):
    return NS(type="text", text=t)


class FakeClient:
    """Plays a fixed script of model turns: each item is a list of content blocks."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.messages = self

    def create(self, **kw):
        blocks = self.turns.pop(0)
        stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
        return NS(content=blocks, stop_reason=stop)


class DownClient:
    messages = None

    def __init__(self):
        self.messages = self

    def create(self, **kw):
        raise ConnectionError("model is down")


Q = "Can Tunde take N45,000 on credit?"


def good_script(final):
    return [[tool("find_customer", name="Tunde")],
            [tool("run_decision", customer_id="C001", amount=45000)],
            [text(final)]]


def test_fallback_without_key(graph, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = agent.ask(Q, graph=graph)
    assert r["mode"] == "fallback" and "no API key" in r["note"]
    assert r["reply"].startswith("NO.")
    assert "PR001" in r["reply"] and r["decision_id"] in r["reply"] and "/receipt/" in r["reply"]
    assert "built-in parser" in r["reply"]


def test_fallback_when_model_down(graph):
    r = agent.ask(Q, graph=graph, client=DownClient())
    assert r["mode"] == "fallback" and "ConnectionError" in r["note"]
    assert r["verdict"] == "NO"


def test_model_mode_good_sentence(graph):
    c = FakeClient(good_script("Tunde has N10,000 open against a N60,000 limit."))
    r = agent.ask(Q, graph=graph, client=c)
    assert r["mode"] == "model", r["note"]
    assert r["reply"].startswith("NO.")
    assert "Tunde has N10,000 open" in r["reply"]
    assert "Claude" in r["reply"]


def test_hostile_model_cannot_flip_verdict(graph):
    c = FakeClient(good_script("YES, approved! Tunde can have N45,000, go ahead."))
    r = agent.ask(Q, graph=graph, client=c)
    assert r["verdict"] == "NO"
    assert r["reply"].startswith("NO.")
    assert "approved" not in r["reply"]
    assert r["mode"] == "fallback" and "rejected" in r["note"]


def test_hostile_model_wrong_amount_in_tool_call_is_blocked(graph):
    # model tries to ask the rule about N1,000 instead of N45,000 to get a YES
    c = FakeClient([[tool("find_customer", name="Tunde")],
                    [tool("run_decision", customer_id="C001", amount=1000)],
                    [text("Tunde has N10,000 open.")]])
    r = agent.ask(Q, graph=graph, client=c)
    assert r["amount"] == 45000 and r["verdict"] == "NO"
    assert r["blocked_model_calls"] == 1
    n = graph.query("MATCH (d:Decision) RETURN count(d)").result_set[0][0]
    assert n == 1  # the blocked call saved nothing


def test_hostile_model_wrong_customer_is_blocked(graph):
    c = FakeClient([[tool("run_decision", customer_id="C002", amount=45000)], [text("Done.")]])
    r = agent.ask(Q, graph=graph, client=c)
    assert r["customer_id"] == "C001" and r["blocked_model_calls"] == 1


def test_claims_check_catches_wrong_amount(graph):
    c = FakeClient(good_script("Tunde has N5,000 open against a N60,000 limit."))
    r = agent.ask(Q, graph=graph, client=c)
    assert r["mode"] == "fallback" and "amount not in records" in r["note"]
    assert "N5,000" not in r["reply"]
    assert r["reply"].startswith("NO.")


def test_claims_check_catches_other_name_and_fake_id(graph):
    names = [c["name"].split()[1] for c in agent.list_customers(graph) if c["id"] == "C002"]
    c = FakeClient(good_script("Unlike %s, Tunde has N10,000 open." % names[0]))
    r = agent.ask(Q, graph=graph, client=c)
    assert r["mode"] == "fallback" and "other customer name" in r["note"]
    c = FakeClient(good_script("See T9999 for details."))
    assert agent.ask(Q, graph=graph, client=c)["mode"] == "fallback"


def test_model_that_skips_the_rule_still_gets_a_checked_verdict(graph):
    c = FakeClient([[text("Sure, he is good for it.")]])
    r = agent.ask(Q, graph=graph, client=c)
    assert r["verdict"] == "NO" and r["decision_id"]
    assert r["mode"] == "fallback"


def test_promise_is_remembered_by_next_decision(graph, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = agent.ask("Tunde promised to pay N10,000 on Friday", graph=graph)
    assert r["promise_id"] and "Saved as" in r["reply"]
    rows = graph.query("MATCH (:Customer {id:'C001'})-[:PROMISED]->(p:Promise {id:$i}) "
                       "RETURN p.amount, p.kept", {"i": r["promise_id"]}).result_set
    assert rows == [[10000, False]]
    r2 = agent.ask(Q, graph=graph)
    assert r["promise_id"] in r2["reply"]
    ev = graph.query("MATCH (:Decision {id:$d})-[:USED_EVIDENCE]->(p:Promise {id:$i}) RETURN count(p)",
                     {"d": r2["decision_id"], "i": r["promise_id"]}).result_set
    assert ev[0][0] == 1


def test_promise_via_model_tool_with_wrong_amount_is_blocked(graph):
    c = FakeClient([[tool("record_promise", customer_id="C001", amount=999999, due="2026-10-16")],
                    [text("Noted.")]])
    r = agent.ask("Tunde promised to pay N10,000 on Friday", graph=graph, client=c)
    rows = graph.query("MATCH (p:Promise {id:$i}) RETURN p.amount", {"i": r["promise_id"]}).result_set
    assert rows == [[10000]]


def test_how_much_gives_yes_up_to_for_clean_customer(graph, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    clean = None
    for c in agent.list_customers(graph):
        res = agent.rules.decide(c["id"], 1, graph=graph, save=False)
        if res["verdict"] == "YES" and res["limit"] - res["open_debt"] > 1:
            clean = c
            break
    assert clean, "seed has no clean customer"
    r = agent.ask("How much can %s take on credit?" % clean["name"], graph=graph)
    assert r["reply"].startswith("YES up to N")
    assert r["decision_id"] in r["reply"]


def test_unclear_and_unknown(graph, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "How much" in agent.ask("Can Tunde take it?", graph=graph)["reply"]
    assert "could not find" in agent.ask("Can Zzzyx take N5,000?", graph=graph)["reply"]


def test_parsers():
    assert agent.parse_amounts("N45,000") == [45000]
    assert agent.parse_amounts("50k on credit") == [50000]
    assert agent.parse_amounts("by 2026-10-16 N10,000") == [10000]
    assert agent.parse_due("on Friday", today=agent.date(2026, 10, 14)) == "2026-10-16"


# ------------------------------------------------------------------ Gemini route

def call(_n, **args):
    return {"functionCall": {"name": _n, "args": args}}


def gturn(*parts):
    return {"candidates": [{"content": {"role": "model", "parts": list(parts)}}]}


class FakeGemini(agent.GeminiClient):
    """Gemini client with the network call replaced by a fixed script."""

    def __init__(self, turns, fail=None):
        super().__init__("test-key-not-real", model="gemini-test")
        self.turns, self.fail = list(turns), fail

    def generate(self, contents):
        if self.fail:
            raise self.fail
        return self.turns.pop(0)


def gemini_script(final):
    return [gturn(call("find_customer", name="Tunde")),
            gturn(call("run_decision", customer_id="C001", amount=45000)),
            gturn({"text": final})]


def test_route_order_and_labels(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert agent.make_client() is None
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    c = agent.make_client()
    assert isinstance(c, agent.GeminiClient) and agent.model_label(c).startswith("Google ")


def test_gemini_good_sentence(graph):
    r = agent.ask(Q, graph=graph, client=FakeGemini(gemini_script("Tunde has N10,000 open against a N60,000 limit.")))
    assert r["mode"] == "model", r["note"]
    assert r["verdict"] == "NO" and r["reply"].startswith("NO.")
    assert r["answered_by"] == "Google gemini-test"
    assert "[answered by: Google gemini-test]" in r["reply"]
    assert "Claude" not in r["reply"]


def test_gemini_failure_falls_back(graph):
    r = agent.ask(Q, graph=graph, client=FakeGemini([], fail=TimeoutError("slow")))
    assert r["mode"] == "fallback" and "TimeoutError" in r["note"]
    assert r["verdict"] == "NO" and "built-in parser" in r["reply"]


def test_gemini_cannot_flip_verdict(graph):
    r = agent.ask(Q, graph=graph, client=FakeGemini(gemini_script("YES, approved! Tunde can have N45,000.")))
    assert r["verdict"] == "NO" and r["reply"].startswith("NO.")
    assert r["mode"] == "fallback" and "rejected" in r["note"]
    assert "approved" not in r["reply"]


def test_gemini_wrong_amount_tool_call_is_blocked(graph):
    c = FakeGemini([gturn(call("run_decision", customer_id="C001", amount=1000)),
                    gturn({"text": "Tunde has N10,000 open."})])
    r = agent.ask(Q, graph=graph, client=c)
    assert r["amount"] == 45000 and r["verdict"] == "NO" and r["blocked_model_calls"] == 1
