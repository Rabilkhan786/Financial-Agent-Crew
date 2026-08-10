"""Tests for CHANGE 5: findings beyond the fixed 10-question checklist.

The checklist is a floor, not a ceiling — these detectors surface material things
no checklist question asks about. Every observation must cite evidence, and none
may fire on a company where nothing is actually wrong. All pure functions.
"""

from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding
from investpanel.utils.observations import (
    collect_observations,
    financial_observations,
    news_observations,
    risk_observations,
)


def _ff(metric, value, healthy=True, unit="ratio"):
    return FinancialFinding(metric=metric, value=value, unit=unit, period="2025",
                             source="FMP test", interpretation="x", healthy=healthy)


def _rf(metric, value):
    return RiskFinding(metric=metric, value=value,
                        computed_from="100-day close series, AV test", interpretation="x")


def _nf(headline, tag=None, relevance="high"):
    return NewsFinding(headline=headline, summary="what happened", source_url="https://e.com",
                        published_date="2026-08-01", relevance=relevance, checklist_question=tag)


# --- nothing fires on a clean company ------------------------------------------------

def test_a_healthy_company_produces_no_extra_findings():
    financial = [
        _ff("gross_margin", 0.45), _ff("operating_margin", 0.20), _ff("net_margin", 0.15),
        _ff("cash_conversion", 1.1), _ff("pe_ratio", 18.0), _ff("revenue_growth", 12.0),
        _ff("interest_coverage", 25.0),
    ]
    assert financial_observations(financial) == []


def test_no_findings_from_empty_input():
    assert collect_observations([], [], []) == []


# --- margin structure -----------------------------------------------------------------

def test_flags_margin_eaten_before_the_bottom_line():
    # Healthy 50% gross margin but only 2% survives -> costs are the story.
    financial = [_ff("gross_margin", 0.50), _ff("net_margin", 0.02)]
    found = financial_observations(financial)
    assert any("consumed before it reaches profit" in o.title for o in found)
    assert found[0].evidence  # never an unsourced opinion


def test_flags_an_operating_loss():
    found = financial_observations([_ff("operating_margin", -0.08, healthy=False)])
    assert any(o.severity == "concern" and "loss-making" in o.title for o in found)


# --- cash quality ------------------------------------------------------------------------

def test_flags_profit_that_is_not_becoming_cash():
    found = financial_observations([_ff("cash_conversion", 0.3, healthy=False)])
    assert len(found) == 1
    assert found[0].severity == "concern"       # far below -> concern
    assert "not converting into cash" in found[0].title


def test_mild_cash_shortfall_is_only_a_watch():
    found = financial_observations([_ff("cash_conversion", 0.7, healthy=False)])
    assert found[0].severity == "watch"


# --- valuation vs reality -------------------------------------------------------------------

def test_flags_growth_pricing_without_growth():
    financial = [_ff("pe_ratio", 60.0, healthy=False), _ff("revenue_growth", -4.0, healthy=False,
                                                            unit="percent_yoy")]
    found = financial_observations(financial)
    assert any("Priced for growth" in o.title for o in found)


def test_does_not_flag_a_high_multiple_when_growth_is_real():
    financial = [_ff("pe_ratio", 60.0, healthy=False), _ff("revenue_growth", 40.0, unit="percent_yoy")]
    assert not any("Priced for growth" in o.title for o in financial_observations(financial))


def test_flags_thin_interest_cover():
    found = financial_observations([_ff("interest_coverage", 1.2, healthy=False, unit="times")])
    assert any("thinly covered" in o.title for o in found)


# --- risk ----------------------------------------------------------------------------------------

def test_flags_a_drawdown_deeper_than_volatility_implies():
    found = risk_observations([_rf("annualized_volatility", 0.20), _rf("max_drawdown", 0.50)])
    assert len(found) == 1
    assert "deeper than day-to-day volatility" in found[0].title


def test_normal_drawdown_is_not_flagged():
    assert risk_observations([_rf("annualized_volatility", 0.40), _rf("max_drawdown", 0.20)]) == []


# --- news ------------------------------------------------------------------------------------------

def test_untagged_high_relevance_news_becomes_an_extra_finding():
    # Tagged items already answer Q7-Q9; only the untagged ones are "extra".
    found = news_observations([_nf("Something material", tag=None), _nf("Risk item", tag="risk")])
    assert len(found) == 1
    assert found[0].title == "Something material"
    assert found[0].evidence == ["https://e.com/"]


def test_low_relevance_news_is_ignored():
    assert news_observations([_nf("Minor thing", tag=None, relevance="low")]) == []


# --- ordering ------------------------------------------------------------------------------------------

def test_findings_are_ordered_worst_first():
    financial = [
        _ff("cash_conversion", 0.2, healthy=False),      # concern
        _ff("gross_margin", 0.50), _ff("net_margin", 0.02),  # watch
    ]
    severities = [o.severity for o in collect_observations(financial, [], [])]
    assert severities == sorted(severities, key=lambda s: {"concern": 0, "watch": 1, "info": 2}[s])
    assert severities[0] == "concern"


def test_observations_reach_the_report():
    from investpanel.agents.analyst import AnalystAgent

    financial = [_ff("cash_conversion", 0.2, healthy=False)]
    report = AnalystAgent().write_report(
        company="Acme", company_description="x", financial=financial, news=[], risk=[],
        contradictions=[], contradictions_resolved=0, peer_comparison={},
    )
    assert report.additional_findings
    assert report.additional_findings[0].severity == "concern"
