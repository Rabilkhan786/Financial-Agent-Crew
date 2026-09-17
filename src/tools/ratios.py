"""Deterministic financial ratio and red-flag calculations."""

import numpy as np
import pandas as pd

REVENUE = "revenue"
OPERATING_INCOME = "operating_income"
NET_INCOME = "net_income"
EBIT = "ebit"
INTEREST_EXPENSE = "interest_expense"
OPERATING_CASH_FLOW = "operating_cash_flow"
CAPEX = "capex"
TOTAL_DEBT = "total_debt"
TOTAL_EQUITY = "total_equity"
TOTAL_ASSETS = "total_assets"
CURRENT_LIABILITIES = "current_liabilities"

CASH_CONVERSION_FLOOR = 0.70
DEBT_TO_EQUITY_CEILING = 2.0
INTEREST_COVERAGE_FLOOR = 2.0
MARGIN_EROSION_PP = 0.03
PROFIT_VS_REVENUE_GAP = 0.20
CAGR_YEARS = 3
VALUATION_MEDIAN_YEARS = 5
VALUATION_IN_LINE_BAND = 0.05


def get_column(table, name):
    """Return a numeric column, or None when it is missing or empty."""
    if name not in table.columns:
        return None

    numbers = pd.to_numeric(table[name], errors="coerce")
    if numbers.dropna().empty:
        return None
    return numbers


def divide(top, bottom, positive_only=False):
    """Safely divide two Series and replace invalid denominators with NaN."""
    if top is None or bottom is None:
        return None

    safe = bottom.astype(float).copy()
    safe[safe == 0] = np.nan
    if positive_only:
        safe[safe < 0] = np.nan
    return top.astype(float) / safe


def latest(column):
    """Return the latest non-null value as a float."""
    if column is None:
        return None

    usable = column.dropna()
    if usable.empty:
        return None
    return float(usable.iloc[-1])


def revenue_growth_yoy(table):
    """Return year-over-year revenue growth."""
    revenue = get_column(table, REVENUE)
    if revenue is None:
        return None

    previous = revenue.shift(1)
    return divide(
        revenue - previous,
        previous,
        positive_only=True,
    )


def revenue_cagr(table, years=CAGR_YEARS):
    """Return revenue CAGR over the requested number of years."""
    revenue = get_column(table, REVENUE)
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


def operating_margin(table):
    """Return operating income divided by revenue."""
    return divide(
        get_column(table, OPERATING_INCOME),
        get_column(table, REVENUE),
        positive_only=True,
    )


def net_margin(table):
    """Return net income divided by revenue."""
    return divide(
        get_column(table, NET_INCOME),
        get_column(table, REVENUE),
        positive_only=True,
    )


def return_on_equity(table):
    """Return net income divided by positive shareholder equity."""
    return divide(
        get_column(table, NET_INCOME),
        get_column(table, TOTAL_EQUITY),
        positive_only=True,
    )


def return_on_capital_employed(table):
    """Return EBIT divided by total assets minus current liabilities."""
    profit = get_column(table, EBIT)
    if profit is None:
        profit = get_column(table, OPERATING_INCOME)

    assets = get_column(table, TOTAL_ASSETS)
    current_liabilities = get_column(table, CURRENT_LIABILITIES)
    if assets is None or current_liabilities is None:
        return None

    return divide(
        profit,
        assets - current_liabilities,
        positive_only=True,
    )


def cash_conversion(table):
    """Return operating cash flow divided by positive net income."""
    return divide(
        get_column(table, OPERATING_CASH_FLOW),
        get_column(table, NET_INCOME),
        positive_only=True,
    )


def free_cash_flow(table):
    """Return operating cash flow minus absolute capital expenditure."""
    cash = get_column(table, OPERATING_CASH_FLOW)
    capex = get_column(table, CAPEX)
    if cash is None or capex is None:
        return None
    return cash - capex.abs()


def debt_to_equity(table):
    """Return total debt divided by positive shareholder equity."""
    return divide(
        get_column(table, TOTAL_DEBT),
        get_column(table, TOTAL_EQUITY),
        positive_only=True,
    )


def interest_coverage(table):
    """Return EBIT divided by absolute interest expense."""
    profit = get_column(table, EBIT)
    if profit is None:
        profit = get_column(table, OPERATING_INCOME)

    interest = get_column(table, INTEREST_EXPENSE)
    if interest is None:
        return None

    return divide(
        profit,
        interest.abs(),
        positive_only=True,
    )


def valuation_vs_median(current, history, years=VALUATION_MEDIAN_YEARS):
    """Compare a current valuation multiple with its historical median."""
    if current is None or history is None:
        return None

    past = pd.to_numeric(history, errors="coerce").dropna()
    past = past[past > 0].tail(years)
    if past.empty:
        return None

    median = float(past.median())
    if current <= 0:
        return {
            "current": float(current),
            "median": median,
            "years": len(past),
            "premium_pct": None,
            "verdict": "not meaningful (the multiple is negative)",
        }

    gap = current / median - 1
    if abs(gap) <= VALUATION_IN_LINE_BAND:
        verdict = f"in line with its own {len(past)}-year median"
    elif gap > 0:
        verdict = f"{gap:.0%} above its own {len(past)}-year median"
    else:
        verdict = f"{abs(gap):.0%} below its own {len(past)}-year median"

    return {
        "current": float(current),
        "median": median,
        "years": len(past),
        "premium_pct": float(gap),
        "verdict": verdict,
    }


def red_flags(table):
    """Return deterministic warning flags triggered by the statement data."""
    found = []

    def add(code, severity, message):
        found.append(
            {
                "code": code,
                "severity": severity,
                "message": message,
            }
        )

    conversion = cash_conversion(table)
    if conversion is not None:
        recent = conversion.dropna().tail(3)
        if len(recent) == 3 and (recent < CASH_CONVERSION_FLOOR).all():
            add(
                "weak_cash_conversion",
                "high",
                (
                    "Operating cash flow has stayed below "
                    f"{CASH_CONVERSION_FLOOR:.0%} of net profit for three "
                    f"straight years (latest {recent.iloc[-1]:.2f}x). "
                    "Reported profit is not turning into cash."
                ),
            )

    cash = get_column(table, OPERATING_CASH_FLOW)
    cash_now = latest(cash)
    if cash_now is not None and cash_now < 0:
        add(
            "negative_operating_cash_flow",
            "high",
            (
                "Operating cash flow is negative in the latest year "
                f"({cash_now:,.0f}). The business used up cash rather than "
                "making it."
            ),
        )

    spare_cash = free_cash_flow(table)
    if spare_cash is not None:
        recent = spare_cash.dropna().tail(3)
        bad_years = int((recent < 0).sum())
        if len(recent) == 3 and bad_years >= 2:
            add(
                "persistent_negative_fcf",
                "medium",
                (
                    f"Free cash flow was negative in {bad_years} of the last "
                    "3 years. Spending is running ahead of the cash coming in."
                ),
            )

    equity_now = latest(get_column(table, TOTAL_EQUITY))
    if equity_now is not None and equity_now < 0:
        add(
            "negative_equity",
            "high",
            (
                f"Shareholder equity is negative ({equity_now:,.0f}). "
                "The company owes more than it owns."
            ),
        )

    borrowing = latest(debt_to_equity(table))
    if borrowing is not None and borrowing > DEBT_TO_EQUITY_CEILING:
        add(
            "high_leverage",
            "high",
            (
                f"Debt to equity is {borrowing:.2f}, above the "
                f"{DEBT_TO_EQUITY_CEILING:.1f} level we treat as heavily "
                "borrowed."
            ),
        )

    cover = latest(interest_coverage(table))
    if cover is not None and cover < INTEREST_COVERAGE_FLOOR:
        add(
            "thin_interest_cover",
            "high",
            (
                f"Operating profit covers the interest bill only {cover:.2f} "
                f"times, under the {INTEREST_COVERAGE_FLOOR:.1f}x level. "
                "There is little room if profit falls."
            ),
        )

    margins = operating_margin(table)
    growth_now = latest(revenue_growth_yoy(table))
    if margins is not None and growth_now is not None and growth_now > 0:
        recent = margins.dropna().tail(CAGR_YEARS + 1)
        if len(recent) >= 2:
            drop = float(recent.iloc[0] - recent.iloc[-1])
            if drop >= MARGIN_EROSION_PP:
                add(
                    "margin_erosion",
                    "medium",
                    (
                        f"Revenue is still growing ({growth_now:.1%} in the "
                        "latest year) but the operating margin fell from "
                        f"{recent.iloc[0]:.1%} to {recent.iloc[-1]:.1%}. "
                        "Growth is costing profitability."
                    ),
                )

    profits = get_column(table, NET_INCOME)
    if profits is not None and cash is not None and growth_now is not None:
        profit_years = profits.dropna()
        cash_years = cash.dropna()

        enough_history = len(profit_years) >= 2 and len(cash_years) >= 2
        if enough_history and profit_years.iloc[-2] > 0 and growth_now > 0:
            profit_growth = float(
                profit_years.iloc[-1] / profit_years.iloc[-2] - 1
            )
            if (
                profit_growth > growth_now + PROFIT_VS_REVENUE_GAP
                and cash_years.iloc[-1] < cash_years.iloc[-2]
            ):
                add(
                    "earnings_quality",
                    "medium",
                    (
                        f"Net profit grew {profit_growth:.1%} against revenue "
                        f"growth of {growth_now:.1%}, while cash from operations "
                        "fell. The extra profit is not showing up as cash."
                    ),
                )

    if growth_now is not None and growth_now < 0:
        add(
            "revenue_decline",
            "medium",
            f"Revenue fell {abs(growth_now):.1%} in the latest year.",
        )

    return found


ALL_RATIOS = {
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

RAW_LINES = [
    REVENUE,
    OPERATING_INCOME,
    NET_INCOME,
    OPERATING_CASH_FLOW,
    TOTAL_DEBT,
    TOTAL_EQUITY,
]


def compute_all(
    table,
    pe_current=None,
    pe_history=None,
    pb_current=None,
    pb_history=None,
):
    """Calculate all fundamental metrics used by the Fundamentals Analyst."""
    if table is None or table.empty:
        return {
            "latest": {},
            "series": {},
            "valuation": {"pe": None, "pb": None},
            "red_flags": [],
            "unavailable": sorted(
                list(ALL_RATIOS)
                + ["revenue_cagr", "pe_vs_median", "pb_vs_median"]
            ),
        }

    table = table.sort_index()
    series = {}
    values = {}
    unavailable = []

    for name, calculate in ALL_RATIOS.items():
        history = calculate(table)
        if history is not None:
            series[name] = history

        value = latest(history)
        values[name] = value
        if value is None:
            unavailable.append(name)

    growth = revenue_cagr(table)
    values["revenue_cagr"] = growth
    if growth is None:
        unavailable.append("revenue_cagr")

    for name in RAW_LINES:
        column = get_column(table, name)
        if column is not None:
            series[name] = column

    valuation = {
        "pe": valuation_vs_median(pe_current, pe_history),
        "pb": valuation_vs_median(pb_current, pb_history),
    }
    for name, result in valuation.items():
        if result is None:
            unavailable.append(f"{name}_vs_median")

    return {
        "latest": values,
        "series": series,
        "valuation": valuation,
        "red_flags": red_flags(table),
        "unavailable": sorted(unavailable),
    }
