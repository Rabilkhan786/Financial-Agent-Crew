"""Focused tests for Yahoo market-data helpers."""

import pandas as pd

from src.tools import market_data


def test_profile_provider_failure_is_not_cached_as_empty_success(monkeypatch):
    """A transient Yahoo failure must reach the cache fallback logic."""

    class BrokenTicker:
        @property
        def info(self):
            raise RuntimeError("Yahoo is temporarily unavailable")

    monkeypatch.setattr(market_data.yf, "Ticker", lambda symbol: BrokenTicker())

    producer_failed = False

    def fake_cached(namespace, key, producer, max_age_hours):
        nonlocal producer_failed
        try:
            producer()
        except RuntimeError:
            producer_failed = True
            raise
        raise AssertionError("provider failure unexpectedly looked successful")

    monkeypatch.setattr(market_data.cache, "cached", fake_cached)

    profile = market_data.fetch_profile("TEST", use_cache=True)

    assert producer_failed is True
    assert profile["name"] == "TEST"
    assert profile["data_source"] == "unavailable"


def test_market_data_uses_the_source_returned_by_cache(monkeypatch):
    prices = pd.Series(
        [100.0, 101.0],
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )

    monkeypatch.setattr(
        market_data,
        "_fetch_prices_with_source",
        lambda *args, **kwargs: (prices, "cached"),
    )
    monkeypatch.setattr(
        market_data,
        "fetch_prices",
        lambda *args, **kwargs: prices,
    )
    monkeypatch.setattr(
        market_data,
        "fetch_profile",
        lambda *args, **kwargs: {
            "name": "Test Company",
            "trailing_pe": None,
            "price_to_book": None,
        },
    )

    result = market_data.fetch_market_data(
        "TEST",
        "2026-01-01",
        "2026-01-03",
    )

    assert result["data_source"] == "cached"
    assert result["error"] is None
