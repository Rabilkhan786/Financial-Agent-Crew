"""Tests for the numeric-accuracy check — logic only, no network."""

from eval.numeric_accuracy import _as_float, baseline_numbers, within_tolerance


def test_within_tolerance_relative_and_floor():
    assert within_tolerance(35.0, 35.8) is True          # ~2% off -> within 15%
    assert within_tolerance(50.0, 35.8) is False         # far off
    assert within_tolerance(0.2, 0.0) is True            # near-zero uses abs floor
    assert within_tolerance(None, 10.0) is False         # missing -> wrong


def test_as_float_coerces_or_none():
    assert _as_float("6.4") == 6.4
    assert _as_float(6.4) == 6.4
    assert _as_float("n/a") is None
    assert _as_float(None) is None


def test_baseline_numbers_parses_fenced_json():
    class FakeReply:
        content = '```json\n{"revenue_growth": 6.4, "pe_ratio": 35.0}\n```'

    class FakeLLM:
        def invoke(self, prompt):
            return FakeReply()

    def fake_searcher(q, max_results=5):
        return {"results": [{"title": "x", "url": "https://e.com"}]}

    out = baseline_numbers("Apple", "AAPL", FakeLLM(), fake_searcher)
    assert out["revenue_growth"] == 6.4
    assert out["pe_ratio"] == 35.0
