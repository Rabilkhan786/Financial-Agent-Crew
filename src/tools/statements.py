"""Annual financial statements from Yahoo Finance, in the shape `ratios.py` expects.

Yahoo names its line items its own way ("Total Revenue", "Stockholders Equity",
"Capital Expenditure"). This module is the only place that knows those names.
It maps them onto the canonical columns in `ratios.py`, so the maths layer stays
provider-agnostic and could be pointed at a different source without changing a
single ratio.

Rule 5 of the project: a line item Yahoo does not have is reported as missing,
never inferred, never quietly replaced by a similar-looking one. Gaps are common
for smaller companies and for anyone reporting unusual line items, and a report
that admits a gap is worth more than one that fills it with a guess.
"""

import pandas as pd
import yfinance as yf

from src import cache, config
from src.tools import ratios

log = config.get_logger(__name__)

CACHE_MAX_AGE_HOURS = config.CACHE_HOURS_STATEMENTS
DEFAULT_YEARS = config.STATEMENT_YEARS

# Canonical column -> the Yahoo row names to try, in order of preference.
# Several alternatives are listed because Yahoo uses different labels for
# different companies and exchanges.
FIELD_MAP = {
    ratios.REVENUE: ["Total Revenue", "Operating Revenue"],
    ratios.OPERATING_INCOME: ["Operating Income", "Total Operating Income As Reported"],
    ratios.NET_INCOME: ["Net Income", "Net Income Common Stockholders",
                        "Net Income From Continuing Operation Net Minority Interest"],
    ratios.EBIT: ["EBIT"],
    ratios.INTEREST_EXPENSE: ["Interest Expense", "Interest Expense Non Operating",
                              "Total Other Finance Cost"],
    ratios.OPERATING_CASH_FLOW: ["Operating Cash Flow",
                                 "Cash Flow From Continuing Operating Activities"],
    ratios.CAPEX: ["Capital Expenditure", "Capital Expenditure Reported", "Purchase Of PPE"],
    ratios.TOTAL_DEBT: ["Total Debt"],
    ratios.TOTAL_EQUITY: ["Stockholders Equity", "Common Stock Equity",
                          "Total Equity Gross Minority Interest"],
    ratios.TOTAL_ASSETS: ["Total Assets"],
    ratios.CURRENT_LIABILITIES: ["Current Liabilities", "Total Current Liabilities"],
    "shares_outstanding": ["Ordinary Shares Number", "Share Issued",
                           "Diluted Average Shares", "Basic Average Shares"],
}

# Used only when "Total Debt" is absent: debt is the sum of its long and short parts.
DEBT_PARTS = ["Long Term Debt", "Current Debt"]


def _row(frames, candidates):
    """The first matching row from whichever statement contains it."""
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for name in candidates:
            if name in frame.index:
                values = pd.to_numeric(frame.loc[name], errors="coerce")
                if not values.dropna().empty:
                    return values
    return None


def _rebuild_total_debt(frames):
    """Add up the debt components when Yahoo gives no single total.

    This is arithmetic on figures Yahoo did report, not an estimate of a figure
    it did not — which is why it is allowed under the no-inference rule.
    """
    parts = [_row(frames, [name]) for name in DEBT_PARTS]
    present = [part for part in parts if part is not None]
    if not present:
        return None
    total = present[0]
    for part in present[1:]:
        total = total.add(part, fill_value=0)
    return total


def _fetch_raw(ticker):
    """The three annual statements plus the profile, straight from Yahoo."""
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


def fetch_statements(ticker, years=DEFAULT_YEARS, use_cache=True):
    """Annual statements for one company, shaped for `ratios.compute_all`.

    Returns the tidy DataFrame (one row per fiscal year, oldest first), the list
    of canonical fields Yahoo had nothing for, and the reporting currency. Never
    raises: a total failure comes back as an empty frame with an error message.
    """
    key = f"{ticker}:statements"

    try:
        if use_cache:
            raw = cache.cached("statements", key, lambda: _fetch_raw(ticker),
                               max_age_hours=CACHE_MAX_AGE_HOURS)
        else:
            raw = _fetch_raw(ticker)
    except Exception as error:
        return {"data": pd.DataFrame(), "missing": sorted(FIELD_MAP), "currency": None,
                "years": 0, "period_end": None,
                "error": f"could not fetch statements for {ticker}: {error}"}

    frames = [raw.get("income"), raw.get("balance"), raw.get("cashflow")]
    frames = [frame for frame in frames if isinstance(frame, pd.DataFrame) and not frame.empty]
    if not frames:
        return {"data": pd.DataFrame(), "missing": sorted(FIELD_MAP), "currency": None,
                "years": 0, "period_end": None,
                "error": f"Yahoo Finance returned no statement data for {ticker}"}

    columns: dict[str, pd.Series] = {}
    missing: list[str] = []
    for canonical, candidates in FIELD_MAP.items():
        values = _row(frames, candidates)
        if values is None and canonical == ratios.TOTAL_DEBT:
            values = _rebuild_total_debt(frames)
        if values is None:
            missing.append(canonical)
        else:
            columns[canonical] = values

    if not columns:
        return {"data": pd.DataFrame(), "missing": sorted(FIELD_MAP), "currency": None,
                "years": 0, "period_end": None,
                "error": f"no recognisable line items for {ticker}"}

    # Yahoo returns newest-first with one column per period; the maths layer
    # wants one row per year, oldest first.
    data = pd.DataFrame(columns)
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data[data.index.notna()].sort_index().tail(years)

    if missing:
        log.warning("%s: no data for %s - reported as unavailable, not estimated",
                    ticker, ", ".join(missing))
    log.info("%s: %d years of statements, %d of %d fields present",
             ticker, len(data), len(columns), len(FIELD_MAP))

    info = raw.get("info") or {}
    return {
        "data": data,
        "missing": sorted(missing),
        "currency": info.get("currency"),
        "years": len(data),
        "period_end": data.index[-1].date().isoformat() if len(data) else None,
        "error": None,
    }


def describe_gaps(result):
    """One plain sentence about what could not be fetched.

    Written here in Python so the report states the gap in fixed words rather
    than leaving a model to decide how to phrase — or whether to mention — it.
    """
    if result.get("error"):
        return result["error"]
    missing = [name for name in result.get("missing", []) if name != "shares_outstanding"]
    if not missing:
        return f"Full statement data available for {result.get('years', 0)} financial years."
    readable = ", ".join(name.replace("_", " ") for name in missing)
    return (f"Statement data covers {result.get('years', 0)} financial years. "
            f"Not reported by the data provider: {readable}. "
            "Any ratio needing these is shown as unavailable rather than estimated.")
