"""Tests for the reviewer: what it sends back, and when it stops.

This is the only place in the project where an agent can send work backwards, so
the routing and the cap are the two things most worth pinning down. Both were
checked by hand while building; these tests mean a future edit cannot quietly
break them.

The model is stubbed out. These are tests of the decision logic, not of Groq.
"""

import pytest

from src.agents import orchestrator


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch):
    """Fail loudly if a test reaches the network.

    Any test that wants the model to answer overrides this itself, so an
    accidental live call shows up as an error rather than a slow test.
    """
    def refuse(*args, **kwargs):
        raise AssertionError("the reviewer called the model when it should not have")

    monkeypatch.setattr(orchestrator.llm, "ask_structured", refuse)


def crew(report="", flags=None, count=0, cap=2, **extra):
    """A crew state holding only what the reviewer reads."""
    base = {
        "ticker": "TEST",
        "report": report,
        "revision_count": count,
        "max_revisions": cap,
        "conflicts": [],
        "fundamentals": {"red_flags": flags or [], "metrics": {}},
        "research": {"articles": []},
        "analysis": {},
    }
    base.update(extra)
    return base


def flag(code="margin_erosion", message="The operating margin fell from 28.2% to 20.7%."):
    return {"code": code, "severity": "medium", "message": message}


# --- The three routes -------------------------------------------------------

def test_route_returns_only_three_answers():
    assert orchestrator.route({"revision_target": "fundamentals_analyst"}) == "fundamentals_analyst"
    assert orchestrator.route({"revision_target": "market_researcher"}) == "market_researcher"
    assert orchestrator.route({"revision_target": ""}) == "accept"


def test_an_unknown_target_falls_through_to_accept():
    # A stray value must never route somewhere the graph has no edge for.
    assert orchestrator.route({"revision_target": "report_writer"}) == "accept"
    assert orchestrator.route({}) == "accept"


# --- The cap ----------------------------------------------------------------

def test_at_the_cap_the_report_is_accepted():
    # The autouse fixture makes this fail if the model is consulted, which is
    # the point: at the cap the reviewer must not even ask.
    state = crew(report="## Executive summary\nAll fine.", flags=[flag()], count=2, cap=2)
    result = orchestrator.review(state)
    assert result["revision_target"] == ""
    assert orchestrator.route({**state, **result}) == "accept"


def test_past_the_cap_is_also_accepted():
    state = crew(report="x", flags=[flag()], count=5, cap=2)
    assert orchestrator.review(state)["revision_target"] == ""


def test_the_cap_is_checked_before_anything_else():
    # A report with both a dropped flag and an invented number still gets
    # accepted at the cap. Nothing outranks the cap.
    state = crew(report="## Summary\nProfit rose 34-45%.", flags=[flag()], count=2, cap=2)
    assert orchestrator.review(state)["revision_target"] == ""


def test_the_cap_comes_from_the_state_not_a_constant():
    state = crew(report="x", flags=[flag()], count=1, cap=1)
    assert orchestrator.review(state)["revision_target"] == ""


def test_a_second_revision_is_granted_before_the_cap():
    # One revision already used (count=1), cap=2: one more is still allowed.
    # This is the count going 1 -> 2, distinct from the cap-reached case above
    # where it is already at the cap and must not move at all.
    state = crew(report="## Executive summary\nAll fine.", flags=[flag()], count=1, cap=2)
    result = orchestrator.review(state)
    assert result["revision_target"] == "fundamentals_analyst"
    assert result["revision_count"] == 2


# --- Red flags the report failed to mention ---------------------------------

def test_a_dropped_red_flag_is_sent_back():
    state = crew(report="## Executive summary\nThe company is doing very well.",
                 flags=[flag()])
    result = orchestrator.review(state)
    assert result["revision_target"] == "fundamentals_analyst"
    assert result["revision_count"] == 1
    assert "margin" in result["revision_reason"].lower()


def test_a_flag_that_is_discussed_is_not_sent_back(monkeypatch):
    monkeypatch.setattr(orchestrator.llm, "ask_structured", lambda *a, **k: orchestrator.ReviewDecision(conflict=False))
    state = crew(report="## Profitability\nThe operating margin fell sharply.",
                 flags=[flag()])
    assert orchestrator.review(state)["revision_target"] == ""


def test_flags_not_mentioned_matches_on_the_subject_word():
    state = crew(report="Debt is high.", flags=[flag("high_leverage", "Debt to equity is 9.98.")])
    assert orchestrator.flags_not_mentioned(state) == []


def test_flags_not_mentioned_on_an_empty_report_finds_nothing():
    # Nothing to judge yet, so this must not fire before a report exists.
    assert orchestrator.flags_not_mentioned(crew(report="", flags=[flag()])) == []


def test_every_red_flag_code_has_a_keyword():
    # A new rule in ratios.py without a keyword here would silently stop being
    # checked, so the two lists are compared directly.
    from src.tools import ratios
    import pandas as pd

    table = pd.DataFrame({
        "revenue": [1000.0, 900.0], "operating_income": [200.0, 50.0],
        "net_income": [150.0, -10.0], "ebit": [200.0, 50.0],
        "interest_expense": [20.0, 300.0], "operating_cash_flow": [180.0, -20.0],
        "capex": [50.0, 400.0], "total_debt": [300.0, 5000.0],
        "total_equity": [600.0, -100.0], "total_assets": [1100.0, 1000.0],
        "current_liabilities": [200.0, 900.0],
    }, index=[2023, 2024])

    report = crew(report="")
    report["fundamentals"]["red_flags"] = ratios.red_flags(table)
    assert report["fundamentals"]["red_flags"], "the fixture should trigger several rules"
    # With an empty report nothing is matched, but with a report mentioning none
    # of the subjects every flag must come back as missed.
    report["report"] = "## Executive summary\nNothing to report."
    missed = orchestrator.flags_not_mentioned(report)
    assert len(missed) == len(report["fundamentals"]["red_flags"])


# --- Invented numbers -------------------------------------------------------

def test_an_invented_number_is_sent_back():
    state = crew(report="## Executive summary\nProfit rose 34-45% this year.",
                 research={"articles": [{"title": "profit rose 34%", "summary": ""}]})
    result = orchestrator.review(state)
    assert result["revision_target"] == "fundamentals_analyst"
    assert "45" in result["revision_reason"]
    assert result["revision_count"] == 1


def test_a_sourced_number_is_not_sent_back(monkeypatch):
    monkeypatch.setattr(orchestrator.llm, "ask_structured", lambda *a, **k: orchestrator.ReviewDecision(conflict=False))
    state = crew(report="## Executive summary\nProfit rose 34% this year.",
                 research={"articles": [{"title": "profit rose 34%", "summary": ""}]})
    assert orchestrator.review(state)["revision_target"] == ""


def test_a_dropped_flag_is_reported_before_an_invented_number():
    # Both are wrong, but the flag check runs first and its reason is the one
    # the writer is given.
    state = crew(report="## Executive summary\nProfit rose 34-45%.", flags=[flag()])
    assert "flagged issues" in orchestrator.review(state)["revision_reason"]


# --- What the model is allowed to decide ------------------------------------

def test_the_model_can_send_work_back(monkeypatch):
    monkeypatch.setattr(orchestrator.llm, "ask_structured", lambda *a, **k: orchestrator.ReviewDecision(
        conflict=True, target="market_researcher", reason="the mood does not match"))
    result = orchestrator.review(crew(report="## Executive summary\nSteady."))
    assert result["revision_target"] == "market_researcher"
    assert result["revision_count"] == 1


def test_a_target_the_graph_cannot_route_to_is_ignored(monkeypatch):
    # The graph has edges to two agents only. Anything else must be accepted
    # rather than routed into a node that does not exist.
    monkeypatch.setattr(orchestrator.llm, "ask_structured", lambda *a, **k: orchestrator.ReviewDecision(
        conflict=True, target="report_writer", reason="rewrite it"))
    assert orchestrator.review(crew(report="## Executive summary\nSteady."))["revision_target"] == ""


def test_an_unparsable_model_reply_accepts_rather_than_looping(monkeypatch):
    monkeypatch.setattr(orchestrator.llm, "ask_structured", lambda *a, **k: None)
    assert orchestrator.review(crew(report="## Executive summary\nSteady."))["revision_target"] == ""


def test_a_conflict_with_no_target_is_ignored(monkeypatch):
    monkeypatch.setattr(orchestrator.llm, "ask_structured", lambda *a, **k: orchestrator.ReviewDecision(
        conflict=True, target="", reason="something"))
    assert orchestrator.review(crew(report="## Executive summary\nSteady."))["revision_target"] == ""


# --- Every path writes to the conversation log ------------------------------

def test_every_decision_is_logged(monkeypatch):
    monkeypatch.setattr(orchestrator.llm, "ask_structured", lambda *a, **k: orchestrator.ReviewDecision(conflict=False))
    for state in (crew(report="x", flags=[flag()], count=2, cap=2),
                  crew(report="## Summary\nAll well.", flags=[flag()]),
                  crew(report="## Summary\nSteady.")):
        result = orchestrator.review(state)
        assert result["conversation_log"], "the reader must be able to see why"
        assert result["conversation_log"][0]["agent"] == "orchestrator_review"


# --- The model answering in the wrong type ----------------------------------

def test_a_string_true_counts_as_a_conflict(monkeypatch):
    """Some models answer "true" rather than true, and the provider rejects the
    call if the schema insists on a boolean. Both forms must work."""
    monkeypatch.setattr(orchestrator.llm, "ask_structured", lambda *a, **k:
                        orchestrator.ReviewDecision(conflict="true",
                                                    target="market_researcher",
                                                    reason="mismatch"))
    assert orchestrator.review(crew(report="## S\nSteady."))["revision_target"] == "market_researcher"


def test_a_string_false_is_not_a_conflict(monkeypatch):
    monkeypatch.setattr(orchestrator.llm, "ask_structured", lambda *a, **k:
                        orchestrator.ReviewDecision(conflict="false", target="", reason=""))
    assert orchestrator.review(crew(report="## S\nSteady."))["revision_target"] == ""


# --- Routing after intake: does an invalid ticker stop the crew? ------------

def test_route_after_intake_continues_for_a_confirmed_ticker():
    assert orchestrator.route_after_intake({"ticker_valid": True}) == "continue"


def test_route_after_intake_defaults_to_continue_when_unset():
    # new_state() always sets this, but the routing function itself should not
    # assume that and quietly stop a run just because the key is missing.
    assert orchestrator.route_after_intake({}) == "continue"


def test_route_after_intake_stops_for_an_unconfirmed_ticker():
    assert orchestrator.route_after_intake({"ticker_valid": False}) == "invalid_ticker"
