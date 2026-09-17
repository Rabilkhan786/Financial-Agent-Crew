"""Fetch and summarize recent StockTwits posts for a ticker."""

import datetime as dt
import json
import urllib.error
import urllib.request

from src import cache, config

log = config.get_logger(__name__)

MIN_POSTS = config.MIN_SOCIAL_POSTS
DEFAULT_LIMIT = config.SOCIAL_LIMIT
CACHE_MAX_AGE_HOURS = config.CACHE_HOURS_SOCIAL
REQUEST_TIMEOUT = 20
STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
USER_AGENT = "financial-analysis-crew/0.1"
INSUFFICIENT = "insufficient data"


def _fetch_stocktwits(ticker, limit):
    """Fetch recent StockTwits posts for one ticker."""
    url = STOCKTWITS_URL.format(symbol=ticker.upper())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))

    posts = []
    for message in payload.get("messages", [])[:limit]:
        sentiment = (
            (message.get("entities") or {})
            .get("sentiment", {})
            .get("basic")
        )
        posts.append(
            {
                "text": (message.get("body") or "").strip(),
                "created": (message.get("created_at") or "")[:10],
                "url": f"https://stocktwits.com/message/{message.get('id')}",
                "where": "StockTwits",
                "score": None,
                "sentiment": sentiment,
            }
        )

    return posts


def _tally(posts):
    """Count Bullish, Bearish, and untagged posts."""
    bullish = sum(post.get("sentiment") == "Bullish" for post in posts)
    bearish = sum(post.get("sentiment") == "Bearish" for post in posts)

    return {
        "bullish": bullish,
        "bearish": bearish,
        "untagged": len(posts) - bullish - bearish,
        "total": len(posts),
    }


def _describe(posts, source):
    """Return a deterministic summary of the social sentiment counts."""
    counts = _tally(posts)

    if counts["bullish"] or counts["bearish"]:
        return (
            f"{counts['total']} recent posts on {source}: "
            f"{counts['bullish']} tagged bullish, "
            f"{counts['bearish']} tagged bearish, "
            f"{counts['untagged']} untagged. "
            "Counted from the posts themselves."
        )

    return (
        f"{counts['total']} recent posts on {source}. "
        "These posts carry no sentiment tag, so the tone can only be read "
        "from the text."
    )


def _fetch_raw(ticker, limit):
    """Return the raw social payload used by the public entry point."""
    return {
        "source": "StockTwits",
        "posts": _fetch_stocktwits(ticker, limit),
        "error": None,
    }


def _load_social(ticker, limit, use_cache):
    """Fetch social data directly or through the disk cache."""
    key = f"{ticker}:{dt.date.today().isoformat()}:{limit}"

    if not use_cache:
        return _fetch_raw(ticker, limit), "live"

    raw = cache.cached(
        "social",
        key,
        lambda: _fetch_raw(ticker, limit),
        max_age_hours=CACHE_MAX_AGE_HOURS,
    )
    return raw, cache.freshness("social", key)


def _empty_result(source, data_source, error, post_count=0, tally=None):
    """Build the standard response used when social data is unavailable."""
    return {
        "source": source,
        "data_source": data_source,
        "posts": [],
        "post_count": post_count,
        "tally": tally or _tally([]),
        "social_sentiment": INSUFFICIENT,
        "error": error,
    }


def fetch_social_posts(ticker, limit=DEFAULT_LIMIT, use_cache=True):
    """Return recent social posts and a deterministic sentiment summary."""
    try:
        raw, data_source = _load_social(ticker, limit, use_cache)
    except urllib.error.HTTPError as error:
        return _empty_result(
            source="StockTwits",
            data_source="unavailable",
            error=f"social lookup failed (HTTP {error.code})",
        )
    except Exception as error:
        return _empty_result(
            source="unavailable",
            data_source="unavailable",
            error=f"social lookup failed: {error}",
        )

    posts = raw.get("posts") or []
    source = raw.get("source", "unavailable")
    counts = _tally(posts)

    if len(posts) < MIN_POSTS:
        log.info(
            "%s: only %d posts from %s (need %d)",
            ticker,
            len(posts),
            source,
            MIN_POSTS,
        )
        return _empty_result(
            source=source,
            data_source=data_source,
            error=raw.get("error"),
            post_count=len(posts),
            tally=counts,
        )

    log.info("%s: %d posts from %s, tally=%s", ticker, len(posts), source, counts)
    return {
        "source": source,
        "data_source": data_source,
        "posts": posts,
        "post_count": len(posts),
        "tally": counts,
        "social_sentiment": _describe(posts, source),
        "error": raw.get("error"),
    }
