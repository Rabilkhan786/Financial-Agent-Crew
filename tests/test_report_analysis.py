"""Tests for the deterministic report-analysis layer: executive-summary category
classification, evidence quality, data freshness, the human checklist, peer table,
and tension/contradiction status — all pure functions, no LLM, no network."""

from datetime import date

from investpanel.models.contradiction import Contradiction
from investpanel.models.findings import FinancialFinding, NewsFinding, RiskFinding
from investpanel.models.report import Report
from investpanel.utils.report_analysis import (
    build_executive_summary,
    build_human_checklist,
    build_peer_table,
    classify_growth,
    classify_news,
    classify_risk,
    contradiction_status,
    crosscheck_conclusion,
    data_freshness,
    evidence_quality,
    peer_chart_data,
    peer_comparison_note,
    question_was_rewritten,
)


def _ff(metric, value, healthy, period="2025", unit="ratio"):
    return FinancialFinding(metric=metric, value=value, unit=unit, period=period,
                             source="FMP test", interpretation="x", healthy=healthy)


def _nf(headline, tag="risk", relevance="high", pdate="2026-08-01"):
    return NewsFinding(headline=headline, summary="s", source_url="https://e.com",
                        published_date=pdate, relevance=relevance, checklist_question=tag)


def _rf(metric, value, days=100):
    return RiskFinding(metric=metric, value=value, computed_from=f"{days}-day close series, AV test",
                        interpretation="x")


# --- executive summary classification ----------------------------------------

def test_classify_growth_positive_negative_mixed_insufficient():
    assert classify_growth([]) == "Insufficient evidence"
    assert classify_growth([_ff("revenue_growth", 10, True), _ff("profit_growth", 5, True)]) == "Positive"
    assert classify_growth([_ff("revenue_growth", -1, False), _ff("profit_growth", -1, False)]) == "Negative"
    assert classify_growth([_ff("revenue_growth", 10, True), _ff("profit_growth", -5, False)]) == "Mixed"


def test_classify_risk_uses_the_same_threshold_as_the_risk_agent():
    assert classify_risk([]) == "Insufficient evidence"
    assert classify_risk([_rf("annualized_volatility", 0.20)]) == "Moderate"
    assert classify_risk([_rf("annualized_volatility", 0.55)]) == "Elevated"
    assert classify_risk([_rf("max_drawdown", 0.40)]) == "Elevated"  # > CONCERNING_DRAWDOWN_THRESHOLD


def test_classify_news_from_tags_not_sentiment_guessing():
    assert classify_news([]) == "Insufficient evidence"
    assert classify_news([_nf("bad thing", tag="risk")]) == "Concerns flagged"
    assert classify_news([_nf("great moat", tag="moat")]) == "No major concerns flagged"
    assert classify_news([_nf("bad thing", tag="risk"), _nf("great moat", tag="moat")]) == "Mixed"


def test_build_executive_summary_has_all_six_categories():
    report = Report(company="Acme", company_description="x", summary="s",
                     financial_findings=[_ff("revenue_growth", 10, True)])
    summary = build_executive_summary(report)
    assert set(summary) == {"Fundamentals", "Growth", "Profitability", "Valuation", "Risk", "News"}


# --- evidence quality -----------------------------------------------------------

def test_evidence_quality_insufficient_when_nothing_available():
    report = Report(company="Acme", company_description="x", summary="s")
    q = evidence_quality(report)
    assert q["Financial"] == "Insufficient"
    assert q["News"] == "Insufficient"
    assert q["Risk"] == "Insufficient"
    assert q["Overall"] == "Insufficient"


def test_evidence_quality_high_when_well_covered():
    financial = [_ff(m, 1, True) for m in
                 ["revenue_growth", "profit_growth", "operating_cash_flow", "debt_to_equity",
                  "interest_coverage", "roce", "roe"]]
    news = [_nf(f"n{i}") for i in range(3)]
    risk = [_rf("annualized_volatility", 0.2, days=252), _rf("max_drawdown", 0.1, days=252)]
    report = Report(company="Acme", company_description="x", summary="s",
                     financial_findings=financial, news_findings=news, risk_findings=risk)
    q = evidence_quality(report)
    assert q["Financial"] == "High"
    assert q["News"] == "High"
    assert q["Risk"] == "High"
    assert q["Overall"] == "High"


def test_overall_quality_ignores_agents_that_were_never_requested():
    # A risk-only run that fully answered the risk question is not "Insufficient"
    # just because there is no news — nobody asked for news.
    report = Report(company="Acme", company_description="x", summary="s",
                     risk_findings=[_rf("annualized_volatility", 0.2, days=252)],
                     query_intent="risk_only", skipped_agents=["financial", "news"])
    quality = evidence_quality(report)
    assert quality["Risk"] == "High"
    assert quality["Overall"] == "High"


def test_overall_quality_still_drops_for_a_requested_agent_that_failed():
    report = Report(company="Acme", company_description="x", summary="s",
                     risk_findings=[_rf("annualized_volatility", 0.2, days=252)],
                     query_intent="full_due_diligence", skipped_agents=[])
    assert evidence_quality(report)["Overall"] == "Insufficient"


def test_evidence_quality_peer_unavailable_when_empty():
    report = Report(company="Acme", company_description="x", summary="s")
    assert evidence_quality(report)["Peer comparison"] == "Insufficient"


# --- data freshness ---------------------------------------------------------------

def test_data_freshness_reports_period_unavailable_when_missing():
    report = Report(company="Acme", company_description="x", summary="s")
    freshness = data_freshness(report)
    assert freshness["Financial data period"] == "Period unavailable"
    assert freshness["News coverage window"] == "Period unavailable"
    assert freshness["Price/risk analysis window"] == "Period unavailable"
    assert freshness["Research date"]  # auto-set, never blank


def test_data_freshness_uses_real_values_from_findings():
    report = Report(
        company="Acme", company_description="x", summary="s",
        financial_findings=[_ff("revenue_growth", 10, True, period="2025")],
        news_findings=[_nf("a", pdate=date(2026, 8, 1)), _nf("b", pdate=date(2026, 8, 5))],
        risk_findings=[_rf("annualized_volatility", 0.2, days=252)],
    )
    freshness = data_freshness(report)
    assert freshness["Financial data period"] == "2025"
    assert freshness["News coverage window"] == "2026-08-01 to 2026-08-05"
    assert freshness["Price/risk analysis window"] == "252 trading days of price history"


# --- human checklist ---------------------------------------------------------------

def test_human_checklist_marks_missing_metric_as_insufficient():
    report = Report(company="Acme", company_description="x", summary="s")
    rows = build_human_checklist(report)
    pe_row = next(r for r in rows if "P/E" in r["question"])
    assert pe_row["status"] == "Insufficient evidence"


def test_human_checklist_shows_formatted_value_for_present_metric():
    report = Report(company="Acme", company_description="x", summary="s",
                     financial_findings=[_ff("pe_ratio", 19.8571, True, period="TTM")])
    rows = build_human_checklist(report)
    pe_row = next(r for r in rows if "P/E" in r["question"])
    assert pe_row["result"] == "19.86×"
    assert pe_row["status"] == "Healthy"


# --- peer table ----------------------------------------------------------------

def test_build_peer_table_only_includes_available_metrics():
    table = build_peer_table({"revenue_growth": {"NKE": 0.19, "ADDYY": 3.0}, "empty_metric": {}})
    assert len(table) == 1
    assert table[0]["Metric"] == "Revenue Growth"
    assert "NKE" in table[0] and "ADDYY" in table[0]


def test_build_peer_table_empty_input_gives_empty_table():
    assert build_peer_table({}) == []


def test_peer_chart_data_needs_at_least_two_companies():
    # One company alone isn't a comparison — no chart for it.
    assert peer_chart_data({"revenue_growth": {"NKE": 0.19}}) == {}
    charts = peer_chart_data({"revenue_growth": {"NKE": 0.19, "ADDYY": 3.0}})
    assert charts == {"Revenue Growth": {"NKE": 0.19, "ADDYY": 3.0}}


def test_peer_chart_data_skips_metrics_that_dont_compare_well():
    # Operating cash flow tracks company size, so it isn't charted against peers.
    assert peer_chart_data({"operating_cash_flow": {"NKE": 2.8e9, "ADDYY": 1.0e9}}) == {}


# --- contradiction follow-up status ---------------------------------------------

def test_question_rewrite_is_shown_only_when_it_really_changed():
    messy = Report(company="BMW", company_description="x", summary="s",
                    question="bmw profit is how and is worth to invest it",
                    interpreted_question="How is BMW's profit, and is it worth investing in?")
    assert question_was_rewritten(messy) is True

    # Punctuation/casing only -> not worth showing as a "correction".
    cosmetic = Report(company="BMW", company_description="x", summary="s",
                       question="is bmw a good investment",
                       interpreted_question="Is BMW a good investment?")
    assert question_was_rewritten(cosmetic) is False


def test_question_rewrite_handles_missing_values():
    assert question_was_rewritten(
        Report(company="X", company_description="x", summary="s")
    ) is False


def test_crosscheck_refuses_to_claim_consistent_without_financial_data():
    # The BMW case: news + risk arrived but NO financial metrics. Finding no
    # contradiction here is meaningless — the report must not claim consistency.
    report = Report(company="BMW", company_description="x", summary="s",
                     news_findings=[_nf("bad news")],
                     risk_findings=[_rf("annualized_volatility", 0.1)])
    status, explanation = crosscheck_conclusion(report)
    assert status == "Cross-check not possible"
    assert "financial data" in explanation
    assert "NOT evidence that the findings agree" in explanation


def test_skipped_agent_reads_as_not_requested_not_as_a_failure():
    # CHANGE 1: News was never dispatched, so its rows must NOT claim we looked
    # and came up short — that would misrepresent a routing decision as a failure.
    report = Report(company="Acme", company_description="x", summary="s",
                     financial_findings=[_ff("revenue_growth", 10, True)],
                     query_intent="financial_health", skipped_agents=["news", "risk"])
    rows = {r["question"]: r for r in build_human_checklist(report)}
    moat = rows["Does it have a durable competitive advantage (moat)?"]
    assert moat["status"] == "Not requested"
    assert "does not need the news agent" in moat["missing_reason"]


def test_failed_agent_still_reads_as_insufficient_evidence():
    # Nothing was skipped: an empty section here really is a data failure.
    report = Report(company="Acme", company_description="x", summary="s",
                     financial_findings=[_ff("revenue_growth", 10, True)])
    rows = {r["question"]: r for r in build_human_checklist(report)}
    moat = rows["Does it have a durable competitive advantage (moat)?"]
    assert moat["status"] == "Insufficient evidence"


def test_executive_summary_says_not_requested_for_a_skipped_agent():
    report = Report(company="Acme", company_description="x", summary="s",
                     risk_findings=[_rf("annualized_volatility", 0.2)],
                     query_intent="risk_only", skipped_agents=["financial", "news"])
    summary = build_executive_summary(report)
    assert summary["Fundamentals"] == "Not requested"
    assert summary["News"] == "Not requested"
    assert summary["Risk"] == "Moderate"          # the one that DID run is judged


def test_empty_section_note_distinguishes_skipped_from_failed():
    from investpanel.utils.report_analysis import empty_section_note

    skipped = Report(company="A", company_description="x", summary="s",
                      query_intent="risk_only", skipped_agents=["news"])
    assert "Not requested" in empty_section_note(skipped, "news")

    failed = Report(company="A", company_description="x", summary="s")
    assert "Insufficient evidence" in empty_section_note(failed, "news")


def test_peer_note_says_not_requested_when_peers_were_not_wanted():
    report = Report(company="A", company_description="x", summary="s",
                     query_intent="risk_only", peers_requested=False)
    assert "Not requested" in peer_comparison_note(report)


def test_crosscheck_says_not_requested_when_an_agent_was_skipped():
    report = Report(company="Acme", company_description="x", summary="s",
                     financial_findings=[_ff("revenue_growth", 10, True)],
                     query_intent="financial_health", skipped_agents=["news", "risk"])
    status, explanation = crosscheck_conclusion(report)
    assert status == "Cross-check not possible"
    assert "was not requested" in explanation
    assert "could not be retrieved" not in explanation


def test_crosscheck_reports_consistent_only_with_both_sides_present():
    report = Report(company="Acme", company_description="x", summary="s",
                     financial_findings=[_ff("revenue_growth", 10, True)],
                     news_findings=[_nf("ok", tag="moat")],
                     risk_findings=[_rf("annualized_volatility", 0.1)])
    status, _ = crosscheck_conclusion(report)
    assert status == "Consistent evidence"


def test_crosscheck_flags_when_tensions_exist():
    from investpanel.models.contradiction import Tension

    report = Report(company="Acme", company_description="x", summary="s",
                     financial_findings=[_ff("revenue_growth", 10, True)],
                     risk_findings=[_rf("annualized_volatility", 0.1)],
                     potential_tensions=[Tension(between=("financial", "financial"),
                                                  description="d", reason="r")])
    status, _ = crosscheck_conclusion(report)
    assert status == "Tensions or contradictions found"


def test_contradiction_status_reflects_actual_execution():
    c = Contradiction(between=("financial", "news"), description="d",
                       follow_up_target="news", follow_up_question="q?")
    executed = Report(company="Acme", company_description="x", summary="s",
                       contradictions_resolved=1, followup_targets_executed=["news"])
    not_executed = Report(company="Acme", company_description="x", summary="s",
                           contradictions_resolved=1, followup_targets_executed=["financial"])
    assert contradiction_status(executed, c) == "Follow-up executed"
    assert contradiction_status(not_executed, c) == "Not selected for follow-up this round"
