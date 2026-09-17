"""Focused tests for deterministic price KPIs."""

import numpy as np
import pandas as pd
import pytest

from src.tools import kpi


def prices(values, start="2023-01-02"):
    """Return closing prices on consecutive business days."""
    dates = pd.bdate_range(start=start, periods=len(values))
    return pd.Series(values, index=dates, dtype=float)


def trending_prices(days=300):
    """Return enough price history for 50-day and 200-day averages."""
    dates = pd.bdate_range(start="2023-01-02", periods=days)
    return pd.Series(np.linspace(100.0, 200.0, days), index=dates)


def test_benchmark_selection():
    assert kpi.benchmark_for("RELIANCE.NS") == "^NSEI"
    assert kpi.benchmark_for("TCS.BO") == "^BSESN"
    assert kpi.benchmark_for("AAPL") == "^GSPC"


def test_return_metrics():
    series = pd.Series(
        [100.0, 121.0],
        index=pd.to_datetime(["2022-01-01", "2024-01-01"]),
    )
    assert kpi.total_return(series) == pytest.approx(0.21)
    assert kpi.annualised_return(series) == pytest.approx(0.10, abs=0.001)


def test_risk_metrics():
    series = prices([100.0, 110.0, 99.0])
    assert list(kpi.daily_returns(series).round(6)) == [0.1, -0.1]
    assert kpi.volatility(series) == pytest.approx(2.24499, abs=1e-5)

    drawdown = prices([100.0, 120.0, 60.0, 90.0])
    assert kpi.max_drawdown(drawdown) == pytest.approx(-0.5)


def test_sharpe_requires_volatility():
    flat = prices([100.0, 100.0, 100.0])
    assert kpi.sharpe_ratio(flat) is None


def test_moving_average_summary():
    summary = kpi.moving_average_summary(trending_prices())
    assert summary["price"] == pytest.approx(200.0)
    assert summary["ma_50"] is not None
    assert summary["ma_200"] is not None
    assert "above both" in summary["trend"]


def test_benchmark_comparison_uses_shared_dates():
    stock = pd.Series(
        [100.0, 150.0],
        index=pd.to_datetime(["2023-01-02", "2023-01-03"]),
    )
    index = pd.Series(
        [200.0, 220.0, 500.0],
        index=pd.to_datetime([
            "2023-01-02",
            "2023-01-03",
            "2023-01-04",
        ]),
    )

    result = kpi.return_vs_benchmark(stock, index)
    assert result["stock_return"] == pytest.approx(0.5)
    assert result["benchmark_return"] == pytest.approx(0.1)
    assert result["days_compared"] == 2


def test_invalid_prices_are_ignored():
    series = prices([100.0, 0.0, np.nan, 121.0])
    assert kpi.total_return(series) == pytest.approx(0.21)


def test_compute_all_returns_chart_series_and_missing_metrics():
    result = kpi.compute_all(trending_prices(), risk_free_rate=0.04)

    assert result["latest"]["total_return"] is not None
    assert result["latest"]["ma_200"] is not None
    assert result["risk_free_rate"] == 0.04
    assert "close" in result["series"]
    assert "ma_50" in result["series"]
    assert "ma_200" in result["series"]

    short = kpi.compute_all(prices([100.0, 110.0]))
    assert short["latest"]["ma_200"] is None
    assert "ma_200" in short["unavailable"]
