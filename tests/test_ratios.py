"""Tests for the fundamental ratios.

Every number below was worked out by hand first, then checked against the code.
That is the point of keeping the arithmetic out of the LLM: these assertions are
things a person can verify with a calculator.
"""

import numpy as np
import pandas as pd
import pytest

from src.tools import ratios


# --- Fixtures ---------------------------------------------------------------

def healthy() -> pd.DataFrame:
    """A steadily growing, cash-generative, lightly borrowed company."""
    return pd.DataFrame(
        {
            "revenue": [1000.0, 1200.0, 1500.0, 1800.0],
            "operating_income": [200.0, 240.0, 285.0, 324.0],
            "net_income": [150.0, 180.0, 210.0, 240.0],
            "ebit": [200.0, 240.0, 285.0, 324.0],
            "interest_expense": [20.0, 20.0, 25.0, 30.0],
            "operating_cash_flow": [180.0, 220.0, 260.0, 300.0],
            "capex": [50.0, 60.0, 70.0, 80.0],
            "total_debt": [300.0, 320.0, 350.0, 400.0],
            "total_equity": [600.0, 700.0, 800.0, 900.0],
            "total_assets": [1100.0, 1250.0, 1400.0, 1600.0],
            "current_liabilities": [200.0, 250.0, 300.0, 350.0],
        },
        index=[2021, 2022, 2023, 2024],
    )


def variant(**columns) -> pd.DataFrame:
    """The healthy company with some columns replaced."""
    fin = healthy()
    for name, values in columns.items():
        fin[name] = values
    return fin


# --- Growth -----------------------------------------------------------------

def test_revenue_growth_latest_year():
    # 1800 / 1500 - 1 = 20%
    assert ratios.latest(ratios.revenue_growth_yoy(healthy())) == pytest.approx(0.20)


def test_revenue_growth_first_year_is_blank():
    # There is no year before the first one, so it cannot have a growth rate.
    assert np.isnan(ratios.revenue_growth_yoy(healthy()).iloc[0])


def test_revenue_cagr_over_three_years():
    # (1800 / 1000) ** (1/3) - 1
    assert ratios.revenue_cagr(healthy()) == pytest.approx(0.21644, abs=1e-5)


def test_revenue_cagr_needs_enough_history():
    two_years = healthy().tail(2)
    assert ratios.revenue_cagr(two_years, years=3) is None


# --- Profitability ----------------------------------------------------------

def test_operating_margin():
    # 324 / 1800 = 18%
    assert ratios.latest(ratios.operating_margin(healthy())) == pytest.approx(0.18)


def test_net_margin():
    # 240 / 1800 = 13.33%
    assert ratios.latest(ratios.net_margin(healthy())) == pytest.approx(0.13333, abs=1e-5)


def test_return_on_equity():
    # 240 / 900 = 26.67%
    assert ratios.latest(ratios.return_on_equity(healthy())) == pytest.approx(0.26667, abs=1e-5)


def test_return_on_capital_employed():
    # 324 / (1600 - 350) = 25.92%
    assert ratios.latest(ratios.return_on_capital_employed(healthy())) == pytest.approx(0.2592)


def test_roce_falls_back_to_operating_income_when_ebit_missing():
    fin = healthy().drop(columns=["ebit"])
    assert ratios.latest(ratios.return_on_capital_employed(fin)) == pytest.approx(0.2592)


# --- Cash -------------------------------------------------------------------

def test_cash_conversion():
    # 300 / 240 = 1.25x
    assert ratios.latest(ratios.cash_conversion(healthy())) == pytest.approx(1.25)


def test_cash_conversion_is_blank_in_a_loss_year():
    # Cash flow divided by a loss is a number that means nothing, so it is left out.
    fin = variant(net_income=[150.0, 180.0, 210.0, -240.0])
    assert ratios.latest(ratios.cash_conversion(fin)) == pytest.approx(260.0 / 210.0)


def test_free_cash_flow():
    # 300 - 80 = 220
    assert ratios.latest(ratios.free_cash_flow(healthy())) == pytest.approx(220.0)


def test_free_cash_flow_ignores_the_sign_of_capex():
    # Providers report capital spending as either a positive or a negative number.
    fin = variant(capex=[-50.0, -60.0, -70.0, -80.0])
    assert ratios.latest(ratios.free_cash_flow(fin)) == pytest.approx(220.0)


# --- Balance sheet ----------------------------------------------------------

def test_debt_to_equity():
    # 400 / 900 = 0.444
    assert ratios.latest(ratios.debt_to_equity(healthy())) == pytest.approx(0.44444, abs=1e-5)


def test_interest_coverage():
    # 324 / 30 = 10.8x
    assert ratios.latest(ratios.interest_coverage(healthy())) == pytest.approx(10.8)


# --- Missing and unusable data ----------------------------------------------

def test_missing_column_gives_none_not_a_guess():
    fin = healthy().drop(columns=["operating_cash_flow"])
    assert ratios.cash_conversion(fin) is None
    assert ratios.free_cash_flow(fin) is None


def test_all_nan_column_is_treated_as_missing():
    fin = variant(total_debt=[np.nan] * 4)
    assert ratios.debt_to_equity(fin) is None


def test_zero_denominator_gives_none_rather_than_infinity():
    fin = variant(total_equity=[0.0, 0.0, 0.0, 0.0])
    assert ratios.latest(ratios.debt_to_equity(fin)) is None


def test_negative_equity_leaves_the_ratio_blank():
    # A negative denominator would produce a tidy-looking number that misleads.
    fin = variant(total_equity=[600.0, 700.0, 800.0, -100.0])
    assert ratios.latest(ratios.return_on_equity(fin)) == pytest.approx(210.0 / 800.0)


def test_latest_never_returns_nan():
    fin = variant(revenue=[1000.0, 1200.0, 1500.0, np.nan])
    value = ratios.latest(ratios.operating_margin(fin))
    assert value is None or not np.isnan(value)


# --- Valuation against the company's own median -----------------------------

def test_valuation_above_its_own_median():
    result = ratios.valuation_vs_median(30.0, pd.Series([18.0, 20.0, 20.0, 22.0, 24.0]))
    assert result["median"] == pytest.approx(20.0)
    assert result["premium_pct"] == pytest.approx(0.5)
    assert "above" in result["verdict"]


def test_valuation_below_its_own_median():
    result = ratios.valuation_vs_median(15.0, pd.Series([18.0, 20.0, 20.0, 22.0, 24.0]))
    assert result["premium_pct"] == pytest.approx(-0.25)
    assert "below" in result["verdict"]


def test_valuation_in_line_with_its_own_median():
    result = ratios.valuation_vs_median(20.5, pd.Series([18.0, 20.0, 20.0, 22.0, 24.0]))
    assert "in line" in result["verdict"]


def test_valuation_uses_only_the_last_five_years():
    history = pd.Series([100.0, 100.0, 10.0, 10.0, 10.0, 10.0, 10.0])
    result = ratios.valuation_vs_median(10.0, history)
    assert result["median"] == pytest.approx(10.0)
    assert result["years"] == 5


def test_negative_multiple_is_reported_as_not_meaningful():
    result = ratios.valuation_vs_median(-12.0, pd.Series([18.0, 20.0, 22.0]))
    assert result["premium_pct"] is None
    assert "not meaningful" in result["verdict"]


def test_valuation_without_history_is_none():
    assert ratios.valuation_vs_median(20.0, None) is None
    assert ratios.valuation_vs_median(None, pd.Series([20.0])) is None


# --- Red flags --------------------------------------------------------------

def codes(fin: pd.DataFrame) -> set[str]:
    return {flag["code"] for flag in ratios.red_flags(fin)}


def test_healthy_company_raises_no_flags():
    assert ratios.red_flags(healthy()) == []


def test_weak_cash_conversion_flag():
    fin = variant(operating_cash_flow=[90.0, 100.0, 120.0, 140.0])
    assert "weak_cash_conversion" in codes(fin)


def test_one_bad_year_alone_does_not_raise_the_cash_conversion_flag():
    fin = variant(operating_cash_flow=[180.0, 220.0, 260.0, 100.0])
    assert "weak_cash_conversion" not in codes(fin)


def test_negative_operating_cash_flow_flag():
    fin = variant(operating_cash_flow=[180.0, 220.0, 260.0, -50.0])
    assert "negative_operating_cash_flow" in codes(fin)


def test_persistent_negative_free_cash_flow_flag():
    fin = variant(capex=[50.0, 300.0, 300.0, 300.0])
    assert "persistent_negative_fcf" in codes(fin)


def test_negative_equity_flag():
    fin = variant(total_equity=[600.0, 700.0, 800.0, -100.0])
    assert "negative_equity" in codes(fin)


def test_high_leverage_flag():
    fin = variant(total_debt=[300.0, 320.0, 350.0, 2500.0])
    assert "high_leverage" in codes(fin)


def test_thin_interest_cover_flag():
    fin = variant(interest_expense=[20.0, 20.0, 25.0, 300.0])
    assert "thin_interest_cover" in codes(fin)


def test_margin_erosion_flag():
    fin = variant(operating_income=[200.0, 240.0, 255.0, 270.0])
    assert "margin_erosion" in codes(fin)


def test_earnings_quality_flag():
    fin = variant(net_income=[150.0, 180.0, 210.0, 300.0],
                  operating_cash_flow=[180.0, 220.0, 260.0, 200.0])
    assert "earnings_quality" in codes(fin)


def test_revenue_decline_flag():
    fin = variant(revenue=[1000.0, 1200.0, 1500.0, 1200.0])
    assert "revenue_decline" in codes(fin)


def test_every_flag_carries_a_severity_and_a_message_with_numbers():
    fin = variant(total_debt=[300.0, 320.0, 350.0, 2500.0])
    for flag in ratios.red_flags(fin):
        assert flag["severity"] in {"high", "medium"}
        assert any(character.isdigit() for character in flag["message"])


# --- The single entry point -------------------------------------------------

def test_compute_all_returns_every_metric():
    result = ratios.compute_all(healthy(), pe_current=30.0,
                                pe_history=pd.Series([18.0, 20.0, 20.0, 22.0, 24.0]),
                                pb_current=3.0,
                                pb_history=pd.Series([2.0, 2.0, 2.5, 3.0, 3.0]))
    assert result["latest"]["operating_margin"] == pytest.approx(0.18)
    assert result["latest"]["revenue_cagr"] == pytest.approx(0.21644, abs=1e-5)
    assert result["valuation"]["pe"]["premium_pct"] == pytest.approx(0.5)
    assert result["unavailable"] == []
    assert result["red_flags"] == []


def test_compute_all_never_leaks_nan_into_the_latest_values():
    fin = variant(revenue=[np.nan] * 4)
    result = ratios.compute_all(fin)
    for name, value in result["latest"].items():
        assert value is None or not np.isnan(value), name


def test_compute_all_names_what_it_could_not_compute():
    fin = healthy().drop(columns=["operating_cash_flow"])
    result = ratios.compute_all(fin)
    assert "cash_conversion" in result["unavailable"]
    assert "free_cash_flow" in result["unavailable"]
    assert result["latest"]["cash_conversion"] is None


def test_compute_all_sorts_years_oldest_first():
    reversed_years = healthy().iloc[::-1]
    result = ratios.compute_all(reversed_years)
    assert result["latest"]["operating_margin"] == pytest.approx(0.18)


def test_compute_all_on_empty_data_reports_everything_unavailable():
    result = ratios.compute_all(pd.DataFrame())
    assert result["latest"] == {}
    assert "revenue_cagr" in result["unavailable"]
    assert result["red_flags"] == []


# --- The purity rule --------------------------------------------------------

def test_ratios_imports_nothing_but_maths():
    """Rule 1: this module does no I/O and calls no model.

    Checked here rather than trusted to memory, so a future edit that reaches
    for a network call or an LLM fails the test suite instead of shipping.
    """
    import ast
    import pathlib

    source = pathlib.Path("src/tools/ratios.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {"__future__", "numpy", "pandas"}, imported
