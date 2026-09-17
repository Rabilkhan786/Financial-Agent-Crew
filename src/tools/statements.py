"""Fetch and normalize annual financial statements from Yahoo Finance."""

import pandas as pd
import yfinance as yf

from src.components import config
from src.components.logging import get_logger
from src.tools import ratios

log = get_logger(__name__)

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


def _find_row(frames, names):
    """Return the first usable statement row matching any supplied name."""
    for frame in frames:
        for name in names:
            if name in frame.index:
                values = pd.to_numeric(frame.loc[name], errors="coerce")
                if not values.dropna().empty:
                    return values
    return None


def _total_debt(frames):
    """Rebuild total debt when Yahoo reports only debt components."""
    long_term = _find_row(frames, ["Long Term Debt"])
    current = _find_row(frames, ["Current Debt"])

    if long_term is None:
        return current
    if current is None:
        return long_term
    return long_term.add(current, fill_value=0)


def fetch_statements(ticker, years=None):
    """Return normalized annual statements used by ratio calculations."""
    years = years or config.STATEMENT_YEARS

    try:
        company = yf.Ticker(ticker)
        frames = [
            company.income_stmt,
            company.balance_sheet,
            company.cashflow,
        ]
        frames = [
            frame
            for frame in frames
            if frame is not None and not frame.empty
        ]
    except Exception as error:
        log.error("Statement fetch failed for %s: %s", ticker, error)
        return {
            "data": pd.DataFrame(),
            "missing": list(FIELD_MAP),
            "years": 0,
            "error": f"Could not fetch statements for {ticker}.",
        }

    if not frames:
        return {
            "data": pd.DataFrame(),
            "missing": list(FIELD_MAP),
            "years": 0,
            "error": f"No statement data found for {ticker}.",
        }

    columns = {}
    missing = []

    for field, names in FIELD_MAP.items():
        values = _find_row(frames, names)
        if values is None and field == ratios.TOTAL_DEBT:
            values = _total_debt(frames)

        if values is None:
            missing.append(field)
        else:
            columns[field] = values

    data = pd.DataFrame(columns)
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data[data.index.notna()].sort_index().tail(years)

    return {
        "data": data,
        "missing": sorted(missing),
        "years": len(data),
        "error": None if not data.empty else f"No usable statement rows for {ticker}.",
    }


def describe_gaps(result):
    """Return a short note describing missing statement fields."""
    if result.get("error"):
        return result["error"]

    missing = [
        name
        for name in result.get("missing", [])
        if name != "shares_outstanding"
    ]
    if not missing:
        return "All required statement fields were available."

    return "Missing statement fields: " + ", ".join(
        name.replace("_", " ") for name in missing
    )
