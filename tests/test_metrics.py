"""Tests for the metrics module — the GATE 1 requirement.

Everything here uses hand-made fixtures with numbers we can compute by hand, so
the expected outputs are known. No network, no real LLM: the "judge" is a fake
function, satisfying the rule that no test makes a real API call.
"""

from eval.metrics import (
    QuestionResult,
    _parse_score,
    build_question_result,
    make_llm_judge,
    score_reasoning,
    summarize,
)


def test_score_reasoning_normalizes_1_to_5_into_0_to_1():
    # A judge that always says 5 should map to 1.0; always 1 maps to 0.0.
    always_5 = lambda q, a, r: 5
    always_1 = lambda q, a, r: 1
    always_3 = lambda q, a, r: 3
    assert score_reasoning("q", "a", "r", always_5) == 1.0
    assert score_reasoning("q", "a", "r", always_1) == 0.0
    assert score_reasoning("q", "a", "r", always_3) == 0.5


def test_score_reasoning_clamps_out_of_range_judge():
    # A misbehaving judge can't push the score outside 0-1.
    too_high = lambda q, a, r: 9
    too_low = lambda q, a, r: -4
    assert score_reasoning("q", "a", "r", too_high) == 1.0
    assert score_reasoning("q", "a", "r", too_low) == 0.0


def test_parse_score_picks_first_digit_and_fails_safe():
    assert _parse_score("4") == 4
    assert _parse_score("The score is 2 out of 5.") == 2
    # No 1-5 digit anywhere -> fails safe to the lowest score.
    assert _parse_score("no number here") == 1
    assert _parse_score("") == 1


def test_make_llm_judge_uses_the_rubric_and_parses_reply():
    # A fake "llm" that records the prompt and returns a canned reply object.
    class FakeReply:
        content = "I would grade this a 4."

    class FakeLLM:
        def __init__(self):
            self.last_prompt = None

        def invoke(self, prompt):
            self.last_prompt = prompt
            return FakeReply()

    llm = FakeLLM()
    judge = make_llm_judge(llm)
    score = judge("Is X a good buy?", "X looks strong.", "X is reasonable.")
    assert score == 4
    # The rubric and both texts must be present in what was sent to the model.
    assert "score from 1 to 5" in llm.last_prompt
    assert "Is X a good buy?" in llm.last_prompt
    assert "X is reasonable." in llm.last_prompt


def _make_results() -> list[QuestionResult]:
    """A fixture of 4 questions with numbers chosen so the aggregates are obvious."""
    return [
        # Labeled contradiction, caught it, sound reasoning, not confidently wrong.
        QuestionResult("q1", 1.0, True, True, True, False, cost_usd=0.02, latency_seconds=10.0),
        # Labeled contradiction, MISSED it, mediocre reasoning.
        QuestionResult("q2", 0.5, True, False, False, False, cost_usd=0.04, latency_seconds=20.0),
        # Not labeled, gave a firm view that contradicts the read -> confidently wrong.
        QuestionResult("q3", 0.0, False, False, True, True, cost_usd=0.06, latency_seconds=30.0),
        # Not labeled, cautious and fine.
        QuestionResult("q4", 0.5, False, False, False, False, cost_usd=0.00, latency_seconds=0.0),
    ]


def test_summarize_computes_known_aggregates():
    summary = summarize("InvestPanel", _make_results())

    assert summary.num_questions == 4
    # Mean reasoning quality: (1.0 + 0.5 + 0.0 + 0.5) / 4 = 0.5
    assert summary.mean_reasoning_quality == 0.5
    # Two labeled contradictions, one caught -> 0.5 catch rate.
    assert summary.num_labeled_contradictions == 2
    assert summary.num_contradictions_caught == 1
    assert summary.contradiction_catch_rate == 0.5
    # One of four is confidently wrong -> 0.25.
    assert summary.confidently_wrong_rate == 0.25
    # Mean cost: (0.02 + 0.04 + 0.06 + 0.0) / 4 = 0.03
    assert round(summary.mean_cost_usd, 6) == 0.03
    # Mean latency: (10 + 20 + 30 + 0) / 4 = 15.0
    assert summary.mean_latency_seconds == 15.0


def test_build_question_result_marks_lowest_score_as_contradicting_read():
    # Judge rates the reasoning at the floor (1) -> quality 0.0 -> contradicts read.
    poor_judge = lambda q, a, r: 1
    result = build_question_result(
        question_id="q1",
        question_text="Is X good?",
        reasonable_read="X is fine.",
        had_known_contradiction=False,
        conclusion="X is a screaming buy, no risks at all!",
        flagged_contradiction=False,
        firm_conclusion=True,
        judge=poor_judge,
    )
    assert result.reasoning_quality == 0.0
    assert result.contradicts_reasonable_read is True
    # Firm + contradicts -> this is exactly a "confidently wrong" case.
    assert result.gave_firm_conclusion is True


def test_build_question_result_good_score_does_not_contradict_read():
    good_judge = lambda q, a, r: 5
    result = build_question_result(
        question_id="q2",
        question_text="Is X good?",
        reasonable_read="X is fine.",
        had_known_contradiction=True,
        conclusion="Balanced, evidence-based view.",
        flagged_contradiction=True,
        firm_conclusion=False,
        judge=good_judge,
    )
    assert result.reasoning_quality == 1.0
    assert result.contradicts_reasonable_read is False
    assert result.caught_contradiction is True


def test_catch_rate_is_none_when_nothing_is_labeled():
    results = [QuestionResult("q1", 1.0, False, False, False, False)]
    summary = summarize("baseline", results)
    assert summary.contradiction_catch_rate is None
    # as_dict should carry the None through, not crash.
    assert summary.as_dict()["contradiction_catch_rate"] is None
