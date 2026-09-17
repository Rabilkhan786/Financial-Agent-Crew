"""Fetch recent StockTwits posts and summarize tagged sentiment."""

import json
import urllib.request

from src.components import config
from src.components.logging import get_logger

log = get_logger(__name__)
STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
REQUEST_TIMEOUT = 20


def _sentiment_summary(posts):
    bullish = sum(post.get("sentiment") == "Bullish" for post in posts)
    bearish = sum(post.get("sentiment") == "Bearish" for post in posts)

    if not posts:
        return "insufficient data"
    if bullish == 0 and bearish == 0:
        return "Posts were found, but none had Bullish/Bearish tags."

    return (
        f"{len(posts)} recent posts: {bullish} bullish and "
        f"{bearish} bearish tags."
    )


def fetch_social_posts(ticker, limit=None):
    """Return recent StockTwits posts for one ticker."""
    limit = limit or config.SOCIAL_LIMIT
    url = STOCKTWITS_URL.format(symbol=ticker.upper())

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "financial-agent-crew"},
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:
        log.warning("StockTwits fetch failed for %s: %s", ticker, error)
        return {
            "source": "StockTwits",
            "posts": [],
            "post_count": 0,
            "social_sentiment": "insufficient data",
            "data_source": "unavailable",
            "error": f"Could not fetch StockTwits posts for {ticker}.",
        }

    posts = []
    for message in payload.get("messages", [])[:limit]:
        sentiment = (
            ((message.get("entities") or {}).get("sentiment") or {}).get("basic")
        )
        posts.append(
            {
                "text": (message.get("body") or "").strip(),
                "created": (message.get("created_at") or "")[:10],
                "sentiment": sentiment,
            }
        )

    if len(posts) < config.MIN_SOCIAL_POSTS:
        sentiment_text = "insufficient data"
    else:
        sentiment_text = _sentiment_summary(posts)

    return {
        "source": "StockTwits",
        "posts": posts,
        "post_count": len(posts),
        "social_sentiment": sentiment_text,
        "data_source": "live" if posts else "unavailable",
        "error": None,
    }
