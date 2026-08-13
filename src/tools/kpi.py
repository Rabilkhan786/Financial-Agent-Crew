"""Price-based KPIs — pure pandas/numpy, no LLM and no network.

Same rule as `ratios.py`: every number here is computed in code so it can be
unit tested and checked by hand. The LLM is handed the results and asked what
they mean; it is never asked to work them out.

The input is a pandas Series of closing prices indexed by date, oldest first.
`market_data.py` is responsible for fetching and shaping that, so this module
never has to know that yfinance exists.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# --- Constants --------------------------------------------------------------
TRADING_DAYS_PER_YEAR = 252       # the usual count of market days in a year
CALENDAR_DAYS_PER_YEAR = 365.25   # includes leap years, for elapsed-time maths
MA_SHORT = 50
MA_LONG = 200
DEFAULT_RISK_FREE_RATE = 0.0      # the caller supplies a real one; see sharpe_ratio

# Which index a ticker is judged against. Beating the market only means
# something if it is the right market, so this is chosen from the suffix
# Yahoo Finance uses rather than assumed to be the S&P 500.
BENCHMARKS = {".NS": "^NSEI", ".BO": "^BSESN", ".L": "^FTSE", ".TO": "^GSPTSE"}
DEFAULT_BENCHMARK = "^GSPC"


def benchmark_for(ticker: str) -> str:
    """The index a ticker should be compared against, from its exchange suffix."""
    for suffix, index in BENCHMARKS.items():
        if ticker.upper().endswith(suffix):
            return index
    return DEFAULT_BENCHMARK


# --- Small helpers ----------------------------------------------------------

def _clean(prices: pd.Series | None) -> pd.Series | None:
    """Sorted, numeric, positive closing prices — or None if there are none.

    Zero and negative prices are dropped rather than divided by: they are data
    errors, and a return calculated from one is worse than no return at all.
    """
    if prices is None or len(prices) == 0:
        return None
    values = pd.to_numeric(pd.Series(prices), errors="coerce").dropna().sort_index()
    values = values[values > 0]
    if values.empty:
        return None
    return values


def _years_covered(prices: pd.Series) -> float | None:
    """How many years the price history actually spans."""
    if len(prices) < 2:
        return None
    start, end = prices.index[0], prices.index[-1]
    try:
        days = (pd.Timestamp(end) - pd.Timestamp(start)).days
    except (TypeError, ValueError):
        # A non-date index (plain row numbers, say) — fall back to trading days.
        days = (len(prices) - 1) / TRADING_DAYS_PER_YEAR * CALENDAR_DAYS_PER_YEAR
    if days <= 0:
        return None
    return days / CALENDAR_DAYS_PER_YEAR


def daily_returns(prices: pd.Series | None) -> pd.Series | None:
    """Day-to-day percentage change in price."""
    cleaned = _clean(prices)
    if cleaned is None or len(cleaned) < 2:
        return None
    return (cleaned / cleaned.shift(1) - 1).dropna()


# --- Return -----------------------------------------------------------------

def total_return(prices: pd.Series | None) -> float | None:
    """Price change from the first day to the last, ignoring dividends."""
    cleaned = _clean(prices)
    if cleaned is None or len(cleaned) < 2:
        return None
    return float(cleaned.iloc[-1] / cleaned.iloc[0] - 1)


def annualised_return(prices: pd.Series | None) -> float | None:
    """Total return restated as a per-year rate (CAGR) over the period covered."""
    cleaned = _clean(prices)
    if cleaned is None or len(cleaned) < 2:
        return None
    years = _years_covered(cleaned)
    if years is None or years <= 0:
        return None
    return float((cleaned.iloc[-1] / cleaned.iloc[0]) ** (1 / years) - 1)


# --- Risk -------------------------------------------------------------------

def volatility(prices: pd.Series | None) -> float | None:
    """Annualised standard deviation of daily returns.

    Daily wobble is scaled up by the square root of the number of trading days,
    which is the standard convention for putting it on a yearly footing.
    """
    returns = daily_returns(prices)
    if returns is None or len(returns) < 2:
        return None
    return float(returns.std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def max_drawdown(prices: pd.Series | None) -> float | None:
    """The worst peak-to-trough fall, as a negative fraction.

    Measures the deepest loss someone would have sat through if they had bought
    at the worst moment in the period.
    """
    cleaned = _clean(prices)
    if cleaned is None or len(cleaned) < 2:
        return None
    running_peak = cleaned.cummax()
    drawdowns = cleaned / running_peak - 1
    return float(drawdowns.min())


def sharpe_ratio(prices: pd.Series | None,
                 risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> float | None:
    """Return above the risk-free rate, per unit of volatility.

    The risk-free rate is a parameter, not a hardcoded guess: it differs by
    market and by year, and the rate actually used is reported alongside the
    result so nobody has to wonder which one it was.
    """
    annual = annualised_return(prices)
    swing = volatility(prices)
    if annual is None or swing is None or swing == 0:
        return None
    return float((annual - risk_free_rate) / swing)


# --- Trend ------------------------------------------------------------------

def moving_average(prices: pd.Series | None, window: int) -> pd.Series | None:
    """A rolling average of closing prices, blank until there is enough history."""
    cleaned = _clean(prices)
    if cleaned is None:
        return None
    return cleaned.rolling(window=window, min_periods=window).mean()


def _last_value(series: pd.Series | None) -> float | None:
    """The most recent usable value, or None. Never returns NaN."""
    if series is None:
        return None
    usable = series.dropna()
    if usable.empty:
        return None
    return float(usable.iloc[-1])


def moving_average_summary(prices: pd.Series | None) -> dict:
    """Latest price against its 50-day and 200-day averages, in plain English.

    The wording is produced here rather than by the LLM so the report cannot
    describe a stock as trading above an average it is actually below.
    """
    cleaned = _clean(prices)
    price = _last_value(cleaned)
    short = _last_value(moving_average(prices, MA_SHORT))
    long = _last_value(moving_average(prices, MA_LONG))

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

def return_vs_benchmark(prices: pd.Series | None,
                        benchmark_prices: pd.Series | None) -> dict | None:
    """Compare the stock's return with an index over the dates they share.

    Both series are trimmed to their common dates first. Comparing a return
    measured over one window against a return measured over a different one is
    the easiest way to produce a confidently wrong answer.
    """
    stock = _clean(prices)
    index = _clean(benchmark_prices)
    if stock is None or index is None:
        return None
    shared = stock.index.intersection(index.index)
    if len(shared) < 2:
        return None
    stock_return = total_return(stock.loc[shared])
    index_return = total_return(index.loc[shared])
    if stock_return is None or index_return is None:
        return None
    excess = stock_return - index_return
    if excess >= 0:
        verdict = f"beat the index by {excess:.1%}"
    else:
        verdict = f"lagged the index by {abs(excess):.1%}"
    return {"stock_return": stock_return, "benchmark_return": index_return,
            "excess_return": excess, "days_compared": len(shared), "verdict": verdict}


# --- One entry point --------------------------------------------------------

def compute_all(prices: pd.Series | None,
                benchmark_prices: pd.Series | None = None,
                risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> dict:
    """Compute every price KPI the crew uses.

    Mirrors `ratios.compute_all`: latest scalars are never NaN, anything that
    could not be computed is None and is named in `unavailable`, and the full
    series are carried through for charting.
    """
    cleaned = _clean(prices)

    latest_values = {
        "total_return": total_return(cleaned),
        "annualised_return": annualised_return(cleaned),
        "volatility": volatility(cleaned),
        "max_drawdown": max_drawdown(cleaned),
        "sharpe_ratio": sharpe_ratio(cleaned, risk_free_rate),
    }

    trend = moving_average_summary(cleaned)
    latest_values[f"ma_{MA_SHORT}"] = trend[f"ma_{MA_SHORT}"]
    latest_values[f"ma_{MA_LONG}"] = trend[f"ma_{MA_LONG}"]
    latest_values["last_close"] = trend["price"]

    series: dict[str, pd.Series] = {}
    if cleaned is not None:
        series["close"] = cleaned
        for window in (MA_SHORT, MA_LONG):
            average = moving_average(cleaned, window)
            if average is not None and not average.dropna().empty:
                series[f"ma_{window}"] = average
        returns = daily_returns(cleaned)
        if returns is not None:
            series["daily_returns"] = returns

    benchmark = return_vs_benchmark(cleaned, benchmark_prices)

    unavailable = sorted(name for name, value in latest_values.items() if value is None)
    if benchmark is None:
        unavailable.append("return_vs_benchmark")

    return {
        "latest": latest_values,
        "series": series,
        "trend": trend["trend"],
        "benchmark": benchmark,
        "risk_free_rate": risk_free_rate,
        "unavailable": sorted(unavailable),
    }
