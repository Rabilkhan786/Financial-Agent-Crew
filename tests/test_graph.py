"""Tests for the main LangGraph routes."""

import pytest

from src.agents import market_researcher, orchestrator
from src.core import graph


def test_invalid_ticker_stops_before_research(monkeypatch):
    def fake_orchestrator(state):
        return {
            "ticker_valid": False,
            "conversation_log": [
                {"agent": "orchestrator", "message": "invalid"}
            ],
            "errors": ["invalid ticker"],
        }

    def should_not_run(state):
        raise AssertionError("market researcher should not run")

    monkeypatch.setattr(orchestrator, "run", fake_orchestrator)
    monkeypatch.setattr(market_researcher, "run", should_not_run)

    snapshots = list(
        graph.stream_crew("BAD", "2023-01-01", "2024-01-01")
    )
    result = snapshots[-1]

    assert result["ticker_valid"] is False
    assert result["errors"] == ["invalid ticker"]


def test_valid_ticker_reaches_market_researcher(monkeypatch):
    class ReachedResearcher(Exception):
        pass

    def fake_orchestrator(state):
        return {
            "ticker_valid": True,
            "company": "Test Company",
            "conversation_log": [
                {"agent": "orchestrator", "message": "valid"}
            ],
        }

    def fake_researcher(state):
        raise ReachedResearcher()

    monkeypatch.setattr(orchestrator, "run", fake_orchestrator)
    monkeypatch.setattr(market_researcher, "run", fake_researcher)

    with pytest.raises(ReachedResearcher):
        list(graph.stream_crew("TEST", "2023-01-01", "2024-01-01"))
