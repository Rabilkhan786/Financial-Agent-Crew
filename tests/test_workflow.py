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


class FakeAnalyst:
    """Returns a scripted list of contradictions per cross_check call."""

    def __init__(self, sequence):
        # sequence is a list of "contradiction lists", one per expected pass.
        self._sequence = list(sequence)
        self.cross_check_calls = 0
        self.last_write_args = None

    def cross_check(self, financial, news, risk, peer_comparison=None, target_ticker=None):
        self.cross_check_calls += 1
        return self._sequence.pop(0) if self._sequence else []

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


def _panel(analyst, failing=None):
    return Panel(
        manager=FakeManager(),
        financial=FailingSpecialist() if failing == "financial" else FakeSpecialist(),
        news=FakeSpecialist(),
        risk=FakeSpecialist(),
        analyst=analyst,
    )


def test_clean_run_writes_report_without_looping():
    analyst = FakeAnalyst(sequence=[[]])  # no contradictions on the first pass
    graph = build_workflow(_panel(analyst))
    state = graph.invoke({"question": "Is Acme a good investment?"})

    assert isinstance(state["report"], Report)
    assert state["report"].contradictions_resolved == 0
    assert analyst.cross_check_calls == 1  # analyst ran once, no loop


def test_caught_contradiction_fires_one_followup():
    # Pass 1 finds a contradiction; pass 2 (after re-asking News) finds none.
    analyst = FakeAnalyst(sequence=[[_news_contradiction()], []])
    panel = _panel(analyst)
    graph = build_workflow(panel)
    state = graph.invoke({"question": "Is Acme a good investment?"})

    report = state["report"]
    assert report.contradictions_resolved == 1  # exactly one follow-up round ran
    assert len(report.contradictions_found) == 1
    assert report.contradictions_found[0].follow_up_target == "news"
    # News ran twice (initial fan-out + the one follow-up); analyst ran twice.
    assert panel.news.calls == 2
    assert analyst.cross_check_calls == 2


def test_loop_stops_at_round_limit_when_contradiction_persists():
    # Analyst always finds a contradiction; the loop must still terminate.
    always = [[_news_contradiction()] for _ in range(10)]
    analyst = FakeAnalyst(sequence=always)
    graph = build_workflow(_panel(analyst))
    state = graph.invoke({"question": "Is Acme a good investment?"})

    assert state["report"].contradictions_resolved == config.MAX_FOLLOWUP_ROUNDS
    # Analyst runs once initially, then once after each follow-up round.
    assert analyst.cross_check_calls == config.MAX_FOLLOWUP_ROUNDS + 1


def test_failing_specialist_degrades_gracefully():
    analyst = FakeAnalyst(sequence=[[]])
    graph = build_workflow(_panel(analyst, failing="financial"))
    state = graph.invoke({"question": "Is Acme a good investment?"})

    # The run still finishes with a report, and the failure is recorded.
    assert isinstance(state["report"], Report)
    assert any("financial" in e for e in state.get("errors", []))
