"""Focused tests for deterministic fundamental ratios."""

import pandas as pd
import pytest

from src.tools import ratios


def healthy_company():
    """Return four years of simple, steadily growing statement data."""
    return pd.DataFrame(
        {
            "revenue": [100.0, 110.0, 121.0, 133.1],
            "operating_income": [20.0, 22.0, 24.2, 26.62],
            "net_income": [10.0, 11.0, 12.1, 13.31],
            "ebit": [20.0, 22.0, 24.2, 26.62],
            "interest_expense": [2.0, 2.0, 2.0, 2.0],
            "operating_cash_flow": [12.0, 13.0, 14.5, 16.0],
            "capex": [2.0, 2.0, 2.0, 2.0],
            "total_debt": [20.0, 20.0, 20.0, 20.0],
            "total_equity": [50.0, 55.0, 60.0, 65.0],
            "total_assets": [100.0, 110.0, 120.0, 130.0],
            "current_liabilities": [20.0, 22.0, 24.0, 26.0],
        },
        index=[2021, 2022, 2023, 2024],
    )


def risky_company():
    """Return statement data that triggers several warning rules."""
    return pd.DataFrame(
        {
            "revenue": [100.0, 90.0],
            "operating_income": [20.0, 5.0],
            "net_income": [10.0, 5.0],
            "ebit": [20.0, 5.0],
            "interest_expense": [2.0, 5.0],
            "operating_cash_flow": [12.0, -1.0],
            "capex": [2.0, 10.0],
            "total_debt": [20.0, 200.0],
            "total_equity": [50.0, 40.0],
            "total_assets": [100.0, 100.0],
            "current_liabilities": [20.0, 20.0],
        },
        index=[2023, 2024],
    )


def test_growth_metrics():
    table = healthy_company()
    assert ratios.latest(ratios.revenue_growth_yoy(table)) == pytest.approx(0.10)
    assert ratios.revenue_cagr(table) == pytest.approx(0.10)


def test_profitability_metrics():
    table = healthy_company()
    assert ratios.latest(ratios.operating_margin(table)) == pytest.approx(0.20)
    assert ratios.latest(ratios.net_margin(table)) == pytest.approx(0.10)
    assert ratios.latest(ratios.return_on_equity(table)) == pytest.approx(
        13.31 / 65.0
    )
    assert ratios.latest(
        ratios.return_on_capital_employed(table)
    ) == pytest.approx(26.62 / (130.0 - 26.0))


def test_cash_and_debt_metrics():
    table = healthy_company()
    assert ratios.latest(ratios.cash_conversion(table)) == pytest.approx(
        16.0 / 13.31
    )
    assert ratios.latest(ratios.free_cash_flow(table)) == pytest.approx(14.0)
    assert ratios.latest(ratios.debt_to_equity(table)) == pytest.approx(
        20.0 / 65.0
    )
    assert ratios.latest(ratios.interest_coverage(table)) == pytest.approx(
        26.62 / 2.0
    )


def test_valuation_vs_historical_median():
    history = pd.Series([10.0, 12.0, 14.0])
    result = ratios.valuation_vs_median(15.0, history)

    assert result["median"] == pytest.approx(12.0)
    assert result["premium_pct"] == pytest.approx(0.25)
    assert "above" in result["verdict"]


def test_red_flags_are_deterministic():
    codes = {flag["code"] for flag in ratios.red_flags(risky_company())}

    assert "negative_operating_cash_flow" in codes
    assert "high_leverage" in codes
    assert "thin_interest_cover" in codes
    assert "revenue_decline" in codes


def test_missing_columns_return_none_instead_of_guessing():
    table = pd.DataFrame({"revenue": [100.0, 110.0]})
    assert ratios.operating_margin(table) is None
    assert ratios.debt_to_equity(table) is None


def test_compute_all_returns_metrics_series_and_red_flags():
    table = healthy_company()
    result = ratios.compute_all(table)

    assert result["latest"]["revenue_growth_yoy"] == pytest.approx(0.10)
    assert result["latest"]["operating_margin"] == pytest.approx(0.20)
    assert "revenue" in result["series"]
    assert "operating_margin" in result["series"]
    assert result["red_flags"] == []
    assert "pe_vs_median" in result["unavailable"]


def test_compute_all_handles_empty_data():
    result = ratios.compute_all(pd.DataFrame())
    assert result["latest"] == {}
    assert result["series"] == {}
    assert result["red_flags"] == []
    assert "revenue_cagr" in result["unavailable"]
