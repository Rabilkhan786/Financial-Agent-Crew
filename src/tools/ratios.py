"""Fundamental ratios. Plain pandas and numpy, no LLM and no internet.

Every fundamental number in the report is worked out here so it can be tested
and checked by hand. The LLM only reads these numbers, it never calculates them.

Input: one table with a row per financial year (oldest first) and the columns
named below. statements.py builds that table from Yahoo data.
"""

import numpy as np
import pandas as pd

# Column names we use everywhere.
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

# Red flag limits. They live here in the open so anyone can argue with them.
CASH_CONVERSION_FLOOR = 0.70     # cash below 70% of profit, 3 years running
DEBT_TO_EQUITY_CEILING = 2.0
INTEREST_COVERAGE_FLOOR = 2.0
MARGIN_EROSION_PP = 0.03         # 3 percentage points of margin lost
PROFIT_VS_REVENUE_GAP = 0.20     # profit growing 20 points faster than sales
CAGR_YEARS = 3
VALUATION_MEDIAN_YEARS = 5
VALUATION_IN_LINE_BAND = 0.05    # within 5% of its own median = "in line"


def get_column(table, name):
    """One column as numbers, or None if it is missing or empty.

    We return None instead of guessing. If the data provider does not report
    something, the report says so.
    """
    if name not in table.columns:
        return None
    numbers = pd.to_numeric(table[name], errors="coerce")
    if numbers.dropna().empty:
        return None
    return numbers


def divide(top, bottom, positive_only=False):
    """Divide two columns. Gives a blank instead of an error or infinity.

    positive_only also blanks negative bottoms. Return on equity when equity is
    negative looks like a real number but means nothing.
    """
    if top is None or bottom is None:
        return None
    safe = bottom.astype(float).copy()
    safe[safe == 0] = np.nan
    if positive_only:
        safe[safe < 0] = np.nan
    return top.astype(float) / safe


def latest(column):
    """The most recent usable value, or None. Never returns a blank (NaN)."""
    if column is None:
        return None
    usable = column.dropna()
    if usable.empty:
        return None
    return float(usable.iloc[-1])


# --- Growth -----------------------------------------------------------------

def revenue_growth_yoy(table):
    """Revenue growth against the year before."""
    revenue = get_column(table, REVENUE)
    if revenue is None:
        return None
    last_year = revenue.shift(1)
    return divide(revenue - last_year, last_year, positive_only=True)


def revenue_cagr(table, years=CAGR_YEARS):
    """Average yearly revenue growth over the last few years."""
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


# --- Profitability ----------------------------------------------------------

def operating_margin(table):
    """Operating profit as a share of revenue."""
    return divide(get_column(table, OPERATING_INCOME), get_column(table, REVENUE),
                  positive_only=True)


def net_margin(table):
    """Net profit as a share of revenue."""
    return divide(get_column(table, NET_INCOME), get_column(table, REVENUE),
                  positive_only=True)


def return_on_equity(table):
    """Profit earned on the shareholders' money."""
    return divide(get_column(table, NET_INCOME), get_column(table, TOTAL_EQUITY),
                  positive_only=True)


def return_on_capital_employed(table):
    """Operating profit against the money tied up in the business."""
    profit = get_column(table, EBIT)
    if profit is None:
        profit = get_column(table, OPERATING_INCOME)
    assets = get_column(table, TOTAL_ASSETS)
    short_term = get_column(table, CURRENT_LIABILITIES)
    if assets is None or short_term is None:
        return None
    return divide(profit, assets - short_term, positive_only=True)


# --- Cash -------------------------------------------------------------------

def cash_conversion(table):
    """Cash from operations divided by net profit.

    Loss years are left blank because dividing cash by a loss means nothing.
    """
    return divide(get_column(table, OPERATING_CASH_FLOW), get_column(table, NET_INCOME),
                  positive_only=True)


def free_cash_flow(table):
    """Cash left after paying for equipment and buildings."""
    cash = get_column(table, OPERATING_CASH_FLOW)
    spending = get_column(table, CAPEX)
    if cash is None or spending is None:
        return None
    return cash - spending.abs()


# --- Balance sheet ----------------------------------------------------------

def debt_to_equity(table):
    """How much the company borrowed against what the owners put in."""
    return divide(get_column(table, TOTAL_DEBT), get_column(table, TOTAL_EQUITY),
                  positive_only=True)


def interest_coverage(table):
    """How many times over the profit covers the interest bill."""
    profit = get_column(table, EBIT)
    if profit is None:
        profit = get_column(table, OPERATING_INCOME)
    interest = get_column(table, INTEREST_EXPENSE)
    if interest is None:
        return None
    return divide(profit, interest.abs(), positive_only=True)


# --- Valuation --------------------------------------------------------------

def valuation_vs_median(current, history, years=VALUATION_MEDIAN_YEARS):
    """Compare a multiple with the same company's own past.

    Comparing a company with itself avoids the argument about which rivals
    count as comparable. A negative multiple is called out, not called cheap.
    """
    if current is None or history is None:
        return None
    past = pd.to_numeric(history, errors="coerce").dropna()
    past = past[past > 0].tail(years)
    if past.empty:
        return None

    middle = float(past.median())
    if current <= 0:
        return {"current": float(current), "median": middle, "years": len(past),
                "premium_pct": None,
                "verdict": "not meaningful (the multiple is negative)"}

    gap = current / middle - 1
    if abs(gap) <= VALUATION_IN_LINE_BAND:
        verdict = f"in line with its own {len(past)}-year median"
    elif gap > 0:
        verdict = f"{gap:.0%} above its own {len(past)}-year median"
    else:
        verdict = f"{abs(gap):.0%} below its own {len(past)}-year median"

    return {"current": float(current), "median": middle, "years": len(past),
            "premium_pct": float(gap), "verdict": verdict}


# --- Red flags --------------------------------------------------------------

def red_flags(table):
    """Warning rules. Fixed limits, no opinion from the model.

    Each flag quotes the numbers that set it off, so the report can state a
    figure it never had to work out.
    """
    found = []

    def add(code, severity, message):
        found.append({"code": code, "severity": severity, "message": message})

    conversion = cash_conversion(table)
    if conversion is not None:
        recent = conversion.dropna().tail(3)
        if len(recent) == 3 and (recent < CASH_CONVERSION_FLOOR).all():
            add("weak_cash_conversion", "high",
                f"Operating cash flow has stayed below {CASH_CONVERSION_FLOOR:.0%} of net "
                f"profit for three straight years (latest {recent.iloc[-1]:.2f}x). "
                "Reported profit is not turning into cash.")

    cash = get_column(table, OPERATING_CASH_FLOW)
    cash_now = latest(cash)
    if cash_now is not None and cash_now < 0:
        add("negative_operating_cash_flow", "high",
            f"Operating cash flow is negative in the latest year ({cash_now:,.0f}). "
            "The business used up cash rather than making it.")

    spare_cash = free_cash_flow(table)
    if spare_cash is not None:
        recent = spare_cash.dropna().tail(3)
        bad_years = int((recent < 0).sum())
        if len(recent) == 3 and bad_years >= 2:
            add("persistent_negative_fcf", "medium",
                f"Free cash flow was negative in {bad_years} of the last 3 years. "
                "Spending is running ahead of the cash coming in.")

    equity_now = latest(get_column(table, TOTAL_EQUITY))
    if equity_now is not None and equity_now < 0:
        add("negative_equity", "high",
            f"Shareholder equity is negative ({equity_now:,.0f}). "
            "The company owes more than it owns.")

    borrowing = latest(debt_to_equity(table))
    if borrowing is not None and borrowing > DEBT_TO_EQUITY_CEILING:
        add("high_leverage", "high",
            f"Debt to equity is {borrowing:.2f}, above the {DEBT_TO_EQUITY_CEILING:.1f} "
            "level we treat as heavily borrowed.")

    cover = latest(interest_coverage(table))
    if cover is not None and cover < INTEREST_COVERAGE_FLOOR:
        add("thin_interest_cover", "high",
            f"Operating profit covers the interest bill only {cover:.2f} times, under the "
            f"{INTEREST_COVERAGE_FLOOR:.1f}x level. There is little room if profit falls.")

    margins = operating_margin(table)
    growth_now = latest(revenue_growth_yoy(table))
    if margins is not None and growth_now is not None and growth_now > 0:
        recent = margins.dropna().tail(CAGR_YEARS + 1)
        if len(recent) >= 2:
            drop = float(recent.iloc[0] - recent.iloc[-1])
            if drop >= MARGIN_EROSION_PP:
                add("margin_erosion", "medium",
                    f"Revenue is still growing ({growth_now:.1%} in the latest year) but the "
                    f"operating margin fell from {recent.iloc[0]:.1%} to {recent.iloc[-1]:.1%}. "
                    "Growth is costing profitability.")

    profits = get_column(table, NET_INCOME)
    if profits is not None and cash is not None and growth_now is not None:
        profit_years = profits.dropna()
        cash_years = cash.dropna()
        if (len(profit_years) >= 2 and len(cash_years) >= 2
                and profit_years.iloc[-2] > 0 and growth_now > 0):
            profit_growth = float(profit_years.iloc[-1] / profit_years.iloc[-2] - 1)
            if (profit_growth > growth_now + PROFIT_VS_REVENUE_GAP
                    and cash_years.iloc[-1] < cash_years.iloc[-2]):
                add("earnings_quality", "medium",
                    f"Net profit grew {profit_growth:.1%} against revenue growth of "
                    f"{growth_now:.1%}, while cash from operations fell. The extra profit is "
                    "not showing up as cash.")

    if growth_now is not None and growth_now < 0:
        add("revenue_decline", "medium",
            f"Revenue fell {abs(growth_now):.1%} in the latest year.")

    return found


# --- Everything in one call -------------------------------------------------

# Each ratio and the function that builds its history.
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

# Raw lines kept for the charts and for checking a ratio by hand.
RAW_LINES = [REVENUE, OPERATING_INCOME, NET_INCOME, OPERATING_CASH_FLOW,
             TOTAL_DEBT, TOTAL_EQUITY]


def compute_all(table, pe_current=None, pe_history=None,
                pb_current=None, pb_history=None):
    """Work out every ratio at once.

    Latest values are never blank: anything we could not work out is None and
    is named in "unavailable", so the report can say so honestly.
    """
    if table is None or table.empty:
        return {"latest": {}, "series": {}, "valuation": {"pe": None, "pb": None},
                "red_flags": [],
                "unavailable": sorted(list(ALL_RATIOS)
                                      + ["revenue_cagr", "pe_vs_median", "pb_vs_median"])}

    table = table.sort_index()
    series = {}
    values = {}
    unavailable = []

    for name, work_out in ALL_RATIOS.items():
        history = work_out(table)
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

    valuation = {"pe": valuation_vs_median(pe_current, pe_history),
                 "pb": valuation_vs_median(pb_current, pb_history)}
    for name, result in valuation.items():
        if result is None:
            unavailable.append(f"{name}_vs_median")

    return {"latest": values, "series": series, "valuation": valuation,
            "red_flags": red_flags(table), "unavailable": sorted(unavailable)}
