"""Deterministic price-performance and risk calculations."""

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252
CALENDAR_DAYS_PER_YEAR = 365.25
MA_SHORT = 50
MA_LONG = 200
DEFAULT_RISK_FREE_RATE = 0.0

BENCHMARKS = {
    ".NS": "^NSEI",
    ".BO": "^BSESN",
    ".L": "^FTSE",
    ".TO": "^GSPTSE",
}
DEFAULT_BENCHMARK = "^GSPC"


def benchmark_for(ticker):
    """Return the benchmark index for a ticker's exchange suffix."""
    for ending, index in BENCHMARKS.items():
        if ticker.upper().endswith(ending):
            return index
    return DEFAULT_BENCHMARK


def clean(prices):
    """Return sorted positive numeric prices, or None when unavailable."""
    if prices is None or len(prices) == 0:
        return None

    numbers = pd.to_numeric(
        pd.Series(prices),
        errors="coerce",
    ).dropna().sort_index()
    numbers = numbers[numbers > 0]
    return None if numbers.empty else numbers


def years_covered(prices):
    """Return the time span of a price series in years."""
    if len(prices) < 2:
        return None

    try:
        days = (
            pd.Timestamp(prices.index[-1])
            - pd.Timestamp(prices.index[0])
        ).days
    except (TypeError, ValueError):
        days = (
            (len(prices) - 1)
            / TRADING_DAYS_PER_YEAR
            * CALENDAR_DAYS_PER_YEAR
        )

    if days <= 0:
        return None
    return days / CALENDAR_DAYS_PER_YEAR


def daily_returns(prices):
    """Return daily percentage price changes."""
    priced = clean(prices)
    if priced is None or len(priced) < 2:
        return None
    return (priced / priced.shift(1) - 1).dropna()


def latest_value(column):
    """Return the latest non-null value as a float."""
    if column is None:
        return None
    usable = column.dropna()
    if usable.empty:
        return None
    return float(usable.iloc[-1])


def total_return(prices):
    """Return total price change from the first close to the last."""
    priced = clean(prices)
    if priced is None or len(priced) < 2:
        return None
    return float(priced.iloc[-1] / priced.iloc[0] - 1)


def annualised_return(prices):
    """Return total price change expressed as an annual rate."""
    priced = clean(prices)
    if priced is None or len(priced) < 2:
        return None

    years = years_covered(priced)
    if years is None or years <= 0:
        return None

    return float(
        (priced.iloc[-1] / priced.iloc[0]) ** (1 / years) - 1
    )


def volatility(prices):
    """Return annualised standard deviation of daily returns."""
    moves = daily_returns(prices)
    if moves is None or len(moves) < 2:
        return None
    return float(moves.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown(prices):
    """Return the largest peak-to-trough decline."""
    priced = clean(prices)
    if priced is None or len(priced) < 2:
        return None

    peaks = priced.cummax()
    return float((priced / peaks - 1).min())


def sharpe_ratio(prices, risk_free_rate=DEFAULT_RISK_FREE_RATE):
    """Return annualised excess return divided by volatility."""
    yearly = annualised_return(prices)
    bounce = volatility(prices)
    if yearly is None or bounce is None or bounce == 0:
        return None
    return float((yearly - risk_free_rate) / bounce)


def moving_average(prices, window):
    """Return a rolling price average for the requested window."""
    priced = clean(prices)
    if priced is None:
        return None
    return priced.rolling(window=window, min_periods=window).mean()


def moving_average_summary(prices):
    """Compare the latest price with its 50-day and 200-day averages."""
    priced = clean(prices)
    price = latest_value(priced)
    short = latest_value(moving_average(prices, MA_SHORT))
    long = latest_value(moving_average(prices, MA_LONG))

    if price is None or short is None or long is None:
        trend = "not enough price history to judge the trend"
    elif price > short and price > long:
        trend = (
            f"price is above both its {MA_SHORT}-day and "
            f"{MA_LONG}-day average"
        )
    elif price < short and price < long:
        trend = (
            f"price is below both its {MA_SHORT}-day and "
            f"{MA_LONG}-day average"
        )
    elif price > long:
        trend = (
            f"price is above its {MA_LONG}-day average but below its "
            f"{MA_SHORT}-day"
        )
    else:
        trend = (
            f"price is above its {MA_SHORT}-day average but below its "
            f"{MA_LONG}-day"
        )

    return {
        "price": price,
        f"ma_{MA_SHORT}": short,
        f"ma_{MA_LONG}": long,
        "trend": trend,
    }


def return_vs_benchmark(prices, index_prices):
    """Compare stock and benchmark returns over their shared trading days."""
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

    return {
        "stock_return": share_return,
        "benchmark_return": index_return,
        "excess_return": gap,
        "days_compared": len(shared_days),
        "verdict": verdict,
    }


def compute_all(
    prices,
    benchmark_prices=None,
    risk_free_rate=DEFAULT_RISK_FREE_RATE,
):
    """Calculate all price metrics used by the Data Analyst."""
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

    return {
        "latest": values,
        "series": series,
        "trend": trend["trend"],
        "benchmark": return_vs_benchmark(priced, benchmark_prices),
    }
