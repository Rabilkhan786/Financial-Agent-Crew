"""Tests for CHANGE 1: the Query Analyzer and dynamic agent dispatch.

Two things are pinned here: the intent -> agents mapping (pure logic), and the
graph actually skipping the specialists a question doesn't need. All mocked.
"""

from investpanel.agents.query_analyzer import QueryAnalyzerAgent
from investpanel.graph.routing import route_after_critic, route_after_manager
from investpanel.models.contradiction import Contradiction
from investpanel.models.query_plan import QueryPlan


class _FakeReply:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    def __init__(self, reply):
        self._reply = reply

    def invoke(self, prompt):
        return _FakeReply(self._reply)


class _BrokenLLM:
    def invoke(self, prompt):
        raise RuntimeError("rate limited")


# --- the intent -> agents table ------------------------------------------------

def test_full_due_diligence_runs_everything():
    plan = QueryPlan.for_intent("full_due_diligence")
    assert plan.required_agents() == ["financial", "news", "risk"]
    assert plan.needs_peers is True
    assert plan.skipped_agents() == []


def test_risk_only_skips_financial_and_news():
    plan = QueryPlan.for_intent("risk_only")
    assert plan.required_agents() == ["risk"]
    assert sorted(plan.skipped_agents()) == ["financial", "news"]


def test_quick_fact_runs_financial_alone():
    plan = QueryPlan.for_intent("quick_fact")
    assert plan.required_agents() == ["financial"]
    assert plan.needs_peers is False


def test_competitor_comparison_asks_for_peers():
    plan = QueryPlan.for_intent("competitor_comparison")
    assert plan.needs_peers is True
    assert "financial" in plan.required_agents()


def test_unknown_intent_falls_back_to_full_checklist():
    plan = QueryPlan.for_intent("something_invented")
    assert plan.intent == "full_due_diligence"
    assert plan.required_agents() == ["financial", "news", "risk"]


def test_default_plan_is_the_old_behaviour():
    # An empty plan must run everything, so existing callers are unaffected.
    assert QueryPlan().required_agents() == ["financial", "news", "risk"]


# --- the agent ---------------------------------------------------------------------

def test_analyzer_classifies_a_risk_question():
    llm = _FakeLLM('{"intent": "risk_only", "reasoning": "asks about volatility"}')
    plan = QueryAnalyzerAgent(llm=llm).plan_query("How volatile is Nvidia?")
    assert plan.intent == "risk_only"
    assert plan.required_agents() == ["risk"]


def test_analyzer_falls_back_to_everything_when_the_llm_fails():
    plan = QueryAnalyzerAgent(llm=_BrokenLLM()).plan_query("Is Apple a good investment?")
    assert plan.intent == "full_due_diligence"
    assert plan.required_agents() == ["financial", "news", "risk"]


def test_analyzer_ignores_a_made_up_intent():
    llm = _FakeLLM('{"intent": "vibes_check", "reasoning": "n/a"}')
    plan = QueryAnalyzerAgent(llm=llm).plan_query("Is Apple a good investment?")
    assert plan.intent == "full_due_diligence"


# --- routing ------------------------------------------------------------------------

def test_route_after_manager_dispatches_only_what_is_needed():
    state = {"query_plan": QueryPlan.for_intent("risk_only")}
    assert route_after_manager(state) == ["risk"]


def test_route_after_manager_defaults_to_all_three():
    assert route_after_manager({}) == ["financial", "news", "risk"]


def test_route_after_manager_never_returns_an_empty_dispatch():
    # A plan wanting nobody must still move the graph forward, not stall it.
    plan = QueryPlan(needs_financial=False, needs_news=False, needs_risk=False)
    assert route_after_manager({"query_plan": plan}) == ["critic"]


def test_followup_cannot_wake_a_skipped_specialist():
    # The Critic wants News, but this run deliberately skipped News -> go straight
    # to the Analyst instead of quietly undoing the routing decision.
    contradiction = Contradiction(
        between=("financial", "news"), description="d",
        follow_up_target="news", follow_up_question="q?",
    )
    state = {
        "contradictions": [contradiction],
        "rounds": 0,
        "query_plan": QueryPlan.for_intent("financial_health"),  # news not dispatched
    }
    assert route_after_critic(state) == "analyst"


def test_followup_still_works_for_a_dispatched_specialist():
    contradiction = Contradiction(
        between=("financial", "news"), description="d",
        follow_up_target="news", follow_up_question="q?",
    )
    state = {
        "contradictions": [contradiction],
        "rounds": 0,
        "query_plan": QueryPlan.for_intent("full_due_diligence"),
    }
    assert route_after_critic(state) == "news"
