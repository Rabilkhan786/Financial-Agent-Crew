"""Tests for the compiled graph's routing, not just the plain functions.

test_orchestrator.py checks route_after_intake() and route() as ordinary
functions. These tests check that the compiled LangGraph actually uses them:
that an invalid ticker really does skip the rest of the crew when run through
the real graph, not just in theory.

No network and no model calls: every agent is monkeypatched to either a fixed
response or to fail loudly if it should not have been called at all.
"""

import pytest

from src import graph as graph_module
from src import state
from src.agents import data_analyst, fundamentals_analyst, market_researcher, orchestrator, report_writer


def refuse(name):
    """A stand-in for an agent that must not run in this test."""
    def run(crew_state):
        raise AssertionError(f"{name} must not run on this path")
    return run


def test_an_invalid_ticker_never_reaches_the_rest_of_the_crew(monkeypatch):
    """The real bug this graph shape fixes: before the conditional edge existed,
    market_researcher, fundamentals_analyst, data_analyst and report_writer all
    ran anyway for a ticker Yahoo could not confirm, each making its own real
    network call that could only ever fail."""

    def fake_orchestrator_run(crew_state):
        return {"company": crew_state["ticker"], "ticker_valid": False,
                "conversation_log": [state.note("orchestrator", "not found")],
                "errors": ["Could not confirm NOTAREAL on Yahoo Finance."]}

    monkeypatch.setattr(orchestrator, "run", fake_orchestrator_run)
    monkeypatch.setattr(market_researcher, "run", refuse("market_researcher"))
    monkeypatch.setattr(fundamentals_analyst, "run", refuse("fundamentals_analyst"))
    monkeypatch.setattr(data_analyst, "run", refuse("data_analyst"))
    monkeypatch.setattr(report_writer, "run", refuse("report_writer"))

    result = graph_module.run_crew("NOTAREAL", "2023-01-01", "2024-01-01")

    assert result["report"] == ""
    assert result["errors"] == ["Could not confirm NOTAREAL on Yahoo Finance."]
    assert result["conversation_log"] == [{"agent": "orchestrator", "message": "not found"}]


def test_a_valid_ticker_does_reach_market_researcher(monkeypatch):
    """The other half of the same edge: a confirmed ticker must still flow
    through normally. Only market_researcher is faked here, and it deliberately
    stops the graph from going further by raising - if this test reaches that
    point without a network call, the routing worked."""

    def fake_orchestrator_run(crew_state):
        return {"company": "Real Co", "ticker_valid": True,
                "conversation_log": [state.note("orchestrator", "confirmed")]}

    class ReachedMarketResearcher(Exception):
        pass

    def fake_market_researcher_run(crew_state):
        raise ReachedMarketResearcher()

    monkeypatch.setattr(orchestrator, "run", fake_orchestrator_run)
    monkeypatch.setattr(market_researcher, "run", fake_market_researcher_run)

    with pytest.raises(ReachedMarketResearcher):
        graph_module.run_crew("REAL", "2023-01-01", "2024-01-01")
