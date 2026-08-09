"""Risk math — plain Python, no API and no LLM.

This is the deliberate design choice behind the Risk agent: instead of paying for
a separate "risk data" API, we compute risk measures ourselves from the price
history the Financial side already fetched. Everything here is standard-library
arithmetic a person can check by hand, which is exactly why the Risk agent's
numbers are trustworthy and cheap.

Prices must be in chronological order (oldest first).
"""

import statistics
from itertools import pairwise
from math import sqrt

TRADING_DAYS_PER_YEAR = 252  # the usual count of US trading days in a year


def daily_returns(prices: list[float]) -> list[float]:
    """Turn a price series into simple day-over-day returns.

    A return is (today / yesterday) - 1. With N prices you get N-1 returns.
    """
    if len(prices) < 2:
        raise ValueError("Need at least two prices to compute a return.")
    returns = []
    # pairwise([100, 110, 121]) yields (100, 110) then (110, 121).
    for yesterday, today in pairwise(prices):
        if yesterday == 0:
            raise ValueError("Encountered a zero price; cannot compute a return.")
        returns.append(today / yesterday - 1)
    return returns


def annualized_volatility(prices: list[float], periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    """Annualized volatility = the day-to-day return std dev scaled up to a year.

    We take the sample standard deviation of daily returns (how much they bounce
    around) and multiply by sqrt(252), the standard way to express a daily wobble
    as a yearly one. Needs at least 3 prices (2 returns) for a sample std dev.
    """
    returns = daily_returns(prices)
    if len(returns) < 2:
        raise ValueError("Need at least three prices for a volatility estimate.")
    return statistics.stdev(returns) * sqrt(periods_per_year)


def max_drawdown(prices: list[float]) -> float:
    """The worst peak-to-trough drop in the series, as a positive fraction.

    We walk the prices tracking the highest point seen so far, and record the
    largest percentage fall from a peak. A result of 0.25 means "at its worst,
    the price was 25% below its previous high." A flat or rising series gives 0.
    """
    if len(prices) < 2:
        raise ValueError("Need at least two prices to compute a drawdown.")
    peak = prices[0]
    worst = 0.0
    for price in prices:
        peak = max(peak, price)
        drop = (price - peak) / peak  # zero or negative
        worst = min(worst, drop)
    return abs(worst)
