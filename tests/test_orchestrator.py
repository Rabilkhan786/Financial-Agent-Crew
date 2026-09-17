"""Tests for the orchestrator review and loop-back routes."""

from src.agents import orchestrator


def crew_state(count=0, cap=1):
    return {
        "report": "## Executive summary\nSteady business.",
        "revision_count": count,
        "max_revisions": cap,
        "fundamentals": {
            "interpretation": "Margins are stable.",
            "red_flags": [],
        },
        "research": {"summary": "Recent news is mixed."},
    }


def test_review_can_loop_back_to_market_researcher(monkeypatch):
    monkeypatch.setattr(
        orchestrator.llm,
        "ask_structured",
        lambda *args, **kwargs: orchestrator.ReviewDecision(
            needs_revision=True,
            target="market_researcher",
            reason="Market context conflicts with the report.",
        ),
    )

    result = orchestrator.review(crew_state())

    assert result["revision_target"] == "market_researcher"
    assert result["revision_count"] == 1
    assert orchestrator.route_after_review(result) == "market_researcher"


def test_review_can_loop_back_to_fundamentals(monkeypatch):
    monkeypatch.setattr(
        orchestrator.llm,
        "ask_structured",
        lambda *args, **kwargs: orchestrator.ReviewDecision(
            needs_revision=True,
            target="fundamentals_analyst",
            reason="A financial risk was missed.",
        ),
    )

    result = orchestrator.review(crew_state())
    assert result["revision_target"] == "fundamentals_analyst"


def test_review_accepts_when_no_revision_is_needed(monkeypatch):
    monkeypatch.setattr(
        orchestrator.llm,
        "ask_structured",
        lambda *args, **kwargs: orchestrator.ReviewDecision(
            needs_revision=False
        ),
    )

    result = orchestrator.review(crew_state())
    assert result["revision_target"] == ""
    assert orchestrator.route_after_review(result) == "accept"


def test_revision_limit_stops_the_loop(monkeypatch):
    def should_not_call_model(*args, **kwargs):
        raise AssertionError("model should not run after the revision limit")

    monkeypatch.setattr(orchestrator.llm, "ask_structured", should_not_call_model)
    result = orchestrator.review(crew_state(count=1, cap=1))
    assert result["revision_target"] == ""


def test_intake_routes():
    assert orchestrator.route_after_intake({"ticker_valid": True}) == "continue"
    assert orchestrator.route_after_intake({"ticker_valid": False}) == "stop"
