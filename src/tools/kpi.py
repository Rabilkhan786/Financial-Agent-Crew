"""Price numbers. Plain pandas and numpy, no LLM and no internet.

Same rule as ratios.py: the maths happens here so it can be tested, and the
LLM only reads the answers.

Input: closing prices as a pandas Series with dates as the index, oldest first.
"""

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365.25
MA_SHORT = 50
MA_LONG = 200
DEFAULT_RISK_FREE_RATE = 0.0

# Which index each market is judged against. Beating "the market" only means
# something if it is the right market, so we pick it from the ticker ending.
BENCHMARKS = {".NS": "^NSEI", ".BO": "^BSESN", ".L": "^FTSE", ".TO": "^GSPTSE"}
DEFAULT_BENCHMARK = "^GSPC"


def benchmark_for(ticker):
    """The index this ticker should be compared against."""
    for ending, index in BENCHMARKS.items():
        if ticker.upper().endswith(ending):
            return index
    return DEFAULT_BENCHMARK


def clean(prices):
    """Sorted, numeric, positive prices. None if there are none left.

    Zero and negative prices are data errors. Dividing by one gives a return
    that is worse than having no return at all.
    """
    if prices is None or len(prices) == 0:
        return None
    numbers = pd.to_numeric(pd.Series(prices), errors="coerce").dropna().sort_index()
    numbers = numbers[numbers > 0]
    if numbers.empty:
        return None
    return numbers


def years_covered(prices):
    """How many years the price history spans."""
    if len(prices) < 2:
        return None
    try:
        days = (pd.Timestamp(prices.index[-1]) - pd.Timestamp(prices.index[0])).days
    except (TypeError, ValueError):
        # The index is row numbers, not dates. Count trading days instead.
        days = (len(prices) - 1) / TRADING_DAYS_PER_YEAR * CALENDAR_DAYS_PER_YEAR
    if days <= 0:
        return None
    return days / CALENDAR_DAYS_PER_YEAR


def daily_returns(prices):
    """How much the price moved each day."""
    priced = clean(prices)
    if priced is None or len(priced) < 2:
        return None
    return (priced / priced.shift(1) - 1).dropna()


def latest_value(column):
    """The most recent usable value, or None. Never a blank (NaN)."""
    if column is None:
        return None
    usable = column.dropna()
    if usable.empty:
        return None
    return float(usable.iloc[-1])


# --- Return -----------------------------------------------------------------

def total_return(prices):
    """Price change from the first day to the last."""
    priced = clean(prices)
    if priced is None or len(priced) < 2:
        return None
    return float(priced.iloc[-1] / priced.iloc[0] - 1)


def annualised_return(prices):
    """The same return stated as a per-year rate."""
    priced = clean(prices)
    if priced is None or len(priced) < 2:
        return None
    years = years_covered(priced)
    if years is None or years <= 0:
        return None
    return float((priced.iloc[-1] / priced.iloc[0]) ** (1 / years) - 1)


# --- Risk -------------------------------------------------------------------

def volatility(prices):
    """How much the price bounces around, stated per year.

    Daily movement is scaled by the square root of the trading days in a year,
    which is the usual way of putting it on a yearly footing.
    """
    moves = daily_returns(prices)
    if moves is None or len(moves) < 2:
        return None
    return float(moves.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown(prices):
    """The worst fall from a peak, as a negative number.

    This is the loss someone would have sat through if they bought at the worst
    moment in the period.
    """
    priced = clean(prices)
    if priced is None or len(priced) < 2:
        return None
    peaks = priced.cummax()
    return float((priced / peaks - 1).min())


def sharpe_ratio(prices, risk_free_rate=DEFAULT_RISK_FREE_RATE):
    """Return above the safe rate, per unit of bounciness.

    The safe rate is passed in rather than hardcoded: it differs by country and
    by year, and the report states which one was used.
    """
    yearly = annualised_return(prices)
    bounce = volatility(prices)
    if yearly is None or bounce is None or bounce == 0:
        return None
    return float((yearly - risk_free_rate) / bounce)


# --- Trend ------------------------------------------------------------------

def moving_average(prices, window):
    """Average price over a window of days. Blank until there is enough data."""
    priced = clean(prices)
    if priced is None:
        return None
    return priced.rolling(window=window, min_periods=window).mean()


def moving_average_summary(prices):
    """The price against its 50 and 200 day averages, in words.

    The sentence is written here, not by the model, so the report can never say
    a share is above an average it is actually below.
    """
    priced = clean(prices)
    price = latest_value(priced)
    short = latest_value(moving_average(prices, MA_SHORT))
    long = latest_value(moving_average(prices, MA_LONG))

    if price is None or short is None or long is None:
        trend = "not enough price history to judge the trend"
    elif price > short and price > long:
        trend = f"price is above both its {MA_SHORT}-day and {MA_LONG}-day average"
    elif price < short and price < long:
        trend = f"price is below both its {MA_SHORT}-day and {MA_LONG}-day average"
    elif price > long:
        trend = f"price is above its {MA_LONG}-day average but below its {MA_SHORT}-day"
    else:
        trend = f"price is above its {MA_SHORT}-day average but below its {MA_LONG}-day"

    return {"price": price, f"ma_{MA_SHORT}": short, f"ma_{MA_LONG}": long, "trend": trend}


# --- Against the market -----------------------------------------------------

def return_vs_benchmark(prices, index_prices):
    """Compare the share with an index over the days they both traded.

    Trimming to shared dates first matters: comparing a return measured over
    one window with one measured over another gives a confidently wrong answer.
    """
    share = clean(prices)
    index = clean(index_prices)
    if share is None or index is None:
        return None

    shared_days = share.index.intersection(index.index)
    if len(shared_days) < 2:
        return None

    share_return = total_return(share.loc[shared_days])
    index_return = total_return(index.loc[shared_days])
    if share_return is None or index_return is None:
        return None

    gap = share_return - index_return
    if gap >= 0:
        verdict = f"beat the index by {gap:.1%}"
    else:
        verdict = f"lagged the index by {abs(gap):.1%}"

    return {"stock_return": share_return, "benchmark_return": index_return,
            "excess_return": gap, "days_compared": len(shared_days), "verdict": verdict}


# --- Everything in one call -------------------------------------------------

def compute_all(prices, benchmark_prices=None, risk_free_rate=DEFAULT_RISK_FREE_RATE):
    """Work out every price number at once.

    Same shape as ratios.compute_all: latest values are never blank, and
    anything missing is named in "unavailable".
    """
    priced = clean(prices)

    values = {
        "total_return": total_return(priced),
        "annualised_return": annualised_return(priced),
        "volatility": volatility(priced),
        "max_drawdown": max_drawdown(priced),
        "sharpe_ratio": sharpe_ratio(priced, risk_free_rate),
    }

    trend = moving_average_summary(priced)
    values[f"ma_{MA_SHORT}"] = trend[f"ma_{MA_SHORT}"]
    values[f"ma_{MA_LONG}"] = trend[f"ma_{MA_LONG}"]
    values["last_close"] = trend["price"]

    series = {}
    if priced is not None:
        series["close"] = priced
        for window in (MA_SHORT, MA_LONG):
            average = moving_average(priced, window)
            if average is not None and not average.dropna().empty:
                series[f"ma_{window}"] = average
        moves = daily_returns(priced)
        if moves is not None:
            series["daily_returns"] = moves

    against_index = return_vs_benchmark(priced, benchmark_prices)

    unavailable = sorted(name for name, value in values.items() if value is None)
    if against_index is None:
        unavailable.append("return_vs_benchmark")

    return {"latest": values, "series": series, "trend": trend["trend"],
            "benchmark": against_index, "risk_free_rate": risk_free_rate,
            "unavailable": sorted(unavailable)}
