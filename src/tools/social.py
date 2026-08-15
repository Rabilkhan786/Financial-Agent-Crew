"""Retail chatter about a ticker — optional, and never allowed to break a run.

Two backends behind one function:

* **Reddit** via praw, used when REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are
  set in `.env`.
* **StockTwits** otherwise, which needs no key at all and whose posts carry a
  self-declared Bullish/Bearish tag, so the mood can be *counted* rather than
  guessed at.

Rule 4 of the project: if fewer than five posts are found, `social_sentiment`
is hardcoded to "insufficient data" and the posts are dropped before the LLM
ever sees them. A handful of anonymous posts is not a signal, and the surest way
to stop a model reading meaning into noise is to not show it the noise.
"""

import datetime as dt
import json
import urllib.error
import urllib.request

from src import cache, config

log = config.get_logger(__name__)

# Where retail investors actually discuss individual stocks.
SUBREDDITS = ["stocks", "investing", "StockMarket", "wallstreetbets", "ValueInvesting"]

MIN_POSTS = config.MIN_SOCIAL_POSTS       # below this, the answer is "insufficient data"
DEFAULT_LIMIT = config.SOCIAL_LIMIT
CACHE_MAX_AGE_HOURS = config.CACHE_HOURS_SOCIAL
REQUEST_TIMEOUT = 20
STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
USER_AGENT = "financial-analysis-crew/0.1"

INSUFFICIENT = "insufficient data"


def _reddit_credentials():
    """The three Reddit values, or None if the user has not set them up."""
    if not config.HAS_REDDIT:
        return None
    return (config.REDDIT_CLIENT_ID, config.REDDIT_CLIENT_SECRET,
            config.REDDIT_USER_AGENT or USER_AGENT)


def _fetch_reddit(ticker, company, limit):
    """Recent Reddit posts mentioning the ticker, newest first."""
    import praw  # imported here so a missing praw cannot break an app that never uses it

    client_id, client_secret, user_agent = _reddit_credentials()
    reddit = praw.Reddit(client_id=client_id, client_secret=client_secret,
                         user_agent=user_agent, check_for_async=False)
    reddit.read_only = True

    query = f"{ticker} OR {company}" if company else ticker
    posts = []
    for submission in reddit.subreddit("+".join(SUBREDDITS)).search(
            query, sort="new", time_filter="month", limit=limit):
        posts.append({
            "text": submission.title,
            "created": dt.datetime.fromtimestamp(
                submission.created_utc, dt.timezone.utc).date().isoformat(),
            "url": f"https://reddit.com{submission.permalink}",
            "where": f"r/{submission.subreddit.display_name}",
            "score": int(submission.score),
            "sentiment": None,      # Reddit posts carry no sentiment tag
        })
    return posts


def _fetch_stocktwits(ticker, limit):
    """Recent StockTwits posts, including each poster's own Bullish/Bearish tag."""
    url = STOCKTWITS_URL.format(symbol=ticker.upper())
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))

    posts = []
    for message in payload.get("messages", [])[:limit]:
        entities = message.get("entities") or {}
        sentiment = (entities.get("sentiment") or {}).get("basic")
        posts.append({
            "text": (message.get("body") or "").strip(),
            "created": (message.get("created_at") or "")[:10],
            "url": f"https://stocktwits.com/message/{message.get('id')}",
            "where": "StockTwits",
            "score": None,
            "sentiment": sentiment,     # "Bullish", "Bearish", or None
        })
    return posts


def _tally(posts):
    """Count the self-declared sentiment tags. Plain counting, no interpretation."""
    bullish = sum(1 for post in posts if post.get("sentiment") == "Bullish")
    bearish = sum(1 for post in posts if post.get("sentiment") == "Bearish")
    return {"bullish": bullish, "bearish": bearish,
            "untagged": len(posts) - bullish - bearish, "total": len(posts)}


def _describe(posts, source):
    """A factual one-line summary, written in Python rather than by the model.

    Where posts carry sentiment tags the counts are stated outright, so the
    report quotes a number nobody had to estimate.
    """
    counts = _tally(posts)
    if counts["bullish"] or counts["bearish"]:
        return (f"{counts['total']} recent posts on {source}: {counts['bullish']} tagged "
                f"bullish, {counts['bearish']} tagged bearish, {counts['untagged']} untagged. "
                "Counted from the posts themselves.")
    return (f"{counts['total']} recent posts on {source}. These posts carry no sentiment "
            "tag, so the tone can only be read from the text.")


def fetch_social_posts(ticker, company=None, limit=DEFAULT_LIMIT, use_cache=True):
    """Retail chatter about a ticker. Never raises.

    Returns a dict with the source used, the posts, a sentiment tally, and
    `social_sentiment` — which is the string "insufficient data" whenever fewer
    than five posts were found, set here before any model is involved.
    """
    key = f"{ticker}:{dt.date.today().isoformat()}:{limit}"

    def produce() -> dict:
        if _reddit_credentials():
            return {"source": "Reddit", "posts": _fetch_reddit(ticker, company, limit),
                    "error": None}
        return {"source": "StockTwits", "posts": _fetch_stocktwits(ticker, limit),
                "error": None}

    try:
        if use_cache:
            raw = cache.cached("social", key, produce, max_age_hours=CACHE_MAX_AGE_HOURS)
        else:
            raw = produce()
    except urllib.error.HTTPError as error:
        # A ticker with no StockTwits page returns 404, common outside the US.
        raw = {"source": "StockTwits", "posts": [],
               "error": f"social lookup failed (HTTP {error.code})"}
    except Exception as error:  # a missing key, a network blip, a changed response shape
        raw = {"source": "unavailable", "posts": [], "error": f"social lookup failed: {error}"}

    posts = raw.get("posts") or []
    source = raw.get("source", "unavailable")

    # Rule 4, enforced here and not in a prompt: too little chatter is not a
    # weak signal, it is no signal. The posts are dropped so the model cannot
    # read a mood into three anonymous messages.
    if len(posts) < MIN_POSTS:
        log.info("%s: only %d posts from %s (need %d) - reporting insufficient data",
                 ticker, len(posts), source, MIN_POSTS)
        return {"source": source, "posts": [], "post_count": len(posts),
                "tally": _tally(posts), "social_sentiment": INSUFFICIENT,
                "error": raw.get("error")}

    log.info("%s: %d posts from %s, tally=%s", ticker, len(posts), source, _tally(posts))
    return {"source": source, "posts": posts, "post_count": len(posts),
            "tally": _tally(posts), "social_sentiment": _describe(posts, source),
            "error": raw.get("error")}
