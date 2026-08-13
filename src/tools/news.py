"""Recent news about a company, with optional scored sentiment.

Three backends, none of them required:

* **Yahoo Finance** via yfinance — the default, no key, headline plus a short
  summary.
* **Finnhub** — used instead when FINNHUB_API_KEY is set. Same idea but with
  fuller article summaries and better date coverage.
* **Alpha Vantage NEWS_SENTIMENT** — used *as well*, when ALPHAVANTAGE_API_KEY
  is set, to attach a sentiment score to the coverage.

The sentiment number is produced by the provider and averaged here in Python.
It is never estimated by the LLM: a model asked to score tone will happily
invent a precise-looking number, and a made-up 0.42 is worse than no score.
"""

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

# Alpha Vantage's own score bands, restated here so the label is reproducible.
SENTIMENT_BANDS = [(-1.01, -0.35, "bearish"), (-0.35, -0.15, "somewhat bearish"),
                   (-0.15, 0.15, "neutral"), (0.15, 0.35, "somewhat bullish"),
                   (0.35, 1.01, "bullish")]


def _get_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


# --- Backends ---------------------------------------------------------------

def _fetch_yahoo(ticker, limit):
    """Yahoo Finance headlines. Handles both the old flat shape and the new
    nested one, because yfinance has changed this response before."""
    import yfinance as yf

    articles = []
    for item in (yf.Ticker(ticker).news or [])[: limit * 2]:
        content = item.get("content", item)
        title = content.get("title")
        if not title:
            continue
        url = ((content.get("canonicalUrl") or {}).get("url")
               or (content.get("clickThroughUrl") or {}).get("url")
               or item.get("link"))
        published = (content.get("pubDate") or content.get("displayTime") or "")[:10]
        if not published and item.get("providerPublishTime"):
            published = dt.datetime.fromtimestamp(
                item["providerPublishTime"], dt.timezone.utc).date().isoformat()
        articles.append({
            "title": title,
            "summary": (content.get("summary") or content.get("description") or "").strip(),
            "published": published,
            "url": url,
            "provider": (content.get("provider") or {}).get("displayName") or "Yahoo Finance",
        })
    return articles[:limit]


def _fetch_finnhub(ticker, limit, days, api_key):
    """Company news from Finnhub over the last `days` days."""
    today = dt.date.today()
    query = urllib.parse.urlencode({
        "symbol": ticker.upper(),
        "from": (today - dt.timedelta(days=days)).isoformat(),
        "to": today.isoformat(),
        "token": api_key,
    })
    payload = _get_json(f"{FINNHUB_URL}?{query}")
    if not isinstance(payload, list):
        return []

    articles = []
    for item in payload[:limit]:
        headline = item.get("headline")
        if not headline:
            continue
        articles.append({
            "title": headline,
            "summary": (item.get("summary") or "").strip(),
            "published": dt.datetime.fromtimestamp(
                item.get("datetime", 0), dt.timezone.utc).date().isoformat(),
            "url": item.get("url"),
            "provider": item.get("source") or "Finnhub",
        })
    return articles


def _label_for(score):
    for low, high, label in SENTIMENT_BANDS:
        if low <= score < high:
            return label
    return "neutral"


def _fetch_alphavantage_sentiment(ticker, api_key):
    """Average news sentiment for a ticker, scored by Alpha Vantage.

    Each article carries a relevance score saying how much it is really about
    this company, so the average is weighted by it — an article that mentions
    the ticker in passing should not count the same as one about it.
    """
    query = urllib.parse.urlencode({
        "function": "NEWS_SENTIMENT", "tickers": ticker.upper(),
        "sort": "LATEST", "limit": 50, "apikey": api_key,
    })
    payload = _get_json(f"{ALPHAVANTAGE_URL}?{query}")
    if not isinstance(payload, dict):
        return None
    if "feed" not in payload:
        # Alpha Vantage reports a used-up quota as an "Information" message.
        note = payload.get("Information") or payload.get("Note") or payload.get("Error Message")
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
    return {"average_score": round(average, 4), "label": _label_for(average),
            "articles_scored": scored, "source": "Alpha Vantage", "error": None}


# --- One entry point --------------------------------------------------------

def fetch_news(ticker, limit=DEFAULT_LIMIT, days=DEFAULT_DAYS, use_cache=True):
    """Recent articles about a company, plus a sentiment score when available.

    Never raises. A backend that fails leaves an error message and an empty
    list, so the report can say coverage was unavailable rather than the run
    falling over.
    """
    finnhub_key = config.FINNHUB_API_KEY
    alphavantage_key = config.ALPHAVANTAGE_API_KEY
    key = f"{ticker}:{dt.date.today().isoformat()}:{limit}:{days}"

    def produce() -> dict:
        articles: list[dict] = []
        source = "Yahoo Finance"
        if finnhub_key:
            # Free Finnhub plans cover US listings but refuse others outright
            # (a 403 on an Indian ticker, for instance). Either an error or an
            # empty result falls back to Yahoo rather than losing the news.
            try:
                articles = _fetch_finnhub(ticker, limit, days, finnhub_key)
                source = "Finnhub"
            except Exception as error:
                log.warning("Finnhub refused %s (%s) - falling back to Yahoo", ticker, error)
                articles = []
        if not articles:
            articles, source = _fetch_yahoo(ticker, limit), "Yahoo Finance"

        sentiment = None
        if alphavantage_key:
            try:
                sentiment = _fetch_alphavantage_sentiment(ticker, alphavantage_key)
            except Exception as error:
                sentiment = {"error": f"sentiment lookup failed: {error}"}

        return {"articles": articles, "source": source, "sentiment": sentiment, "error": None}

    try:
        if use_cache:
            result = cache.cached("news", key, produce, max_age_hours=CACHE_MAX_AGE_HOURS)
        else:
            result = produce()
    except Exception as error:
        result = {"articles": [], "source": "unavailable", "sentiment": None,
                  "error": f"news lookup failed: {error}"}

    articles = result.get("articles") or []
    result["article_count"] = len(articles)
    log.info("%s: %d articles via %s, sentiment=%s",
             ticker, len(articles), result.get("source"),
             (result.get("sentiment") or {}).get("label", "none"))
    if not articles and not result.get("error"):
        result["error"] = f"No recent news found for {ticker}."
    return result
