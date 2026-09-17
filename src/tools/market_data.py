"""Fetch prices, company profile data, and benchmark data from Yahoo Finance."""

import datetime as dt

import pandas as pd
import yfinance as yf

from src import cache, config
from src.tools import kpi, ratios

log = config.get_logger(__name__)

CACHE_MAX_AGE_HOURS = config.CACHE_HOURS_PRICES
VALUATION_LOOKBACK_DAYS = 40
REQUEST_TIMEOUT = 20


def _naive(prices):
    """Remove timezone information from a price index when present."""
    if isinstance(prices.index, pd.DatetimeIndex) and prices.index.tz is not None:
        prices = prices.copy()
        prices.index = prices.index.tz_localize(None)
    return prices


def _fetch_closes(symbol, start, end):
    """Fetch adjusted closing prices for one symbol."""
    history = yf.Ticker(symbol).history(
        start=start,
        end=end,
        auto_adjust=True,
        timeout=REQUEST_TIMEOUT,
    )
    if history is None or history.empty or "Close" not in history:
        return pd.Series(dtype=float)
    return _naive(history["Close"].astype(float))


def _fetch_prices_with_source(symbol, start=None, end=None, use_cache=True):
    """Return closing prices together with ``live/cached/unavailable`` source."""
    key = f"{symbol}:{start}:{end}"
    try:
        if use_cache:
            return cache.cached(
                "prices",
                key,
                lambda: _fetch_closes(symbol, start, end),
                max_age_hours=CACHE_MAX_AGE_HOURS,
            )
        return _fetch_closes(symbol, start, end), "live"
    except Exception as error:
        log.error("price fetch failed for %s: %s", symbol, error)
        return pd.Series(dtype=float), "unavailable"


def fetch_prices(symbol, start=None, end=None, use_cache=True):
    """Return closing prices for one symbol. Empty Series means unavailable."""
    prices, _ = _fetch_prices_with_source(symbol, start, end, use_cache)
    return prices


def _fetch_info(symbol):
    """Fetch raw Yahoo profile data.

    Provider errors are allowed to propagate so the cache can use an older
    profile instead of caching a temporary failure as an empty result.
    """
    return yf.Ticker(symbol).info or {}


def fetch_profile(symbol, use_cache=True):
    """Return the company fields used by the agents."""
    try:
        if use_cache:
            info, source = cache.cached(
                "profile",
                symbol,
                lambda: _fetch_info(symbol),
                max_age_hours=CACHE_MAX_AGE_HOURS,
            )
        else:
            info = _fetch_info(symbol)
            source = "live"
    except Exception as error:
        log.warning("profile fetch failed for %s: %s", symbol, error)
        info = {}
        source = "unavailable"

    return {
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "data_source": source if info else "unavailable",
        "shares_outstanding": info.get("sharesOutstanding"),
        "business_summary": (info.get("longBusinessSummary") or "")[:1200] or None,
    }


def valuation_history(prices, statements):
    """Rebuild historical P/E and P/B values at fiscal year ends."""
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

        if (period_end - window.index[-1]).days > VALUATION_LOOKBACK_DAYS:
            continue

        price = float(window.iloc[-1])
        shares = statements.at[period_end, "shares_outstanding"]
        if pd.isna(shares) or shares <= 0:
            continue

        market_value = price * float(shares)
        profit = (
            statements.at[period_end, ratios.NET_INCOME]
            if ratios.NET_INCOME in statements.columns
            else None
        )
        equity = (
            statements.at[period_end, ratios.TOTAL_EQUITY]
            if ratios.TOTAL_EQUITY in statements.columns
            else None
        )

        if profit is not None and not pd.isna(profit) and profit > 0:
            pe_values[period_end] = market_value / float(profit)
        if equity is not None and not pd.isna(equity) and equity > 0:
            pb_values[period_end] = market_value / float(equity)

    return {
        "pe_history": pd.Series(pe_values).sort_index() if pe_values else None,
        "pb_history": pd.Series(pb_values).sort_index() if pb_values else None,
    }


def fetch_market_data(ticker, start=None, end=None, statements=None, use_cache=True):
    """Return the price data needed for analysis and optional valuation history."""
    prices, price_source = _fetch_prices_with_source(ticker, start, end, use_cache)
    benchmark_symbol = kpi.benchmark_for(ticker)
    benchmark_prices = fetch_prices(benchmark_symbol, start, end, use_cache)
    profile = fetch_profile(ticker, use_cache)

    valuation = {"pe_history": None, "pb_history": None}
    if statements is not None and not statements.empty:
        history_start = (statements.index[0] - dt.timedelta(days=60)).date().isoformat()
        wide_prices = fetch_prices(ticker, history_start, None, use_cache)
        if not wide_prices.empty:
            valuation = valuation_history(wide_prices, statements)

    log.info(
        "%s: %d price rows, benchmark %s (%d rows)",
        ticker,
        len(prices),
        benchmark_symbol,
        len(benchmark_prices),
    )

    error = None
    if prices.empty:
        error = (
            f"No price data for {ticker} between {start} and {end}. "
            "Check the ticker symbol and the date range."
        )
        price_source = "unavailable"

    return {
        "prices": prices,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_prices": benchmark_prices,
        "profile": profile,
        "pe_current": profile.get("trailing_pe"),
        "pb_current": profile.get("price_to_book"),
        "pe_history": valuation["pe_history"],
        "pb_history": valuation["pb_history"],
        "data_source": price_source,
        "error": error,
    }
