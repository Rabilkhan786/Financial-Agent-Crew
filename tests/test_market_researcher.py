"""Focused tests for the market researcher verification step."""

from src.agents import market_researcher


def _stub_sources(monkeypatch):
    monkeypatch.setattr(
        market_researcher.market_data,
        "fetch_profile",
        lambda ticker: {"name": "Test Company", "sector": "Technology"},
    )
    monkeypatch.setattr(
        market_researcher.news,
        "fetch_news",
        lambda ticker: {
            "articles": [{"title": "Test Company announces update", "summary": ""}],
            "article_count": 1,
            "source": "Yahoo Finance",
            "data_source": "live",
            "sentiment": None,
        },
    )
    monkeypatch.setattr(
        market_researcher.social,
        "fetch_social_posts",
        lambda ticker: {
            "source": "StockTwits",
            "data_source": "live",
            "posts": [],
            "post_count": 0,
            "tally": {"bullish": 0, "bearish": 0, "untagged": 0, "total": 0},
            "social_sentiment": "insufficient data",
            "error": None,
        },
    )


def test_failed_retry_does_not_keep_known_bad_summary(monkeypatch):
    _stub_sources(monkeypatch)
    answers = iter(["Revenue rose 999%.", ""])
    monkeypatch.setattr(market_researcher.llm, "ask", lambda prompt: next(answers))

    result = market_researcher.run(
        {"ticker": "TEST", "company": "Test Company"}
    )

    assert result["research"]["summary"] == ""


def test_verified_retry_replaces_bad_first_summary(monkeypatch):
    _stub_sources(monkeypatch)
    answers = iter(["Revenue rose 999%.", "The company announced an update."])
    monkeypatch.setattr(market_researcher.llm, "ask", lambda prompt: next(answers))

    result = market_researcher.run(
        {"ticker": "TEST", "company": "Test Company"}
    )

    assert result["research"]["summary"] == "The company announced an update."
