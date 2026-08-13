"""Prices, the benchmark index, and company profile — from Yahoo Finance.

This module fetches; it does not judge. Everything it returns is handed to
`kpi.py` and `ratios.py` for the arithmetic. The one calculation done here is
the historical P/E and P/B series, because building it needs prices and
statements side by side — and it is still plain division, not an estimate.
"""

import datetime as dt

import pandas as pd
import yfinance as yf

from src import cache, config
from src.tools import kpi, ratios

log = config.get_logger(__name__)

CACHE_MAX_AGE_HOURS = config.CACHE_HOURS_PRICES
VALUATION_LOOKBACK_DAYS = 40      # nearest trading day to a fiscal year end


def _naive(prices):
    """Strip the timezone from a price index.

    Yahoo returns exchange-local timestamps, but fiscal period ends are plain
    dates. Comparing the two without this raises, so they are put on the same
    footing before anything is looked up.
    """
    if isinstance(prices.index, pd.DatetimeIndex) and prices.index.tz is not None:
        prices = prices.copy()
        prices.index = prices.index.tz_localize(None)
    return prices


def _fetch_closes(symbol, start, end):
    """Adjusted closing prices for one symbol over a date range."""
    history = yf.Ticker(symbol).history(start=start, end=end, auto_adjust=True)
    if history is None or history.empty or "Close" not in history:
        return pd.Series(dtype=float)
    return _naive(history["Close"].astype(float))


def fetch_prices(symbol, start=None, end=None, use_cache=True):
    """Closing prices, cached by symbol and date range. Empty Series on failure."""
    key = f"{symbol}:{start}:{end}"
    try:
        if use_cache:
            return cache.cached("prices", key, lambda: _fetch_closes(symbol, start, end),
                                max_age_hours=CACHE_MAX_AGE_HOURS)
        return _fetch_closes(symbol, start, end)
    except Exception as error:
        log.error("price fetch failed for %s: %s", symbol, error)
        return pd.Series(dtype=float)


def _fetch_info(symbol):
    try:
        return yf.Ticker(symbol).info or {}
    except Exception:
        return {}


def fetch_profile(symbol, use_cache=True):
    """Company name, sector, currency, and today's headline multiples."""
    try:
        if use_cache:
            info = cache.cached("profile", symbol, lambda: _fetch_info(symbol),
                                max_age_hours=CACHE_MAX_AGE_HOURS)
        else:
            info = _fetch_info(symbol)
    except Exception:
        info = {}

    return {
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "business_summary": (info.get("longBusinessSummary") or "")[:1200] or None,
    }


def valuation_history(prices, statements):
    """P/E and P/B as they stood at each past fiscal year end.

    Market value at a year end is that year's share count times the closing
    price nearest to it; dividing by that year's profit and equity gives the
    multiple the market was actually paying back then. That history is what
    `ratios.valuation_vs_median` compares today's multiple against.
    """
    empty = {"pe_history": None, "pb_history": None}
    if prices is None or prices.empty or statements is None or statements.empty:
        return empty
    if "shares_outstanding" not in statements.columns:
        return empty

    prices = _naive(prices).sort_index()
    pe_values: dict[pd.Timestamp, float] = {}
    pb_values: dict[pd.Timestamp, float] = {}

    for period_end in statements.index:
        window = prices.loc[:period_end]
        if window.empty:
            continue
        # Ignore a price that is far from the year end rather than pairing a
        # year-end profit with a price from a different era.
        if (period_end - window.index[-1]).days > VALUATION_LOOKBACK_DAYS:
            continue
        price = float(window.iloc[-1])
        shares = statements.at[period_end, "shares_outstanding"]
        if pd.isna(shares) or shares <= 0:
            continue
        market_value = price * float(shares)

        profit = statements.at[period_end, ratios.NET_INCOME] \
            if ratios.NET_INCOME in statements.columns else None
        equity = statements.at[period_end, ratios.TOTAL_EQUITY] \
            if ratios.TOTAL_EQUITY in statements.columns else None

        if profit is not None and not pd.isna(profit) and profit > 0:
            pe_values[period_end] = market_value / float(profit)
        if equity is not None and not pd.isna(equity) and equity > 0:
            pb_values[period_end] = market_value / float(equity)

    return {
        "pe_history": pd.Series(pe_values).sort_index() if pe_values else None,
        "pb_history": pd.Series(pb_values).sort_index() if pb_values else None,
    }


def fetch_market_data(ticker, start=None, end=None, statements=None, use_cache=True):
    """Everything price-related for one company, in one call.

    Fetches the stock over the requested window, the right index to judge it
    against, the profile, and enough extra price history to rebuild the
    valuation multiples of past years.
    """
    prices = fetch_prices(ticker, start, end, use_cache)
    benchmark_symbol = kpi.benchmark_for(ticker)
    benchmark_prices = fetch_prices(benchmark_symbol, start, end, use_cache)
    profile = fetch_profile(ticker, use_cache)

    valuation = {"pe_history": None, "pb_history": None}
    if statements is not None and not statements.empty:
        # Valuation history needs prices going back to the earliest statement,
        # which is usually further back than the window the user asked about.
        history_start = (statements.index[0] - dt.timedelta(days=60)).date().isoformat()
        wide_prices = fetch_prices(ticker, history_start, None, use_cache)
        if not wide_prices.empty:
            valuation = valuation_history(wide_prices, statements)

    log.info("%s: %d price rows, benchmark %s (%d rows)",
             ticker, len(prices), benchmark_symbol, len(benchmark_prices))

    error = None
    if prices.empty:
        error = (f"No price data for {ticker} between {start} and {end}. "
                 "Check the ticker symbol and the date range.")

    return {
        "prices": prices,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_prices": benchmark_prices,
        "profile": profile,
        "pe_current": profile.get("trailing_pe"),
        "pb_current": profile.get("price_to_book"),
        "pe_history": valuation["pe_history"],
        "pb_history": valuation["pb_history"],
        "error": error,
    }
