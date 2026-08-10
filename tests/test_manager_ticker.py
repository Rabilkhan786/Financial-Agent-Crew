"""Tests for ticker resolution — the fix for the BMW failure.

The LLM guesses a ticker from memory; these tests pin down that a wrong guess is
detected and corrected from a REAL symbol search, and — just as important — that
an unrelated company with a similar name is never substituted. All mocked.
"""

from investpanel.agents.manager import ManagerAgent, names_match, pick_best_symbol
from investpanel.tools import fmp_client

# What FMP's search-symbol really returns for "BMW" (captured from a live call).
BMW_RESULTS = [
    {"symbol": "BMWYY", "name": "Bayerische Motoren Werke AG", "currency": "USD", "exchange": "OTC"},
    {"symbol": "BMW.SW", "name": "Bayerische Motoren Werke AG", "currency": "CHF", "exchange": "SIX"},
    {"symbol": "BMW.DE", "name": "Bayerische Motoren Werke AG", "currency": "EUR", "exchange": "XETRA"},
    {"symbol": "BMW.BO", "name": "BMW Industries Ltd", "currency": "INR", "exchange": "BSE"},
]


# --- name matching (the wrong-company guard) ---------------------------------

def test_names_match_ignores_legal_suffixes():
    assert names_match("Apple", "Apple Inc.") is True
    assert names_match("Nvidia", "NVIDIA Corporation") is True
    assert names_match("Bayerische Motoren Werke", "Bayerische Motoren Werke AG") is True


def test_names_match_rejects_a_different_company():
    # The whole point: "BMW Industries Ltd" is NOT Bayerische Motoren Werke.
    assert names_match("Bayerische Motoren Werke", "BMW Industries Ltd") is False
    assert names_match("Apple", "Apple Hospitality REIT") is True  # superset is allowed
    assert names_match("Microsoft", "Micro Focus International") is False


def test_names_match_handles_empty_input():
    assert names_match("", "Apple Inc.") is False
    assert names_match("Apple", "") is False


# --- picking the best symbol ---------------------------------------------------

def test_pick_best_symbol_prefers_the_usd_listing():
    # BMWYY (USD/OTC ADR) must win over the EUR/CHF lines our data plan can't use.
    assert pick_best_symbol("Bayerische Motoren Werke", BMW_RESULTS) == "BMWYY"


def test_pick_best_symbol_skips_the_unrelated_company():
    # The dangerous case: asking for the BRAND "BMW" must resolve to the carmaker's
    # US ADR, never to BMW Industries Ltd (an unrelated Indian company).
    assert pick_best_symbol("BMW", BMW_RESULTS) == "BMWYY"
    assert pick_best_symbol("Bayerische Motoren Werke", BMW_RESULTS) == "BMWYY"
    # ...but someone explicitly asking for BMW Industries still gets it, because an
    # exact name match outranks the US-listing preference.
    assert pick_best_symbol("BMW Industries", BMW_RESULTS) == "BMW.BO"


def test_pick_best_symbol_returns_none_when_nothing_matches():
    assert pick_best_symbol("Tesla", BMW_RESULTS) is None
    assert pick_best_symbol("Anything", []) is None


def test_pick_best_symbol_prefers_an_exact_name_match():
    # Searching "Apple" also finds Apple Hospitality REIT — the exact name must win
    # even though both are on a major US exchange.
    results = [
        {"symbol": "APLE", "name": "Apple Hospitality REIT, Inc.", "currency": "USD", "exchange": "NYSE"},
        {"symbol": "AAPL", "name": "Apple Inc.", "currency": "USD", "exchange": "NASDAQ"},
    ]
    assert pick_best_symbol("Apple", results) == "AAPL"


def test_pick_best_symbol_prefers_major_exchange_over_otc():
    results = [
        {"symbol": "ACMEY", "name": "Acme Corp", "currency": "USD", "exchange": "OTC"},
        {"symbol": "ACME", "name": "Acme Corp", "currency": "USD", "exchange": "NASDAQ"},
    ]
    assert pick_best_symbol("Acme", results) == "ACME"


# --- the resolver end to end (mocked FMP) ----------------------------------------

def test_valid_guess_is_kept_without_searching(monkeypatch):
    calls = {"search": 0}

    def count(q, limit=10):
        calls["search"] += 1
        return []

    monkeypatch.setattr(fmp_client, "get_company_profile", lambda t: {"companyName": "Apple Inc."})
    monkeypatch.setattr(fmp_client, "search_symbol", count)
    monkeypatch.setattr(fmp_client, "search_name", count)

    assert ManagerAgent().resolve_ticker("Apple", "AAPL") == "AAPL"
    assert calls["search"] == 0  # fast path: no extra lookup for a good guess


def test_bad_guess_is_corrected_from_search(monkeypatch):
    # "BMW" has no profile; BMWYY does. This is exactly the observed failure.
    def fake_profile(ticker):
        if ticker.upper() == "BMW":
            raise ValueError("FMP returned no profile for ticker 'BMW'.")
        return {"companyName": "Bayerische Motoren Werke AG"}

    monkeypatch.setattr(fmp_client, "get_company_profile", fake_profile)
    monkeypatch.setattr(fmp_client, "search_name", lambda q, limit=10: BMW_RESULTS)
    monkeypatch.setattr(fmp_client, "search_symbol", lambda q, limit=10: [])

    resolved = ManagerAgent().resolve_ticker("Bayerische Motoren Werke", "BMW")
    assert resolved == "BMWYY"


def test_symbol_search_is_used_when_name_search_finds_nothing(monkeypatch):
    # The real FMP behaviour: the legal name misses on search-symbol and the short
    # name misses on search-name, so both endpoints must be consulted.
    def fake_profile(ticker):
        if ticker.upper() == "BMW":
            raise ValueError("no profile")
        return {"companyName": "Bayerische Motoren Werke AG"}

    monkeypatch.setattr(fmp_client, "get_company_profile", fake_profile)
    monkeypatch.setattr(fmp_client, "search_name", lambda q, limit=10: [])
    monkeypatch.setattr(fmp_client, "search_symbol", lambda q, limit=10: BMW_RESULTS)

    assert ManagerAgent().resolve_ticker("Bayerische Motoren Werke", "BMW") == "BMWYY"


def test_unresolvable_ticker_keeps_the_original_guess(monkeypatch):
    # Nothing verifies -> keep the guess so the report degrades honestly.
    monkeypatch.setattr(fmp_client, "get_company_profile",
                        lambda t: (_ for _ in ()).throw(ValueError("no profile")))
    monkeypatch.setattr(fmp_client, "search_symbol", lambda q, limit=10: [])
    monkeypatch.setattr(fmp_client, "search_name", lambda q, limit=10: [])

    assert ManagerAgent().resolve_ticker("Obscure Private Co", "XYZ") == "XYZ"


def test_search_failure_is_not_fatal(monkeypatch):
    def boom(q, limit=10):
        raise RuntimeError("API down")

    monkeypatch.setattr(fmp_client, "get_company_profile",
                        lambda t: (_ for _ in ()).throw(ValueError("no profile")))
    monkeypatch.setattr(fmp_client, "search_symbol", boom)
    monkeypatch.setattr(fmp_client, "search_name", boom)

    assert ManagerAgent().resolve_ticker("Acme", "ACME") == "ACME"
