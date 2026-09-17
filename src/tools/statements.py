"""Fetch and normalize annual financial statements from Yahoo Finance."""

import pandas as pd
import yfinance as yf

from src import cache, config
from src.tools import ratios

log = config.get_logger(__name__)

CACHE_MAX_AGE_HOURS = config.CACHE_HOURS_STATEMENTS
DEFAULT_YEARS = config.STATEMENT_YEARS

FIELD_MAP = {
    ratios.REVENUE: ["Total Revenue", "Operating Revenue"],
    ratios.OPERATING_INCOME: [
        "Operating Income",
        "Total Operating Income As Reported",
    ],
    ratios.NET_INCOME: [
        "Net Income",
        "Net Income Common Stockholders",
        "Net Income From Continuing Operation Net Minority Interest",
    ],
    ratios.EBIT: ["EBIT"],
    ratios.INTEREST_EXPENSE: [
        "Interest Expense",
        "Interest Expense Non Operating",
        "Total Other Finance Cost",
    ],
    ratios.OPERATING_CASH_FLOW: [
        "Operating Cash Flow",
        "Cash Flow From Continuing Operating Activities",
    ],
    ratios.CAPEX: [
        "Capital Expenditure",
        "Capital Expenditure Reported",
        "Purchase Of PPE",
    ],
    ratios.TOTAL_DEBT: ["Total Debt"],
    ratios.TOTAL_EQUITY: [
        "Stockholders Equity",
        "Common Stock Equity",
        "Total Equity Gross Minority Interest",
    ],
    ratios.TOTAL_ASSETS: ["Total Assets"],
    ratios.CURRENT_LIABILITIES: [
        "Current Liabilities",
        "Total Current Liabilities",
    ],
    "shares_outstanding": [
        "Ordinary Shares Number",
        "Share Issued",
        "Diluted Average Shares",
        "Basic Average Shares",
    ],
}

DEBT_PARTS = ["Long Term Debt", "Current Debt"]


def _empty_result(error, data_source="unavailable"):
    """Return the standard empty response for failed statement fetches."""
    return {
        "data": pd.DataFrame(),
        "missing": sorted(FIELD_MAP),
        "currency": None,
        "years": 0,
        "period_end": None,
        "data_source": data_source,
        "error": error,
    }


def _find_row(frames, candidates):
    """Return the first usable Yahoo row matching any candidate name."""
    for frame in frames:
        if frame is None or frame.empty:
            continue

        for name in candidates:
            if name not in frame.index:
                continue

            values = pd.to_numeric(frame.loc[name], errors="coerce")
            if not values.dropna().empty:
                return values

    return None


def _rebuild_total_debt(frames):
    """Add reported long- and short-term debt when total debt is absent."""
    parts = [_find_row(frames, [name]) for name in DEBT_PARTS]
    parts = [part for part in parts if part is not None]

    if not parts:
        return None

    total = parts[0]
    for part in parts[1:]:
        total = total.add(part, fill_value=0)
    return total


def _fetch_raw(ticker):
    """Fetch Yahoo's annual statements and company profile."""
    handle = yf.Ticker(ticker)

    try:
        info = handle.info or {}
    except Exception:
        info = {}

    return {
        "income": handle.income_stmt,
        "balance": handle.balance_sheet,
        "cashflow": handle.cashflow,
        "info": info,
    }


def _load_raw(ticker, use_cache):
    """Fetch statement data directly or through the disk cache."""
    key = f"{ticker}:statements"

    if not use_cache:
        return _fetch_raw(ticker), "live"

    raw = cache.cached(
        "statements",
        key,
        lambda: _fetch_raw(ticker),
        max_age_hours=CACHE_MAX_AGE_HOURS,
    )
    return raw, cache.freshness("statements", key)


def _statement_frames(raw):
    """Return only non-empty statement DataFrames."""
    frames = [raw.get("income"), raw.get("balance"), raw.get("cashflow")]
    return [
        frame
        for frame in frames
        if isinstance(frame, pd.DataFrame) and not frame.empty
    ]


def _normalize_fields(frames):
    """Map Yahoo row names to the canonical columns used by ratios.py."""
    columns = {}
    missing = []

    for canonical, candidates in FIELD_MAP.items():
        values = _find_row(frames, candidates)

        if values is None and canonical == ratios.TOTAL_DEBT:
            values = _rebuild_total_debt(frames)

        if values is None:
            missing.append(canonical)
        else:
            columns[canonical] = values

    return columns, missing


def fetch_statements(ticker, years=DEFAULT_YEARS, use_cache=True):
    """Return normalized annual statements for one ticker."""
    try:
        raw, data_source = _load_raw(ticker, use_cache)
    except Exception as error:
        return _empty_result(
            f"could not fetch statements for {ticker}: {error}"
        )

    frames = _statement_frames(raw)
    if not frames:
        return _empty_result(
            f"Yahoo Finance returned no statement data for {ticker}",
            data_source,
        )

    columns, missing = _normalize_fields(frames)
    if not columns:
        return _empty_result(
            f"no recognisable line items for {ticker}",
            data_source,
        )

    data = pd.DataFrame(columns)
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data[data.index.notna()].sort_index().tail(years)

    if missing:
        log.warning(
            "%s: no data for %s - reported as unavailable, not estimated",
            ticker,
            ", ".join(missing),
        )

    log.info(
        "%s: %d years of statements, %d of %d fields present (%s)",
        ticker,
        len(data),
        len(columns),
        len(FIELD_MAP),
        data_source,
    )

    info = raw.get("info") or {}
    return {
        "data": data,
        "missing": sorted(missing),
        "currency": info.get("currency"),
        "years": len(data),
        "period_end": data.index[-1].date().isoformat() if len(data) else None,
        "data_source": data_source,
        "error": None,
    }


def describe_gaps(result):
    """Return a plain-English description of missing statement data."""
    if result.get("error"):
        return result["error"]

    missing = [
        name
        for name in result.get("missing", [])
        if name != "shares_outstanding"
    ]

    if not missing:
        return (
            f"Full statement data available for "
            f"{result.get('years', 0)} financial years."
        )

    readable = ", ".join(name.replace("_", " ") for name in missing)
    return (
        f"Statement data covers {result.get('years', 0)} financial years. "
        f"Not reported by the data provider: {readable}. "
        "Any ratio needing these is shown as unavailable rather than estimated."
    )
