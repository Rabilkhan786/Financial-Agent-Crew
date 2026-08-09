"""Tests for the single-LLM baseline — fully mocked, no network.

We inject a fake searcher and a fake LLM, so the test proves the baseline wires
search -> prompt -> parse correctly without ever calling a real API.
"""

from eval.baselines.single_llm_search import BaselineAnswer, _parse_json, run_baseline
from eval.datasets.heldout_questions import HeldoutQuestion


def _question() -> HeldoutQuestion:
    return HeldoutQuestion(
        id="test-1",
        company="Acme",
        ticker="ACME",
        as_of="January 2025",
        question="Is Acme a reasonable investment?",
        knowable_context="Made-up context.",
        reasonable_read="Made-up reasonable read.",
    )


def test_parse_json_handles_plain_and_fenced_json():
    assert _parse_json('{"a": 1}') == {"a": 1}
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('```\n{"a": 2}\n```') == {"a": 2}


def test_run_baseline_wires_search_and_llm_without_network():
    # Fake searcher records its call and returns canned results.
    calls = {}

    def fake_searcher(query, max_results=5):
        calls["query"] = query
        calls["max_results"] = max_results
        return {"results": [{"title": "Acme news", "url": "https://example.com/acme"}]}

    # Fake LLM returns a canned JSON answer, wrapped in a code fence to prove we
    # tolerate that.
    class FakeReply:
        content = (
            "```json\n"
            '{"conclusion": "Balanced view.", "flagged_contradiction": true, '
            '"contradiction_note": "cheap but risky", "firm_conclusion": false, '
            '"sources": ["https://example.com/acme"]}\n'
            "```"
        )

    class FakeLLM:
        def invoke(self, prompt):
            calls["prompt"] = prompt
            return FakeReply()

    answer = run_baseline(_question(), llm=FakeLLM(), searcher=fake_searcher)

    assert isinstance(answer, BaselineAnswer)
    assert answer.question_id == "test-1"
    assert answer.flagged_contradiction is True
    assert answer.firm_conclusion is False
    assert answer.sources == ["https://example.com/acme"]
    # The company name reached the search query, and the results reached the prompt.
    assert "Acme" in calls["query"]
    assert "Acme news" in calls["prompt"]
