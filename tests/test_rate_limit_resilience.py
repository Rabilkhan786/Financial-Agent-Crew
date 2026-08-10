"""Tests for surviving free-tier rate limits.

A 429 on a free tier is normal traffic shaping, not a real failure, so the run has
to absorb it rather than hand the user an error. All mocked — no network.
"""

from investpanel.agents.analyst import _brief_findings, _brief_lines, _brief_news
from investpanel.graph.workflow import Panel, build_workflow
from investpanel.models.findings import FinancialFinding, NewsFinding
from investpanel.models.report import Report


def _ff(metric, value, healthy=True):
    return FinancialFinding(metric=metric, value=value, unit="ratio", period="2025",
                             source="FMP statements for ACME", interpretation="a long sentence "
                             "explaining the metric in words the prompt does not need",
                             healthy=healthy)


# --- prompt size --------------------------------------------------------------

def test_brief_findings_keeps_only_what_the_model_needs():
    line = _brief_findings([_ff("pe_ratio", 19.86)])
    # Human-formatted, so the model quotes "19.86×" rather than a bare float.
    assert line == "- P/E Ratio: 19.86× (healthy)"
    # The verbose fields must NOT be in the prompt: they cost tokens and add nothing.
    assert "FMP statements" not in line
    assert "long sentence" not in line


def test_brief_findings_formats_a_fraction_as_a_percentage():
    # Regression: a raw 0.3998 in the prompt produced "volatility of 0.3998" in the
    # takeaway. The model should see the same string a reader would.
    from investpanel.models.findings import RiskFinding

    line = _brief_findings([RiskFinding(metric="annualized_volatility", value=0.3998,
                                         computed_from="100-day close series", interpretation="x")])
    assert "40.0%" in line
    assert "0.3998" not in line


def test_brief_findings_marks_concerns():
    assert "(concern)" in _brief_findings([_ff("pe_ratio", 300.0, healthy=False)])


def test_brief_helpers_handle_empty_input():
    assert _brief_findings([]) == "- none"
    assert _brief_news([]) == "- none"
    assert _brief_lines([]) == "- none"


def test_brief_news_drops_the_summary_body():
    item = NewsFinding(headline="Something happened", summary="a very long article summary " * 20,
                        source_url="https://e.com", published_date="2026-08-01", relevance="high")
    line = _brief_news([item])
    assert line == "- Something happened (high)"


# --- the manager no longer kills the run ------------------------------------------

class _FakeSpecialist:
    def __init__(self):
        self.calls = 0

    def analyze(self, *args, **kwargs):
        self.calls += 1
        return []

    def peer_metric_table(self, tickers):
        return {}

    def price_series(self, ticker):
        return []


class _RateLimitedManager:
    """Stands in for a manager whose LLM call hits a 429."""

    def plan(self, question):
        raise RuntimeError("Error code: 429 - rate_limit_exceeded")

    def company_description(self, ticker):
        return ""


class _FakeCritic:
    def review(self, financial, news, risk, peer_comparison=None, target_ticker=None):
        return [], [], []


class _FakeAnalyst:
    def write_report(self, **kwargs):
        return Report(
            company=kwargs["company"],
            company_description=kwargs["company_description"] or "unavailable",
            summary="summary",
            contradictions_found=kwargs["contradictions"],
            contradictions_resolved=kwargs["contradictions_resolved"],
        )


def test_a_rate_limited_manager_still_produces_a_report():
    panel = Panel(
        manager=_RateLimitedManager(),
        financial=_FakeSpecialist(), news=_FakeSpecialist(), risk=_FakeSpecialist(),
        analyst=_FakeAnalyst(), critic=_FakeCritic(),
    )
    state = build_workflow(panel).invoke({"question": "Is Acme a good investment?"})

    # The run completes instead of surfacing an error to the user...
    assert isinstance(state["report"], Report)
    # ...and the reason the scope is thin is recorded, not hidden.
    assert any("manager" in e for e in state.get("errors", []))


def test_the_llm_factory_asks_for_patient_retries():
    from investpanel import config

    # A 429 usually clears in a few seconds, so the client must be willing to wait.
    assert config.LLM_MAX_RETRIES >= 3
