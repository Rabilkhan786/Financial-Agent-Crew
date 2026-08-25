"""Tests for the guard that rejects invented numbers.

This is the check that protects the project's main claim: every figure in the
report came from a calculation or from a headline we fetched. It is production
code now - the reviewer sends reports back based on it - so it needs tests of
its own rather than being trusted because the eval happens to exercise it.

The awkward cases here are all real ones seen in live runs.
"""

import pandas as pd

from src.tools import sourcing


def state(report, metrics=None, articles=None, **extra):
    """A crew state with only the parts the guard reads."""
    research = {"articles": articles or []}
    research.update(extra.pop("research", {}))
    return {
        "report": report,
        "fundamentals": {"metrics": metrics or {}, **extra.pop("fundamentals", {})},
        "analysis": extra.pop("analysis", {}),
        "research": research,
    }


# --- The core rule ----------------------------------------------------------

def test_a_calculated_number_is_allowed():
    crew = state("The operating margin was 20.7%.", metrics={"operating_margin": 0.207})
    assert sourcing.unsourced_numbers(crew) == []


def test_a_number_from_nowhere_is_caught():
    crew = state("Revenue will reach 500bn next year.", metrics={"operating_margin": 0.207})
    assert "500" in sourcing.unsourced_numbers(crew)


def test_a_number_quoted_from_a_fetched_headline_is_allowed():
    crew = state("Profit rose 34%.",
                 articles=[{"title": "Yes Bank reports 34% jump in profit", "summary": ""}])
    assert sourcing.unsourced_numbers(crew) == []


def test_widening_a_sourced_figure_into_a_range_is_caught():
    # The real failure this guard was written for: 34 was sourced, 45 was not.
    crew = state("Profit rose 34-45% over three quarters.",
                 articles=[{"title": "Yes Bank reports 34% jump in profit", "summary": ""}])
    assert sourcing.unsourced_numbers(crew) == ["45"]


def test_a_number_only_in_an_article_summary_counts_as_sourced():
    crew = state("The raise was 20 billion.",
                 articles=[{"title": "Intel news", "summary": "a $20 billion capital raise"}])
    assert sourcing.unsourced_numbers(crew) == []


# --- Things that look like numbers but are not measurements -----------------

def test_iso_dates_are_not_numbers():
    crew = state("Fundamental analysis - 2023-01-01 to 2026-08-13")
    assert sourcing.unsourced_numbers(crew) == []


def test_written_dates_are_not_numbers():
    crew = state("Over the period from January 1, 2023, to August 13, 2026, it grew.")
    assert sourcing.unsourced_numbers(crew) == []


def test_index_names_are_not_numbers():
    crew = state("It outperformed the S&P 500 and the Nasdaq 100.")
    assert sourcing.unsourced_numbers(crew) == []


def test_years_are_always_allowed():
    crew = state("Revenue in 2024 was higher than in 2019.")
    assert sourcing.unsourced_numbers(crew) == []


# --- Formatting differences between the report and the source ---------------

def test_thousands_separators_do_not_split_a_number():
    # "105,263" is one number. Splitting it gave a phantom 105 and 263.
    crew = state("The chief executive bought 105,263 shares.",
                 articles=[{"title": "CEO buys 105,263 shares", "summary": ""}])
    assert sourcing.unsourced_numbers(crew) == []


def test_narrow_no_break_spaces_are_handled():
    # Models emit U+202F between a number and its unit; it broke the matching.
    crew = state("It beat the S&P 500 by 43.4 %.",
                 metrics={"excess": 0.434})
    assert sourcing.unsourced_numbers(crew) == []


def test_a_decimal_is_allowed_in_several_printed_forms():
    crew = state("Margin of 20.7%, or 0.21 as a fraction, near 21%.",
                 metrics={"operating_margin": 0.207})
    unknown = sourcing.unsourced_numbers(crew)
    assert "20.7" not in unknown and "21" not in unknown


def test_a_negative_value_may_be_written_without_its_sign():
    crew = state("The drawdown was 33.4%.", metrics={"max_drawdown": -0.334})
    assert sourcing.unsourced_numbers(crew) == []


# --- Other sources of legitimate numbers ------------------------------------

def test_the_social_tally_counts_as_calculated():
    # "16 out of 30 posts" is counted in Python, not guessed by the model.
    crew = state("Retail posts were 16 bullish out of 30.",
                 research={"social": {"tally": {"bullish": 16, "bearish": 3, "total": 30}}})
    assert sourcing.unsourced_numbers(crew) == []


def test_the_news_sentiment_score_counts_as_calculated():
    crew = state("News sentiment stands at 0.15.",
                 research={"news_sentiment": {"average_score": 0.15, "articles_scored": 12}})
    assert sourcing.unsourced_numbers(crew) == []


def test_statement_history_counts_as_calculated():
    crew = state("Revenue was 1500 in the prior year.",
                 fundamentals={"series": {"revenue": pd.Series([1000.0, 1500.0])}})
    assert sourcing.unsourced_numbers(crew) == []


def test_the_benchmark_comparison_counts_as_calculated():
    crew = state("It beat the index by 43.4%.",
                 analysis={"benchmark": {"stock_return": 1.46, "benchmark_return": 1.026,
                                         "excess_return": 0.434}})
    assert sourcing.unsourced_numbers(crew) == []


# --- Edge cases that must not raise -----------------------------------------

def test_an_empty_report_has_nothing_to_flag():
    assert sourcing.unsourced_numbers(state("")) == []


def test_a_report_with_no_numbers_at_all():
    assert sourcing.unsourced_numbers(state("The business looks steady.")) == []


def test_a_state_missing_every_section_does_not_raise():
    assert sourcing.unsourced_numbers({"report": "Margin was 12.3%."}) == ["12.3"]


def test_each_unknown_number_is_reported_once():
    crew = state("It was 999 then 999 again, and 999.")
    assert sourcing.unsourced_numbers(crew) == ["999"]


def test_a_report_can_be_passed_in_directly():
    # market_researcher checks its own summary before it reaches the state.
    crew = {"research": {"articles": [{"title": "profit rose 34%", "summary": ""}]}}
    assert sourcing.unsourced_numbers(crew, "profit rose 34%") == []
    assert sourcing.unsourced_numbers(crew, "profit rose 77%") == ["77"]


# --- The purity rule --------------------------------------------------------

def test_sourcing_imports_nothing_but_the_standard_library():
    """No LLM and no network: the guard must be checkable on its own."""
    import ast
    import pathlib

    source = pathlib.Path("src/tools/sourcing.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {"math", "re"}, imported


# --- The model wrapper ------------------------------------------------------

def test_structured_output_survives_the_retry_wrapper():
    """Regression: wrapping the model in .with_retry() first removed
    .with_structured_output(), so every reviewer decision silently became None.

    Checked without calling the model - it is the wiring that broke, not the
    answer.
    """
    from src import config, llm

    if not config.GROQ_API_KEY:
        import pytest
        pytest.skip("no key configured")

    assert hasattr(llm.get_base(), "with_structured_output")
    from src.agents.orchestrator import ReviewDecision
    chain = llm.get_base().with_structured_output(ReviewDecision).with_retry(**llm.RETRY)
    assert hasattr(chain, "invoke")
