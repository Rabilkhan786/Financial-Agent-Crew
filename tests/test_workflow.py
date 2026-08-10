"""Tests for the LangGraph workflow — fake agents, no network, no LLM.

These prove the wiring itself: the analyst's follow-up loop fires when a
contradiction is found, it stops at the configured round limit, and one failing
specialist doesn't sink the whole run.
"""

from investpanel import config
from investpanel.graph.workflow import Panel, build_workflow
from investpanel.models.contradiction import Contradiction
from investpanel.models.report import Report
from investpanel.models.scope import ResearchScope


class FakeManager:
    def plan(self, question):
        return ResearchScope(company="Acme", ticker="ACME", competitors=["RIVL"])

    def company_description(self, ticker):
        return "Acme makes widgets."


class FakeSpecialist:
    """Stands in for Financial / News / Risk. Records how often it ran."""

    def __init__(self):
        self.calls = 0

    def analyze(self, *args, **kwargs):
        self.calls += 1
        return []

    def peer_metric_table(self, tickers):
        return {}

    def price_series(self, ticker):
        return [100.0, 101.0, 99.0]


class FailingSpecialist(FakeSpecialist):
    def analyze(self, *args, **kwargs):
        raise RuntimeError("boom")


class FakeCritic:
    """Returns a scripted list of contradictions per review call.

    The Critic — not the Analyst — drives the follow-up loop, so this is what the
    loop tests script.
    """

    def __init__(self, sequence):
        # sequence is a list of "contradiction lists", one per expected pass.
        self._sequence = list(sequence)
        self.review_calls = 0

    def review(self, financial, news, risk, peer_comparison=None, target_ticker=None):
        self.review_calls += 1
        contradictions = self._sequence.pop(0) if self._sequence else []
        return contradictions, []


class FakeAnalyst:
    """Only synthesizes now — the cross-check moved to the Critic."""

    def __init__(self):
        self.last_write_args = None

    def write_report(self, **kwargs):
        self.last_write_args = kwargs
        return Report(
            company=kwargs["company"],
            company_description=kwargs["company_description"],
            summary="summary",
            contradictions_found=kwargs["contradictions"],
            contradictions_resolved=kwargs["contradictions_resolved"],
        )


def _news_contradiction():
    return Contradiction(
        between=("risk", "news"),
        description="Elevated volatility with no explaining news.",
        follow_up_target="news",
        follow_up_question="Explain the volatility.",
    )


class FakeQueryAnalyzer:
    """Returns a fixed plan, so a test can pin which specialists should run."""

    def __init__(self, plan):
        self._plan = plan

    def plan_query(self, question):
        return self._plan


def _panel(critic=None, failing=None, query_analyzer=None, analyst=None):
    return Panel(
        manager=FakeManager(),
        financial=FailingSpecialist() if failing == "financial" else FakeSpecialist(),
        news=FakeSpecialist(),
        risk=FakeSpecialist(),
        analyst=analyst or FakeAnalyst(),
        query_analyzer=query_analyzer,
        critic=critic if critic is not None else FakeCritic(sequence=[[]]),
    )


def test_clean_run_writes_report_without_looping():
    critic = FakeCritic(sequence=[[]])  # no contradictions on the first pass
    graph = build_workflow(_panel(critic))
    state = graph.invoke({"question": "Is Acme a good investment?"})

    assert isinstance(state["report"], Report)
    assert state["report"].contradictions_resolved == 0
    assert critic.review_calls == 1  # critic ran once, no loop


def test_caught_contradiction_fires_one_followup():
    # Pass 1 finds a contradiction; pass 2 (after re-asking News) finds none.
    critic = FakeCritic(sequence=[[_news_contradiction()], []])
    panel = _panel(critic)
    graph = build_workflow(panel)
    state = graph.invoke({"question": "Is Acme a good investment?"})

    report = state["report"]
    assert report.contradictions_resolved == 1  # exactly one follow-up round ran
    assert len(report.contradictions_found) == 1
    assert report.contradictions_found[0].follow_up_target == "news"
    # News ran twice (initial fan-out + the one follow-up); the critic reviewed twice.
    assert panel.news.calls == 2
    assert critic.review_calls == 2


def test_loop_stops_at_round_limit_when_contradiction_persists():
    # The critic always finds a contradiction; the loop must still terminate.
    always = [[_news_contradiction()] for _ in range(10)]
    critic = FakeCritic(sequence=always)
    graph = build_workflow(_panel(critic))
    state = graph.invoke({"question": "Is Acme a good investment?"})

    assert state["report"].contradictions_resolved == config.MAX_FOLLOWUP_ROUNDS
    # Critic runs once initially, then once after each follow-up round.
    assert critic.review_calls == config.MAX_FOLLOWUP_ROUNDS + 1


def test_risk_only_question_does_not_run_financial_or_news():
    # CHANGE 1: the whole point — a risk question must not pay for FMP and Tavily.
    from investpanel.models.query_plan import QueryPlan

    panel = _panel(query_analyzer=FakeQueryAnalyzer(QueryPlan.for_intent("risk_only")))
    graph = build_workflow(panel)
    state = graph.invoke({"question": "How volatile is Acme?"})

    assert panel.risk.calls == 1        # the one agent the question needed
    assert panel.financial.calls == 0   # skipped
    assert panel.news.calls == 0        # skipped
    assert isinstance(state["report"], Report)


def test_quick_fact_runs_financial_only():
    from investpanel.models.query_plan import QueryPlan

    panel = _panel(query_analyzer=FakeQueryAnalyzer(QueryPlan.for_intent("quick_fact")))
    build_workflow(panel).invoke({"question": "What is Acme's P/E?"})

    assert panel.financial.calls == 1
    assert panel.news.calls == 0
    assert panel.risk.calls == 0


def test_full_due_diligence_still_runs_all_three():
    from investpanel.models.query_plan import QueryPlan

    panel = _panel(query_analyzer=FakeQueryAnalyzer(QueryPlan.for_intent("full_due_diligence")))
    build_workflow(panel).invoke({"question": "Is Acme a good investment?"})

    assert panel.financial.calls == 1
    assert panel.news.calls == 1
    assert panel.risk.calls == 1


def test_failing_specialist_degrades_gracefully():
    graph = build_workflow(_panel(failing="financial"))
    state = graph.invoke({"question": "Is Acme a good investment?"})

    # The run still finishes with a report, and the failure is recorded.
    assert isinstance(state["report"], Report)
    assert any("financial" in e for e in state.get("errors", []))
