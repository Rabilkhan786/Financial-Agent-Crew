"""Tests for the human-readable number formatting helpers. Pure functions, no I/O."""

from investpanel.utils.report_format import (
    format_currency,
    format_drawdown,
    format_metric_label,
    format_metric_value,
    format_multiple,
    format_percent,
    format_times,
    format_volatility,
)


def test_format_currency_picks_the_right_scale():
    assert format_currency(2_868_000_000.0) == "$2.87B"
    assert format_currency(4_500_000.0) == "$4.50M"
    assert format_currency(999.0) == "$999.00"
    assert format_currency(-1_200_000_000.0) == "-$1.20B"


def test_format_percent_signs_positive_only():
    assert format_percent(19.2234) == "+19.22%"
    assert format_percent(-3.4483) == "-3.45%"
    assert format_percent(19.2234, signed=False) == "19.22%"


def test_format_multiple_and_times():
    assert format_multiple(19.857142857) == "19.86×"
    assert format_times(76.0) == "76×"


def test_format_drawdown_and_volatility_from_positive_fractions():
    # RiskFinding stores both as positive fractions (0.26 == "26% below peak").
    assert format_drawdown(0.26) == "-26.0%"
    assert format_volatility(0.3987) == "39.9%"


def test_format_metric_label_known_and_unknown():
    assert format_metric_label("pe_ratio") == "P/E Ratio"
    assert format_metric_label("some_new_metric") == "Some New Metric"


def test_format_metric_value_matches_expected_display_per_metric():
    assert format_metric_value("pe_ratio", 19.8571) == "19.86×"
    assert format_metric_value("revenue_growth", 19.22) == "+19.22% YoY"
    assert format_metric_value("profit_growth", -3.4483) == "-3.45% YoY"
    assert format_metric_value("operating_cash_flow", 2_868_000_000.0) == "$2.87B"
    assert format_metric_value("debt_to_equity", 0.7422) == "0.74×"
    assert format_metric_value("interest_coverage", 76.0) == "76×"
    assert format_metric_value("roe", 0.2091) == "20.9%"
    assert format_metric_value("valuation_vs_growth", 0.6) == "0.60"
