"""Fetch company profile, prices, and benchmark data from Yahoo Finance."""

import pandas as pd
import yfinance as yf

from src.components.logging import get_logger
from src.tools import kpi, ratios

log = get_logger(__name__)
REQUEST_TIMEOUT = 20
VALUATION_LOOKBACK_DAYS = 40


def _clean_index(series):
    """Remove timezone information from a price index when needed."""
    if (
        isinstance(series.index, pd.DatetimeIndex)
        and series.index.tz is not None
    ):
        series = series.copy()
        series.index = series.index.tz_localize(None)
    return series


def fetch_prices(symbol, start=None, end=None):
    """Return adjusted closing prices for one symbol."""
    try:
        history = yf.Ticker(symbol).history(
            start=start,
            end=end,
            auto_adjust=True,
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as error:
        log.error("Price fetch failed for %s: %s", symbol, error)
        return pd.Series(dtype=float)

    if history is None or history.empty or "Close" not in history:
        return pd.Series(dtype=float)

    return _clean_index(history["Close"].astype(float))


def fetch_profile(symbol):
    """Return the company fields required by the workflow."""
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception as error:
        log.warning("Profile fetch failed for %s: %s", symbol, error)
        info = {}

    return {
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "currency": info.get("currency"),
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
    }


def valuation_history(prices, statements):
    """Calculate historical P/E and P/B values at fiscal year ends."""
    empty = {"pe_history": None, "pb_history": None}
    if prices is None or prices.empty or statements is None or statements.empty:
        return empty
    if "shares_outstanding" not in statements.columns:
        return empty

    prices = _clean_index(prices).sort_index()
    pe_values = {}
    pb_values = {}

    for period_end in statements.index:
        price_window = prices.loc[:period_end]
        if price_window.empty:
            continue
        if (period_end - price_window.index[-1]).days > VALUATION_LOOKBACK_DAYS:
            continue

        shares = statements.at[period_end, "shares_outstanding"]
        if pd.isna(shares) or shares <= 0:
            continue

        market_value = float(price_window.iloc[-1]) * float(shares)

        profit = None
        if ratios.NET_INCOME in statements.columns:
            profit = statements.at[period_end, ratios.NET_INCOME]

        equity = None
        if ratios.TOTAL_EQUITY in statements.columns:
            equity = statements.at[period_end, ratios.TOTAL_EQUITY]

        if profit is not None and not pd.isna(profit) and profit > 0:
            pe_values[period_end] = market_value / float(profit)
        if equity is not None and not pd.isna(equity) and equity > 0:
            pb_values[period_end] = market_value / float(equity)

    return {
        "pe_history": (
            pd.Series(pe_values).sort_index() if pe_values else None
        ),
        "pb_history": (
            pd.Series(pb_values).sort_index() if pb_values else None
        ),
    }


def fetch_market_data(ticker, start, end):
    """Return stock and benchmark prices for the selected period."""
    prices = fetch_prices(ticker, start, end)
    benchmark_symbol = kpi.benchmark_for(ticker)
    benchmark_prices = fetch_prices(benchmark_symbol, start, end)

    error = None
    if prices.empty:
        error = f"No price data found for {ticker} between {start} and {end}."

    return {
        "prices": prices,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_prices": benchmark_prices,
        "error": error,
    }
