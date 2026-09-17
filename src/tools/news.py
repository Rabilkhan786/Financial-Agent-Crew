"""Fetch recent company news from Yahoo Finance."""

import datetime as dt

import yfinance as yf

from src.components import config
from src.components.logging import get_logger

log = get_logger(__name__)


def fetch_news(ticker, limit=None):
    """Return recent Yahoo Finance headlines for one ticker."""
    limit = limit or config.NEWS_LIMIT

    try:
        raw_items = yf.Ticker(ticker).news or []
    except Exception as error:
        log.error("News fetch failed for %s: %s", ticker, error)
        return []

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

        articles.append(
            {
                "title": title,
                "published": published,
            }
        )

        if len(articles) >= limit:
            break

    return articles
