"""Fetch recent StockTwits posts and summarise their self-declared sentiment."""

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
    """Fetch recent StockTwits posts and their Bullish/Bearish tags."""
    url = STOCKTWITS_URL.format(symbol=ticker.upper())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))

    posts = []
    for message in payload.get("messages", [])[:limit]:
        entities = message.get("entities") or {}
        sentiment = (entities.get("sentiment") or {}).get("basic")
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
    bullish = sum(1 for post in posts if post.get("sentiment") == "Bullish")
    bearish = sum(1 for post in posts if post.get("sentiment") == "Bearish")
    return {
        "bullish": bullish,
        "bearish": bearish,
        "untagged": len(posts) - bullish - bearish,
        "total": len(posts),
    }


def _describe(posts, source):
    """Return a factual one-line summary of the post counts."""
    counts = _tally(posts)
    if counts["bullish"] or counts["bearish"]:
        return (
            f"{counts['total']} recent posts on {source}: {counts['bullish']} tagged "
            f"bullish, {counts['bearish']} tagged bearish, {counts['untagged']} untagged. "
            "Counted from the posts themselves."
        )
    return (
        f"{counts['total']} recent posts on {source}. These posts carry no sentiment "
        "tag, so the tone can only be read from the text."
    )


def fetch_social_posts(ticker, limit=DEFAULT_LIMIT, use_cache=True):
    """Return retail chatter while treating too little data as no signal."""
    key = f"{ticker}:{dt.date.today().isoformat()}:{limit}"

    def produce():
        return {
            "source": "StockTwits",
            "posts": _fetch_stocktwits(ticker, limit),
            "error": None,
        }

    try:
        if use_cache:
            raw, data_source = cache.cached(
                "social",
                key,
                produce,
                max_age_hours=CACHE_MAX_AGE_HOURS,
            )
        else:
            raw = produce()
            data_source = "live"
    except urllib.error.HTTPError as error:
        raw = {
            "source": "StockTwits",
            "posts": [],
            "error": f"social lookup failed (HTTP {error.code})",
        }
        data_source = "unavailable"
    except Exception as error:
        raw = {
            "source": "unavailable",
            "posts": [],
            "error": f"social lookup failed: {error}",
        }
        data_source = "unavailable"

    posts = raw.get("posts") or []
    source = raw.get("source", "unavailable")
    tally = _tally(posts)

    if len(posts) < MIN_POSTS:
        log.info(
            "%s: only %d posts from %s (need %d) - reporting insufficient data",
            ticker,
            len(posts),
            source,
            MIN_POSTS,
        )
        return {
            "source": source,
            "data_source": data_source,
            "posts": [],
            "post_count": len(posts),
            "tally": tally,
            "social_sentiment": INSUFFICIENT,
            "error": raw.get("error"),
        }

    log.info("%s: %d posts from %s, tally=%s", ticker, len(posts), source, tally)
    return {
        "source": source,
        "data_source": data_source,
        "posts": posts,
        "post_count": len(posts),
        "tally": tally,
        "social_sentiment": _describe(posts, source),
        "error": raw.get("error"),
    }
