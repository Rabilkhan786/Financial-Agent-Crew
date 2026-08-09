"""Financial Modeling Prep (FMP) client — company fundamentals.

This is where the Financial agent will get real numbers: company profile, income
statement, balance sheet, cash flow. For Phase 0 we only need one working call to
prove the key and connection work. Every response is cached and every function
returns a plain Python object plus a ``source`` string the agent can cite, so no
financial fact ever appears without saying where it came from.
"""

from investpanel import config
from investpanel.tools import cache

BASE_URL = "https://financialmodelingprep.com/api/v3"


def _require_key() -> str:
    """Return the FMP key, or raise a clear error if the user hasn't set it."""
    if not config.FMP_API_KEY:
        raise RuntimeError("FMP_API_KEY is not set. Add it to your .env file.")
    return config.FMP_API_KEY


def get_company_profile(ticker: str) -> dict:
    """Fetch the basic company profile (name, sector, price, market cap...).

    Returns the first profile object plus the source URL it came from. FMP
    returns a list with a single item for a valid ticker; we hand back that item.
    """
    key = _require_key()
    ticker = ticker.upper()
    url = f"{BASE_URL}/profile/{ticker}"
    source = f"FMP /profile/{ticker}"
    data = cache.cached_get_json(
        url,
        cache_key=f"fmp:profile:{ticker}",
        params={"apikey": key},
    )
    if not data:
        raise ValueError(f"FMP returned no profile for ticker '{ticker}'.")
    profile = data[0]
    profile["source"] = source
    return profile


def _get_statement(endpoint: str, ticker: str, limit: int) -> list[dict]:
    """Shared helper: fetch a financial statement list, newest period first.

    ``endpoint`` is an FMP path like "income-statement". We ask for a few years so
    the Financial agent can compute year-over-year growth. Returns the raw list;
    the agent picks the fields it needs and records the source.
    """
    key = _require_key()
    ticker = ticker.upper()
    url = f"{BASE_URL}/{endpoint}/{ticker}"
    data = cache.cached_get_json(
        url,
        cache_key=f"fmp:{endpoint}:{ticker}:{limit}",
        params={"apikey": key, "limit": limit, "period": "annual"},
    )
    if not data:
        raise ValueError(f"FMP returned no '{endpoint}' for ticker '{ticker}'.")
    return data


def get_income_statement(ticker: str, limit: int = 2) -> list[dict]:
    """Annual income statements (revenue, net income, operating income...)."""
    return _get_statement("income-statement", ticker, limit)


def get_balance_sheet(ticker: str, limit: int = 1) -> list[dict]:
    """Annual balance sheets (debt, equity, assets, current liabilities...)."""
    return _get_statement("balance-sheet-statement", ticker, limit)


def get_cash_flow(ticker: str, limit: int = 1) -> list[dict]:
    """Annual cash-flow statements (operating cash flow...)."""
    return _get_statement("cash-flow-statement", ticker, limit)


def get_ratios_ttm(ticker: str) -> dict:
    """Trailing-twelve-month ratios (P/E, P/B...). Returns the single ratios dict."""
    key = _require_key()
    ticker = ticker.upper()
    url = f"{BASE_URL}/ratios-ttm/{ticker}"
    data = cache.cached_get_json(
        url,
        cache_key=f"fmp:ratios-ttm:{ticker}",
        params={"apikey": key},
    )
    if not data:
        raise ValueError(f"FMP returned no TTM ratios for ticker '{ticker}'.")
    return data[0]
