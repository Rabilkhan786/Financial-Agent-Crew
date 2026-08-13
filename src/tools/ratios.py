"""Fundamental ratios — pure pandas/numpy, no LLM and no network.

Every fundamental number the agent crew talks about is computed here. That is
deliberate: arithmetic done in code can be unit tested and re-derived by hand,
while arithmetic done by a language model cannot. The LLM only ever *interprets*
what this module returns.

The input is one tidy DataFrame of annual statement data: one row per fiscal
year (oldest first), one column per canonical field below. `statements.py` is
responsible for mapping a data provider's line-item names onto these, so this
module never has to know that yfinance exists.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --- Canonical statement fields ---------------------------------------------
REVENUE = "revenue"
OPERATING_INCOME = "operating_income"
NET_INCOME = "net_income"
EBIT = "ebit"
INTEREST_EXPENSE = "interest_expense"          # positive magnitude of the cost
OPERATING_CASH_FLOW = "operating_cash_flow"
CAPEX = "capex"                                # positive magnitude of the spend
TOTAL_DEBT = "total_debt"
TOTAL_EQUITY = "total_equity"
TOTAL_ASSETS = "total_assets"
CURRENT_LIABILITIES = "current_liabilities"

# --- Thresholds -------------------------------------------------------------
# Red flags are rules, not opinions, so every threshold lives here in the open
# where it can be argued with. Nothing below is decided by the LLM.
CASH_CONVERSION_FLOOR = 0.70      # OCF below 70% of profit for 3 years running
DEBT_TO_EQUITY_CEILING = 2.0
INTEREST_COVERAGE_FLOOR = 2.0     # EBIT less than 2x the interest bill
MARGIN_EROSION_PP = 0.03          # 3 percentage points of operating margin lost
PROFIT_VS_REVENUE_GAP = 0.20      # profit growing 20pp faster than revenue
CAGR_YEARS = 3
VALUATION_MEDIAN_YEARS = 5
VALUATION_IN_LINE_BAND = 0.05     # within +/-5% of its own median = "in line"


# --- Small helpers ----------------------------------------------------------

def _column(fin: pd.DataFrame, name: str) -> pd.Series | None:
    """Return one statement column as numbers, or None if it is missing/empty.

    Missing data is returned as None rather than guessed at. Rule 5 of the
    project: absent statement data is reported as unavailable, never inferred.
    """
    if name not in fin.columns:
        return None
    values = pd.to_numeric(fin[name], errors="coerce")
    if values.dropna().empty:
        return None
    return values


def _divide(numerator: pd.Series | None, denominator: pd.Series | None,
            positive_denominator_only: bool = False) -> pd.Series | None:
    """Divide two columns, giving NaN instead of an error or an infinity.

    `positive_denominator_only` masks zero *and* negative denominators. A ratio
    like return-on-equity is meaningless when equity is negative, and printing a
    tidy-looking negative number there would mislead a reader.
    """
    if numerator is None or denominator is None:
        return None
    safe = denominator.astype(float).copy()
    safe[safe == 0] = np.nan
    if positive_denominator_only:
        safe[safe < 0] = np.nan
    return numerator.astype(float) / safe


def latest(series: pd.Series | None) -> float | None:
    """The most recent usable value, or None. Never returns NaN."""
    if series is None:
        return None
    usable = series.dropna()
    if usable.empty:
        return None
    return float(usable.iloc[-1])


# --- Growth -----------------------------------------------------------------

def revenue_growth_yoy(fin: pd.DataFrame) -> pd.Series | None:
    """Year-on-year revenue growth for every year except the first."""
    revenue = _column(fin, REVENUE)
    if revenue is None:
        return None
    previous = revenue.shift(1)
    return _divide(revenue - previous, previous, positive_denominator_only=True)


def revenue_cagr(fin: pd.DataFrame, years: int = CAGR_YEARS) -> float | None:
    """Compound annual growth rate of revenue over the last `years` years."""
    revenue = _column(fin, REVENUE)
    if revenue is None:
        return None
    usable = revenue.dropna()
    if len(usable) < years + 1:
        return None
    first = float(usable.iloc[-(years + 1)])
    last = float(usable.iloc[-1])
    if first <= 0 or last <= 0:
        return None
    return (last / first) ** (1 / years) - 1


# --- Profitability ----------------------------------------------------------

def operating_margin(fin: pd.DataFrame) -> pd.Series | None:
    return _divide(_column(fin, OPERATING_INCOME), _column(fin, REVENUE),
                   positive_denominator_only=True)


def net_margin(fin: pd.DataFrame) -> pd.Series | None:
    return _divide(_column(fin, NET_INCOME), _column(fin, REVENUE),
                   positive_denominator_only=True)


def return_on_equity(fin: pd.DataFrame) -> pd.Series | None:
    return _divide(_column(fin, NET_INCOME), _column(fin, TOTAL_EQUITY),
                   positive_denominator_only=True)


def return_on_capital_employed(fin: pd.DataFrame) -> pd.Series | None:
    """EBIT over capital employed (total assets minus current liabilities)."""
    ebit = _column(fin, EBIT)
    if ebit is None:
        ebit = _column(fin, OPERATING_INCOME)
    assets = _column(fin, TOTAL_ASSETS)
    current = _column(fin, CURRENT_LIABILITIES)
    if assets is None or current is None:
        return None
    return _divide(ebit, assets - current, positive_denominator_only=True)


# --- Cash -------------------------------------------------------------------

def cash_conversion(fin: pd.DataFrame) -> pd.Series | None:
    """Operating cash flow divided by net profit.

    Loss-making years are left blank: dividing cash flow by a negative profit
    produces a number that looks like a ratio but means nothing.
    """
    return _divide(_column(fin, OPERATING_CASH_FLOW), _column(fin, NET_INCOME),
                   positive_denominator_only=True)


def free_cash_flow(fin: pd.DataFrame) -> pd.Series | None:
    """Operating cash flow minus capital expenditure, in currency units."""
    ocf = _column(fin, OPERATING_CASH_FLOW)
    capex = _column(fin, CAPEX)
    if ocf is None or capex is None:
        return None
    return ocf - capex.abs()


# --- Balance sheet ----------------------------------------------------------

def debt_to_equity(fin: pd.DataFrame) -> pd.Series | None:
    return _divide(_column(fin, TOTAL_DEBT), _column(fin, TOTAL_EQUITY),
                   positive_denominator_only=True)


def interest_coverage(fin: pd.DataFrame) -> pd.Series | None:
    """EBIT divided by the interest bill — how many times over it is covered."""
    ebit = _column(fin, EBIT)
    if ebit is None:
        ebit = _column(fin, OPERATING_INCOME)
    interest = _column(fin, INTEREST_EXPENSE)
    if interest is None:
        return None
    return _divide(ebit, interest.abs(), positive_denominator_only=True)


# --- Valuation against the company's own history ----------------------------

def valuation_vs_median(current: float | None, history: pd.Series | None,
                        years: int = VALUATION_MEDIAN_YEARS) -> dict | None:
    """Compare a multiple with the same company's own median over `years`.

    Comparing a company against itself sidesteps the argument about which peers
    are truly comparable. A negative multiple (a loss-making company) is reported
    as not meaningful rather than dressed up as "cheap".
    """
    if current is None or history is None:
        return None
    window = pd.to_numeric(history, errors="coerce").dropna()
    window = window[window > 0].tail(years)
    if window.empty:
        return None
    median = float(window.median())
    if current <= 0:
        return {"current": float(current), "median": median, "years": len(window),
                "premium_pct": None,
                "verdict": "not meaningful (the multiple is negative)"}
    premium = current / median - 1
    if abs(premium) <= VALUATION_IN_LINE_BAND:
        verdict = f"in line with its own {len(window)}-year median"
    elif premium > 0:
        verdict = f"{premium:.0%} above its own {len(window)}-year median"
    else:
        verdict = f"{abs(premium):.0%} below its own {len(window)}-year median"
    return {"current": float(current), "median": median, "years": len(window),
            "premium_pct": float(premium), "verdict": verdict}


# --- Red flags --------------------------------------------------------------

def red_flags(fin: pd.DataFrame) -> list[dict]:
    """Deterministic warning rules. No LLM opinion involved.

    Each flag quotes the numbers that triggered it, so the report writer can
    state a figure it never had to calculate.
    """
    found: list[dict] = []

    def flag(code: str, severity: str, message: str) -> None:
        found.append({"code": code, "severity": severity, "message": message})

    conversion = cash_conversion(fin)
    if conversion is not None:
        recent = conversion.dropna().tail(3)
        if len(recent) == 3 and (recent < CASH_CONVERSION_FLOOR).all():
            flag("weak_cash_conversion", "high",
                 f"Operating cash flow has stayed below {CASH_CONVERSION_FLOOR:.0%} of net "
                 f"profit for three straight years (latest {recent.iloc[-1]:.2f}x). "
                 "Reported profit is not turning into cash.")

    ocf = _column(fin, OPERATING_CASH_FLOW)
    ocf_latest = latest(ocf)
    if ocf_latest is not None and ocf_latest < 0:
        flag("negative_operating_cash_flow", "high",
             f"Operating cash flow is negative in the latest year ({ocf_latest:,.0f}). "
             "The business consumed cash from its own operations.")

    fcf = free_cash_flow(fin)
    if fcf is not None:
        recent_fcf = fcf.dropna().tail(3)
        negative_years = int((recent_fcf < 0).sum())
        if len(recent_fcf) == 3 and negative_years >= 2:
            flag("persistent_negative_fcf", "medium",
                 f"Free cash flow was negative in {negative_years} of the last 3 years. "
                 "Capital spending is running ahead of the cash generated.")

    equity_latest = latest(_column(fin, TOTAL_EQUITY))
    if equity_latest is not None and equity_latest < 0:
        flag("negative_equity", "high",
             f"Shareholder equity is negative ({equity_latest:,.0f}). "
             "Liabilities exceed assets on the balance sheet.")

    leverage = latest(debt_to_equity(fin))
    if leverage is not None and leverage > DEBT_TO_EQUITY_CEILING:
        flag("high_leverage", "high",
             f"Debt-to-equity is {leverage:.2f}, above the {DEBT_TO_EQUITY_CEILING:.1f} "
             "threshold used here for a heavily borrowed balance sheet.")

    coverage = latest(interest_coverage(fin))
    if coverage is not None and coverage < INTEREST_COVERAGE_FLOOR:
        flag("thin_interest_cover", "high",
             f"Operating profit covers the interest bill only {coverage:.2f} times, below the "
             f"{INTEREST_COVERAGE_FLOOR:.1f}x threshold. There is little room if profit falls.")

    margins = operating_margin(fin)
    latest_growth = latest(revenue_growth_yoy(fin))
    if margins is not None and latest_growth is not None and latest_growth > 0:
        recent_margins = margins.dropna().tail(CAGR_YEARS + 1)
        if len(recent_margins) >= 2:
            erosion = float(recent_margins.iloc[0] - recent_margins.iloc[-1])
            if erosion >= MARGIN_EROSION_PP:
                flag("margin_erosion", "medium",
                     f"Revenue is still growing ({latest_growth:.1%} in the latest year) but the "
                     f"operating margin fell from {recent_margins.iloc[0]:.1%} to "
                     f"{recent_margins.iloc[-1]:.1%}. Growth is costing profitability.")

    net_income = _column(fin, NET_INCOME)
    if net_income is not None and ocf is not None and latest_growth is not None:
        profits = net_income.dropna()
        cash = ocf.dropna()
        if len(profits) >= 2 and len(cash) >= 2 and profits.iloc[-2] > 0 and latest_growth > 0:
            profit_change = float(profits.iloc[-1] / profits.iloc[-2] - 1)
            if (profit_change > latest_growth + PROFIT_VS_REVENUE_GAP
                    and cash.iloc[-1] < cash.iloc[-2]):
                flag("earnings_quality", "medium",
                     f"Net profit grew {profit_change:.1%} against revenue growth of "
                     f"{latest_growth:.1%}, while operating cash flow fell. The extra profit is "
                     "not showing up in cash.")

    if latest_growth is not None and latest_growth < 0:
        flag("revenue_decline", "medium",
             f"Revenue fell {abs(latest_growth):.1%} in the latest year.")

    return found


# --- One entry point --------------------------------------------------------

# Every ratio the crew reports on, paired with the function producing its history.
_SERIES_METRICS = {
    "revenue_growth_yoy": revenue_growth_yoy,
    "operating_margin": operating_margin,
    "net_margin": net_margin,
    "cash_conversion": cash_conversion,
    "free_cash_flow": free_cash_flow,
    "debt_to_equity": debt_to_equity,
    "interest_coverage": interest_coverage,
    "return_on_capital_employed": return_on_capital_employed,
    "return_on_equity": return_on_equity,
}

# Raw statement lines carried through for the charts and for anyone who wants to
# check a ratio by hand.
_PASSTHROUGH_FIELDS = (REVENUE, OPERATING_INCOME, NET_INCOME, OPERATING_CASH_FLOW,
                       TOTAL_DEBT, TOTAL_EQUITY)


def compute_all(fin: pd.DataFrame,
                pe_current: float | None = None,
                pe_history: pd.Series | None = None,
                pb_current: float | None = None,
                pb_history: pd.Series | None = None) -> dict:
    """Compute every fundamental ratio the crew uses.

    Returns the latest scalars (never NaN — a metric that cannot be computed is
    None and is named in `unavailable`), the full history of each metric for
    charting, valuation against the company's own median, and the red flags.
    """
    empty = fin is None or fin.empty
    if empty:
        return {"latest": {}, "series": {}, "valuation": {"pe": None, "pb": None},
                "red_flags": [],
                "unavailable": sorted(list(_SERIES_METRICS)
                                      + ["revenue_cagr", "pe_vs_median", "pb_vs_median"])}

    fin = fin.sort_index()

    series: dict[str, pd.Series] = {}
    latest_values: dict[str, float | None] = {}
    unavailable: list[str] = []

    for name, function in _SERIES_METRICS.items():
        computed = function(fin)
        if computed is not None:
            series[name] = computed
        value = latest(computed)
        latest_values[name] = value
        if value is None:
            unavailable.append(name)

    cagr = revenue_cagr(fin)
    latest_values["revenue_cagr"] = cagr
    if cagr is None:
        unavailable.append("revenue_cagr")

    for field in _PASSTHROUGH_FIELDS:
        column = _column(fin, field)
        if column is not None:
            series[field] = column

    valuation = {
        "pe": valuation_vs_median(pe_current, pe_history),
        "pb": valuation_vs_median(pb_current, pb_history),
    }
    for name, result in valuation.items():
        if result is None:
            unavailable.append(f"{name}_vs_median")

    return {
        "latest": latest_values,
        "series": series,
        "valuation": valuation,
        "red_flags": red_flags(fin),
        "unavailable": sorted(unavailable),
    }
