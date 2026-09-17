"""Fetch prices, company profile data, and benchmark prices from Yahoo Finance."""

import datetime as dt

import pandas as pd
import yfinance as yf

from src import cache, config
from src.tools import kpi, ratios

log = config.get_logger(__name__)

CACHE_MAX_AGE_HOURS = config.CACHE_HOURS_PRICES
VALUATION_LOOKBACK_DAYS = 40
REQUEST_TIMEOUT = 20


def _without_timezone(series):
    """Remove timezone information from a DatetimeIndex when present."""
    if isinstance(series.index, pd.DatetimeIndex) and series.index.tz is not None:
        series = series.copy()
        series.index = series.index.tz_localize(None)
    return series


def _price_cache_key(symbol, start, end):
    """Return the cache key used for a price request."""
    return f"{symbol}:{start}:{end}"


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

    return _without_timezone(history["Close"].astype(float))


def fetch_prices(symbol, start=None, end=None, use_cache=True):
    """Return closing prices for a symbol, using the disk cache when enabled."""
    key = _price_cache_key(symbol, start, end)

    try:
        if not use_cache:
            return _fetch_closes(symbol, start, end)

        return cache.cached(
            "prices",
            key,
            lambda: _fetch_closes(symbol, start, end),
            max_age_hours=CACHE_MAX_AGE_HOURS,
        )
    except Exception as error:
        log.error("price fetch failed for %s: %s", symbol, error)
        return pd.Series(dtype=float)


def _fetch_info(symbol):
    """Fetch Yahoo's company profile payload."""
    try:
        return yf.Ticker(symbol).info or {}
    except Exception:
        return {}


def _load_profile_info(symbol, use_cache):
    """Fetch company profile information directly or from cache."""
    if not use_cache:
        return _fetch_info(symbol), "live"

    info = cache.cached(
        "profile",
        symbol,
        lambda: _fetch_info(symbol),
        max_age_hours=CACHE_MAX_AGE_HOURS,
    )
    return info, cache.freshness("profile", symbol)


def fetch_profile(symbol, use_cache=True):
    """Return the company profile fields used by the agents."""
    try:
        info, data_source = _load_profile_info(symbol, use_cache)
    except Exception:
        info, data_source = {}, "unavailable"

    return {
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": info.get("currency"),
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "price_to_book": info.get("priceToBook"),
        "data_source": data_source if info else "unavailable",
        "shares_outstanding": info.get("sharesOutstanding"),
        "business_summary": (
            (info.get("longBusinessSummary") or "")[:1200] or None
        ),
    }


def valuation_history(prices, statements):
    """Build historical P/E and P/B series from reported statements and prices."""
    empty = {"pe_history": None, "pb_history": None}

    if prices is None or prices.empty:
        return empty
    if statements is None or statements.empty:
        return empty
    if "shares_outstanding" not in statements.columns:
        return empty

    prices = _without_timezone(prices).sort_index()
    pe_values = {}
    pb_values = {}

    for period_end in statements.index:
        available_prices = prices.loc[:period_end]
        if available_prices.empty:
            continue

        price_date = available_prices.index[-1]
        if (period_end - price_date).days > VALUATION_LOOKBACK_DAYS:
            continue

        shares = statements.at[period_end, "shares_outstanding"]
        if pd.isna(shares) or shares <= 0:
            continue

        price = float(available_prices.iloc[-1])
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
        "pe_history": (
            pd.Series(pe_values).sort_index() if pe_values else None
        ),
        "pb_history": (
            pd.Series(pb_values).sort_index() if pb_values else None
        ),
    }


def _build_valuation_history(ticker, statements, use_cache):
    """Fetch the wider price range required for historical valuation multiples."""
    if statements is None or statements.empty:
        return {"pe_history": None, "pb_history": None}

    history_start = (
        statements.index[0] - dt.timedelta(days=60)
    ).date().isoformat()

    prices = fetch_prices(ticker, history_start, None, use_cache)
    if prices.empty:
        return {"pe_history": None, "pb_history": None}

    return valuation_history(prices, statements)


def fetch_market_data(
    ticker,
    start=None,
    end=None,
    statements=None,
    use_cache=True,
):
    """Return all market data needed by the data analyst agent."""
    prices = fetch_prices(ticker, start, end, use_cache)

    benchmark_symbol = kpi.benchmark_for(ticker)
    benchmark_prices = fetch_prices(
        benchmark_symbol,
        start,
        end,
        use_cache,
    )

    profile = fetch_profile(ticker, use_cache)
    valuation = _build_valuation_history(ticker, statements, use_cache)

    if prices.empty:
        error = (
            f"No price data for {ticker} between {start} and {end}. "
            "Check the ticker symbol and the date range."
        )
        data_source = "unavailable"
    else:
        error = None
        data_source = (
            cache.freshness(
                "prices",
                _price_cache_key(ticker, start, end),
            )
            if use_cache
            else "live"
        )

    log.info(
        "%s: %d price rows, benchmark %s (%d rows)",
        ticker,
        len(prices),
        benchmark_symbol,
        len(benchmark_prices),
    )

    return {
        "prices": prices,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_prices": benchmark_prices,
        "profile": profile,
        "pe_current": profile.get("trailing_pe"),
        "pb_current": profile.get("price_to_book"),
        "pe_history": valuation["pe_history"],
        "pb_history": valuation["pb_history"],
        "data_source": data_source,
        "error": error,
    }
