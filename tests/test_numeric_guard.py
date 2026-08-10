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
