"""Fetch recent company news from Yahoo Finance."""

import datetime as dt

import yfinance as yf

from src.components import config
from src.components.logging import get_logger

log = get_logger(__name__)


def fetch_news(ticker, limit=None):
    """Return recent Yahoo Finance articles for one ticker."""
    limit = limit or config.NEWS_LIMIT

    try:
        raw_items = yf.Ticker(ticker).news or []
    except Exception as error:
        log.error("News fetch failed for %s: %s", ticker, error)
        return {
            "articles": [],
            "source": "Yahoo Finance",
            "article_count": 0,
            "data_source": "unavailable",
            "error": f"Could not fetch news for {ticker}.",
        }

    articles = []
    for item in raw_items:
        content = item.get("content", item)
        title = content.get("title")
        if not title:
            continue

        published = (content.get("pubDate") or content.get("displayTime") or "")[:10]
        if not published and item.get("providerPublishTime"):
            published = dt.datetime.fromtimestamp(
                item["providerPublishTime"],
                dt.timezone.utc,
            ).date().isoformat()

        url = (
            (content.get("canonicalUrl") or {}).get("url")
            or (content.get("clickThroughUrl") or {}).get("url")
            or item.get("link")
        )

        articles.append(
            {
                "title": title,
                "summary": (
                    content.get("summary")
                    or content.get("description")
                    or ""
                ).strip(),
                "published": published,
                "url": url,
            }
        )

        if len(articles) >= limit:
            break

    return {
        "articles": articles,
        "source": "Yahoo Finance",
        "article_count": len(articles),
        "data_source": "live" if articles else "unavailable",
        "error": None if articles else f"No recent news found for {ticker}.",
    }
