"""Tests for CHANGE 2's enforcement: LLM prose may only quote computed numbers.

The guard has to be strict about invented figures without being so twitchy that it
rejects honest rounding — both directions are tested here.
"""

from investpanel.utils.numeric_guard import extract_numbers, unsupported_numbers, verify_summary


def test_extract_ignores_counts_and_years():
    numbers = extract_numbers("In 2026 we reviewed 3 news items and found 2 contradictions.")
    assert numbers == []


def test_extract_finds_real_figures():
    assert 65.47 in extract_numbers("Revenue grew 65.47% year over year.")
    assert 1234.5 in extract_numbers("Operating income was 1,234.5 million.")


def test_rounded_prose_is_accepted():
    # 65.47 computed; the model writing "65.5%" or "65%" is honest rounding.
    for phrasing in ("Revenue grew 65.47%.", "Revenue grew 65.5%.", "Revenue grew 65%."):
        clean, offenders = verify_summary(phrasing, [65.47])
        assert clean, f"{phrasing} was wrongly rejected ({offenders})"


def test_fraction_written_as_a_percentage_is_accepted():
    # ROE is stored as 0.2091 but is naturally written "20.9%".
    clean, _ = verify_summary("Return on equity is 20.9%.", [0.2091])
    assert clean


def test_large_number_written_in_billions_is_accepted():
    clean, _ = verify_summary("Operating cash flow was $2.87B.", [2_868_000_000.0])
    assert clean


def test_invented_number_is_caught():
    clean, offenders = verify_summary("Revenue grew 80% and margins hit 45%.", [65.47, 20.9])
    assert not clean
    assert 80.0 in offenders


def test_prose_with_no_numbers_is_clean():
    clean, offenders = verify_summary("Growth is strong but the valuation looks rich.", [])
    assert clean
    assert offenders == []


def test_unsupported_numbers_lists_only_the_bad_ones():
    offenders = unsupported_numbers("Revenue 65.47%, profit 64.75%, and a made-up 999.9%.",
                                     [65.47, 64.75])
    assert offenders == [999.9]


def test_analyst_discards_a_summary_containing_invented_numbers():
    # End to end: a model that fabricates a figure must not reach the report.
    from investpanel.agents.analyst import AnalystAgent
    from investpanel.models.findings import FinancialFinding

    class LyingLLM:
        def invoke(self, prompt):
            class R:
                content = "Revenue grew an incredible 250% this year."
            return R()

    financial = [FinancialFinding(metric="revenue_growth", value=6.4, unit="percent_yoy",
                                   period="2025", source="FMP", interpretation="up", healthy=True)]
    agent = AnalystAgent(llm=LyingLLM())
    summary = agent._summary("Acme", financial, [], [], [])
    assert "250" not in summary          # the fabrication is gone
    assert "1/1 financial metrics" in summary  # fell back to the counted template


def test_numbers_quoted_from_a_finding_sentence_are_allowed():
    # Regression from a live run: the guard rejected "100-day" and the "40% threshold",
    # both of which are computed facts stated in the findings' own text.
    from investpanel.agents.analyst import AnalystAgent
    from investpanel.models.findings import RiskFinding

    class QuotingLLM:
        def invoke(self, prompt):
            class R:
                content = ("Annualized volatility is 45% over a 100-day close series, "
                           "moderate versus a 40% threshold.")
            return R()

    risk = [RiskFinding(
        metric="annualized_volatility", value=0.45,
        computed_from="100-day close series, AlphaVantage",
        interpretation="Annualized volatility is 45% — moderate versus a 40% threshold.",
    )]
    summary = AnalystAgent(llm=QuotingLLM())._summary("Acme", [], [], risk, [])
    assert "100-day" in summary  # kept, not discarded


def test_numbers_from_a_critic_finding_are_allowed():
    # Regression from a live Intel run: the guard rejected "50%", which came from
    # the Critic's own "versus a peer average of 50%" — a computed figure.
    from investpanel.agents.analyst import AnalystAgent
    from investpanel.models.contradiction import Contradiction

    class QuotingLLM:
        def invoke(self, prompt):
            class R:
                content = "Revenue growth lags a peer average of 50%, which is the main concern."
            return R()

    contradiction = Contradiction(
        between=("financial", "news"),
        description="revenue growth is -0% versus a peer average of 50% — behind its competitors.",
        follow_up_target="news", follow_up_question="why?",
    )
    summary = AnalystAgent(llm=QuotingLLM())._summary("Intel", [], [], [], [contradiction], [])
    assert "50%" in summary  # kept, not discarded


def test_analyst_keeps_a_summary_that_only_uses_real_numbers():
    from investpanel.agents.analyst import AnalystAgent
    from investpanel.models.findings import FinancialFinding

    class HonestLLM:
        def invoke(self, prompt):
            class R:
                content = "Revenue grew 6.4% year over year, a modest but positive result."
            return R()

    financial = [FinancialFinding(metric="revenue_growth", value=6.4, unit="percent_yoy",
                                   period="2025", source="FMP", interpretation="up", healthy=True)]
    summary = AnalystAgent(llm=HonestLLM())._summary("Acme", financial, [], [], [])
    assert "6.4%" in summary


def test_a_number_quoted_from_a_sourced_article_is_allowed():
    # Regression from a live Tesla news-only run: the guard rejected "475", a figure
    # stated in a fetched article. It has a source URL, so repeating it is legitimate —
    # the guard exists to stop invention, not sourced quotation.
    from investpanel.agents.analyst import AnalystAgent
    from investpanel.models.findings import NewsFinding

    class QuotingLLM:
        def invoke(self, prompt):
            class R:
                content = "Analysts set a price target of 475 following the announcement."
            return R()

    news = [NewsFinding(headline="Analyst raises target to 475", summary="A target of 475 was set.",
                         source_url="https://e.com", published_date="2026-08-01", relevance="high")]
    summary = AnalystAgent(llm=QuotingLLM())._summary("Tesla", [], news, [], [])
    assert "475" in summary


def test_fallback_summary_mentions_only_what_ran():
    # "0/0 financial metrics healthy" on a news-only run reads like a failure.
    from investpanel.agents.analyst import AnalystAgent
    from investpanel.models.findings import NewsFinding

    class BrokenLLM:
        def invoke(self, prompt):
            raise RuntimeError("rate limited")

    news = [NewsFinding(headline="h", summary="s", source_url="https://e.com",
                         published_date="2026-08-01", relevance="high")]
    summary = AnalystAgent(llm=BrokenLLM())._summary("Tesla", [], news, [], [])
    assert "financial metrics" not in summary
    assert "1 news items reviewed" in summary
