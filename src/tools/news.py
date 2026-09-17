"""Fetch recent company news and optional sentiment data."""

import datetime as dt
import json
import urllib.parse
import urllib.request

from src import cache, config

log = config.get_logger(__name__)

CACHE_MAX_AGE_HOURS = config.CACHE_HOURS_NEWS
DEFAULT_LIMIT = config.NEWS_LIMIT
DEFAULT_DAYS = config.NEWS_DAYS
REQUEST_TIMEOUT = 20
USER_AGENT = "financial-analysis-crew/0.1"

FINNHUB_URL = "https://finnhub.io/api/v1/company-news"
ALPHAVANTAGE_URL = "https://www.alphavantage.co/query"

SENTIMENT_BANDS = [
    (-1.01, -0.35, "bearish"),
    (-0.35, -0.15, "somewhat bearish"),
    (-0.15, 0.15, "neutral"),
    (0.15, 0.35, "somewhat bullish"),
    (0.35, 1.01, "bullish"),
]


def _get_json(url):
    """Fetch and decode a JSON response."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_yahoo(ticker, limit):
    """Fetch recent Yahoo Finance headlines."""
    import yfinance as yf

    articles = []
    for item in (yf.Ticker(ticker).news or [])[: limit * 2]:
        content = item.get("content", item)
        title = content.get("title")
        if not title:
            continue

        url = (
            (content.get("canonicalUrl") or {}).get("url")
            or (content.get("clickThroughUrl") or {}).get("url")
            or item.get("link")
        )

        published = (
            content.get("pubDate")
            or content.get("displayTime")
            or ""
        )[:10]

        if not published and item.get("providerPublishTime"):
            published = dt.datetime.fromtimestamp(
                item["providerPublishTime"],
                dt.timezone.utc,
            ).date().isoformat()

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
                "provider": (
                    (content.get("provider") or {}).get("displayName")
                    or "Yahoo Finance"
                ),
            }
        )

    return articles[:limit]


def _fetch_finnhub(ticker, limit, days, api_key):
    """Fetch recent company news from Finnhub."""
    today = dt.date.today()
    query = urllib.parse.urlencode(
        {
            "symbol": ticker.upper(),
            "from": (today - dt.timedelta(days=days)).isoformat(),
            "to": today.isoformat(),
            "token": api_key,
        }
    )

    payload = _get_json(f"{FINNHUB_URL}?{query}")
    if not isinstance(payload, list):
        return []

    articles = []
    for item in payload[:limit]:
        title = item.get("headline")
        if not title:
            continue

        articles.append(
            {
                "title": title,
                "summary": (item.get("summary") or "").strip(),
                "published": dt.datetime.fromtimestamp(
                    item.get("datetime", 0),
                    dt.timezone.utc,
                ).date().isoformat(),
                "url": item.get("url"),
                "provider": item.get("source") or "Finnhub",
            }
        )

    return articles


def _label_for(score):
    """Convert an Alpha Vantage sentiment score to a label."""
    for low, high, label in SENTIMENT_BANDS:
        if low <= score < high:
            return label
    return "neutral"


def _fetch_alphavantage_sentiment(ticker, api_key):
    """Fetch the weighted average news sentiment for one ticker."""
    query = urllib.parse.urlencode(
        {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker.upper(),
            "sort": "LATEST",
            "limit": 50,
            "apikey": api_key,
        }
    )

    payload = _get_json(f"{ALPHAVANTAGE_URL}?{query}")
    if not isinstance(payload, dict):
        return None

    if "feed" not in payload:
        note = (
            payload.get("Information")
            or payload.get("Note")
            or payload.get("Error Message")
        )
        return {"error": str(note)[:200]} if note else None

    weighted_total = 0.0
    weight_total = 0.0
    scored = 0

    for article in payload["feed"]:
        for entry in article.get("ticker_sentiment", []):
            if entry.get("ticker", "").upper() != ticker.upper():
                continue

            try:
                score = float(entry["ticker_sentiment_score"])
                relevance = float(entry.get("relevance_score", 1.0))
            except (KeyError, TypeError, ValueError):
                continue

            weighted_total += score * relevance
            weight_total += relevance
            scored += 1

    if not scored or weight_total == 0:
        return None

    average = weighted_total / weight_total
    return {
        "average_score": round(average, 4),
        "label": _label_for(average),
        "articles_scored": scored,
        "source": "Alpha Vantage",
        "error": None,
    }


def _fetch_articles(ticker, limit, days):
    """Fetch articles from Finnhub when configured, otherwise Yahoo."""
    if config.FINNHUB_API_KEY:
        try:
            articles = _fetch_finnhub(
                ticker,
                limit,
                days,
                config.FINNHUB_API_KEY,
            )
            if articles:
                return articles, "Finnhub"
        except Exception as error:
            log.warning(
                "Finnhub failed for %s (%s) - falling back to Yahoo",
                ticker,
                error,
            )

    return _fetch_yahoo(ticker, limit), "Yahoo Finance"


def _fetch_sentiment(ticker):
    """Fetch optional Alpha Vantage sentiment data."""
    if not config.ALPHAVANTAGE_API_KEY:
        return None

    try:
        return _fetch_alphavantage_sentiment(
            ticker,
            config.ALPHAVANTAGE_API_KEY,
        )
    except Exception as error:
        return {"error": f"sentiment lookup failed: {error}"}


def _fetch_raw(ticker, limit, days):
    """Fetch the complete uncached news payload."""
    articles, source = _fetch_articles(ticker, limit, days)
    return {
        "articles": articles,
        "source": source,
        "sentiment": _fetch_sentiment(ticker),
        "error": None,
    }


def _empty_result(error):
    """Return the standard response used when news fetching fails."""
    return {
        "articles": [],
        "source": "unavailable",
        "data_source": "unavailable",
        "sentiment": None,
        "article_count": 0,
        "error": error,
    }


def fetch_news(ticker, limit=DEFAULT_LIMIT, days=DEFAULT_DAYS, use_cache=True):
    """Return recent company news and optional sentiment information."""
    key = f"{ticker}:{dt.date.today().isoformat()}:{limit}:{days}"

    try:
        if use_cache:
            result = cache.cached(
                "news",
                key,
                lambda: _fetch_raw(ticker, limit, days),
                max_age_hours=CACHE_MAX_AGE_HOURS,
            )
            result["data_source"] = cache.freshness("news", key)
        else:
            result = _fetch_raw(ticker, limit, days)
            result["data_source"] = "live"
    except Exception as error:
        return _empty_result(f"news lookup failed: {error}")

    articles = result.get("articles") or []
    result["article_count"] = len(articles)

    if not articles and not result.get("error"):
        result["error"] = f"No recent news found for {ticker}."

    log.info(
        "%s: %d articles via %s, sentiment=%s",
        ticker,
        len(articles),
        result.get("source"),
        (result.get("sentiment") or {}).get("label", "none"),
    )

    return result
