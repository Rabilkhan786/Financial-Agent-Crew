"""Alpha Vantage client — daily price history.

The Risk agent does not have its own data API. Instead it computes volatility and
exposure in plain Python from the price history fetched here (see the design note
in docs/architecture.md). For Phase 0 we only need one working call: pull daily
prices for a known ticker and confirm the key works. Responses are cached.
"""

from investpanel import config
from investpanel.tools import cache

BASE_URL = "https://www.alphavantage.co/query"


def _require_key() -> str:
    """Return the Alpha Vantage key, or raise a clear error if it's missing."""
    if not config.ALPHAVANTAGE_API_KEY:
        raise RuntimeError("ALPHAVANTAGE_API_KEY is not set. Add it to your .env file.")
    return config.ALPHAVANTAGE_API_KEY


def get_daily_prices(ticker: str) -> dict:
    """Fetch daily price history for a ticker (adjusted close etc.).

    Returns the parsed JSON plus a ``source`` field. Alpha Vantage's free tier is
    rate-limited, so if you call it too fast it returns a "Note" or "Information"
    message instead of data — we raise a clear error in that case rather than
    silently returning something the Risk agent can't use.
    """
    key = _require_key()
    ticker = ticker.upper()
    source = f"AlphaVantage TIME_SERIES_DAILY {ticker}"
    data = cache.cached_get_json(
        BASE_URL,
        cache_key=f"alphavantage:daily:{ticker}",
        params={
            "function": "TIME_SERIES_DAILY",
            "symbol": ticker,
            "outputsize": "compact",  # last ~100 trading days is plenty for Phase 0
            "apikey": key,
        },
    )
    # Alpha Vantage signals rate limits and errors inside the JSON body, not the
    # HTTP status, so we have to check the body explicitly.
    if "Note" in data or "Information" in data or "Error Message" in data:
        message = data.get("Note") or data.get("Information") or data.get("Error Message")
        raise RuntimeError(f"Alpha Vantage did not return price data: {message}")
    if "Time Series (Daily)" not in data:
        raise ValueError(f"Alpha Vantage returned no daily series for '{ticker}'.")
    data["source"] = source
    return data


def closing_prices(data: dict) -> list[float]:
    """Pull the daily closing prices out of an Alpha Vantage response.

    Alpha Vantage returns the series as a date -> fields dict, newest first and
    keyed by strings like "4. close". The Risk agent needs a plain list of closes
    in chronological (oldest-first) order, which is what this returns.
    """
    series = data.get("Time Series (Daily)", {})
    closes = []
    # Sorting the date strings ascending puts oldest first (ISO dates sort right).
    for day in sorted(series.keys()):
        close = series[day].get("4. close")
        if close is not None:
            closes.append(float(close))
    if len(closes) < 3:
        raise ValueError("Not enough closing prices to assess risk.")
    return closes
