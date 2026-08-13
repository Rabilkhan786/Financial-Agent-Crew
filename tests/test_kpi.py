"""Tests for the price KPIs.

As with the ratios, every expected number was worked out by hand first. The
series below are deliberately small and round so the arithmetic can be checked
without running anything.
"""

import ast
import pathlib

import numpy as np
import pandas as pd
import pytest

from src.tools import kpi


# --- Fixtures ---------------------------------------------------------------

def prices(values: list[float], start: str = "2022-01-03") -> pd.Series:
    """Closing prices on consecutive business days."""
    dates = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(values, index=dates, dtype=float)


def two_year_prices(start_price: float, end_price: float) -> pd.Series:
    """A straight line between two prices spanning exactly two calendar years."""
    dates = pd.to_datetime(["2022-01-01", "2024-01-01"])
    return pd.Series([start_price, end_price], index=dates, dtype=float)


def trending_prices(days: int = 300) -> pd.Series:
    """A long enough history for a 200-day average to exist."""
    dates = pd.bdate_range(start="2023-01-02", periods=days)
    return pd.Series(np.linspace(100.0, 200.0, days), index=dates)


# --- Which index to compare against -----------------------------------------

def test_benchmark_for_indian_tickers():
    assert kpi.benchmark_for("RELIANCE.NS") == "^NSEI"
    assert kpi.benchmark_for("TCS.BO") == "^BSESN"


def test_benchmark_for_us_ticker_defaults_to_the_sp500():
    assert kpi.benchmark_for("AAPL") == "^GSPC"


def test_benchmark_lookup_ignores_case():
    assert kpi.benchmark_for("infy.ns") == "^NSEI"


# --- Return -----------------------------------------------------------------

def test_total_return():
    # 121 / 100 - 1 = 21%
    assert kpi.total_return(prices([100.0, 110.0, 121.0])) == pytest.approx(0.21)


def test_total_return_can_be_negative():
    assert kpi.total_return(prices([100.0, 50.0])) == pytest.approx(-0.5)


def test_annualised_return_over_two_years():
    # 121 / 100 doubled up over 2 years is roughly 10% a year.
    assert kpi.annualised_return(two_year_prices(100.0, 121.0)) == pytest.approx(0.10, abs=0.001)


def test_annualised_return_matches_total_return_over_one_year():
    one_year = pd.Series([100.0, 115.0], index=pd.to_datetime(["2023-01-01", "2024-01-01"]))
    assert kpi.annualised_return(one_year) == pytest.approx(0.15, abs=0.001)


def test_single_price_has_no_return():
    assert kpi.total_return(prices([100.0])) is None
    assert kpi.annualised_return(prices([100.0])) is None


# --- Risk -------------------------------------------------------------------

def test_daily_returns():
    result = kpi.daily_returns(prices([100.0, 110.0, 99.0]))
    assert list(result.round(6)) == [0.1, -0.1]


def test_volatility():
    # Daily returns of +10% and -10%: sample standard deviation is sqrt(0.02),
    # annualised by multiplying by sqrt(252) = 0.141421 * 15.874508 = 2.24499
    assert kpi.volatility(prices([100.0, 110.0, 99.0])) == pytest.approx(2.24499, abs=1e-5)


def test_a_flat_price_has_no_volatility():
    assert kpi.volatility(prices([100.0, 100.0, 100.0])) == pytest.approx(0.0)


def test_max_drawdown():
    # Peak 120 down to trough 60 is a 50% fall.
    assert kpi.max_drawdown(prices([100.0, 120.0, 60.0, 90.0])) == pytest.approx(-0.5)


def test_max_drawdown_measures_from_the_peak_not_the_start():
    # The later 200 -> 150 fall (-25%) is deeper than the early 100 -> 90 (-10%).
    assert kpi.max_drawdown(prices([100.0, 90.0, 200.0, 150.0])) == pytest.approx(-0.25)


def test_a_price_that_only_rises_has_no_drawdown():
    assert kpi.max_drawdown(prices([100.0, 110.0, 120.0])) == pytest.approx(0.0)


def test_sharpe_ratio_uses_the_risk_free_rate_it_is_given():
    series = trending_prices()
    annual = kpi.annualised_return(series)
    swing = kpi.volatility(series)
    expected = (annual - 0.05) / swing
    assert kpi.sharpe_ratio(series, risk_free_rate=0.05) == pytest.approx(expected)


def test_sharpe_is_lower_when_the_risk_free_rate_is_higher():
    series = trending_prices()
    assert kpi.sharpe_ratio(series, 0.07) < kpi.sharpe_ratio(series, 0.02)


def test_sharpe_is_none_when_there_is_no_volatility_to_divide_by():
    assert kpi.sharpe_ratio(prices([100.0, 100.0, 100.0])) is None


# --- Trend ------------------------------------------------------------------

def test_moving_average():
    # The 3-day average of the last three values 20, 30, 40 is 30.
    result = kpi.moving_average(prices([10.0, 20.0, 30.0, 40.0]), window=3)
    assert result.iloc[-1] == pytest.approx(30.0)


def test_moving_average_is_blank_until_there_is_enough_history():
    result = kpi.moving_average(prices([10.0, 20.0, 30.0, 40.0]), window=3)
    assert np.isnan(result.iloc[0])
    assert np.isnan(result.iloc[1])


def test_moving_average_summary_on_a_rising_stock():
    summary = kpi.moving_average_summary(trending_prices())
    assert summary["price"] == pytest.approx(200.0)
    assert summary["ma_50"] is not None and summary["ma_200"] is not None
    assert "above both" in summary["trend"]


def test_moving_average_summary_on_a_falling_stock():
    falling = pd.Series(np.linspace(200.0, 100.0, 300),
                        index=pd.bdate_range("2023-01-02", periods=300))
    assert "below both" in kpi.moving_average_summary(falling)["trend"]


def test_short_history_says_so_instead_of_guessing_the_trend():
    summary = kpi.moving_average_summary(prices([100.0, 101.0, 102.0]))
    assert summary["ma_200"] is None
    assert "not enough price history" in summary["trend"]


# --- Against the market -----------------------------------------------------

def test_return_vs_benchmark_when_the_stock_wins():
    stock = prices([100.0, 150.0])
    index = prices([200.0, 220.0])
    result = kpi.return_vs_benchmark(stock, index)
    assert result["stock_return"] == pytest.approx(0.5)
    assert result["benchmark_return"] == pytest.approx(0.1)
    assert result["excess_return"] == pytest.approx(0.4)
    assert "beat the index" in result["verdict"]


def test_return_vs_benchmark_when_the_stock_loses():
    result = kpi.return_vs_benchmark(prices([100.0, 105.0]), prices([200.0, 240.0]))
    assert result["excess_return"] == pytest.approx(-0.15)
    assert "lagged the index" in result["verdict"]


def test_return_vs_benchmark_compares_only_the_dates_they_share():
    # The index has an extra day the stock does not; using it would compare two
    # different windows and quietly produce a wrong answer.
    stock = pd.Series([100.0, 150.0], index=pd.to_datetime(["2023-01-02", "2023-01-03"]))
    index = pd.Series([200.0, 220.0, 500.0],
                      index=pd.to_datetime(["2023-01-02", "2023-01-03", "2023-01-04"]))
    result = kpi.return_vs_benchmark(stock, index)
    assert result["days_compared"] == 2
    assert result["benchmark_return"] == pytest.approx(0.1)


def test_return_vs_benchmark_with_no_overlap_is_none():
    stock = pd.Series([100.0, 150.0], index=pd.to_datetime(["2023-01-02", "2023-01-03"]))
    index = pd.Series([200.0, 220.0], index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    assert kpi.return_vs_benchmark(stock, index) is None


def test_return_vs_benchmark_without_an_index_is_none():
    assert kpi.return_vs_benchmark(prices([100.0, 150.0]), None) is None


# --- Bad and missing data ---------------------------------------------------

def test_empty_prices_give_none_everywhere():
    empty = pd.Series(dtype=float)
    assert kpi.total_return(empty) is None
    assert kpi.volatility(empty) is None
    assert kpi.max_drawdown(empty) is None


def test_none_prices_do_not_raise():
    assert kpi.total_return(None) is None
    assert kpi.moving_average_summary(None)["price"] is None


def test_zero_and_negative_prices_are_dropped_as_data_errors():
    # A zero close is a data error; dividing by it would produce an infinity.
    result = kpi.total_return(prices([100.0, 0.0, 121.0]))
    assert result == pytest.approx(0.21)


def test_gaps_in_the_price_history_are_skipped():
    with_gap = prices([100.0, np.nan, 121.0])
    assert kpi.total_return(with_gap) == pytest.approx(0.21)


def test_unsorted_dates_are_put_back_in_order():
    reversed_series = prices([100.0, 110.0, 121.0]).iloc[::-1]
    assert kpi.total_return(reversed_series) == pytest.approx(0.21)


# --- The single entry point -------------------------------------------------

def test_compute_all_returns_every_kpi():
    result = kpi.compute_all(trending_prices(), risk_free_rate=0.04)
    for name in ("total_return", "annualised_return", "volatility",
                 "max_drawdown", "sharpe_ratio", "ma_50", "ma_200", "last_close"):
        assert result["latest"][name] is not None, name
    assert result["risk_free_rate"] == 0.04
    assert "above both" in result["trend"]


def test_compute_all_never_leaks_nan_into_the_latest_values():
    result = kpi.compute_all(prices([100.0, 110.0]))
    for name, value in result["latest"].items():
        assert value is None or not np.isnan(value), name


def test_compute_all_names_what_it_could_not_compute():
    # Two days of prices is not enough for a 200-day average.
    result = kpi.compute_all(prices([100.0, 110.0]))
    assert "ma_200" in result["unavailable"]
    assert "return_vs_benchmark" in result["unavailable"]
    assert result["latest"]["ma_200"] is None


def test_compute_all_carries_the_series_needed_for_the_price_chart():
    result = kpi.compute_all(trending_prices())
    assert "close" in result["series"]
    assert "ma_50" in result["series"]
    assert "ma_200" in result["series"]


def test_compute_all_includes_the_benchmark_comparison_when_given_one():
    stock = prices([100.0, 150.0])
    index = prices([200.0, 220.0])
    result = kpi.compute_all(stock, benchmark_prices=index)
    assert result["benchmark"]["excess_return"] == pytest.approx(0.4)
    assert "return_vs_benchmark" not in result["unavailable"]


def test_compute_all_on_no_prices_reports_everything_unavailable():
    result = kpi.compute_all(None)
    assert result["benchmark"] is None
    assert "total_return" in result["unavailable"]
    assert result["series"] == {}


# --- The purity rule --------------------------------------------------------

def test_kpi_imports_nothing_but_maths():
    """Rule 1: this module does no I/O and calls no model.

    Checked here rather than trusted to memory, so a future edit that reaches
    for a network call or an LLM fails the test suite instead of shipping.
    """
    source = pathlib.Path("src/tools/kpi.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {"__future__", "numpy", "pandas"}, imported
