"""Tavily client — news and web search.

The News agent uses this to find recent events about a company, then fetches the
actual articles (see fetch.py) so every claim it makes has a real URL behind it.
We call Tavily directly over HTTP with httpx — no MCP, no vendor SDK — which is a
deliberate project decision to keep things simple to build, debug, and explain.
Every search is cached, so re-running the evaluation never re-pays for a query.
"""

from investpanel import config
from investpanel.tools import cache

BASE_URL = "https://api.tavily.com/search"


def _require_key() -> str:
    """Return the Tavily key, or raise a clear error if it's missing."""
    if not config.TAVILY_API_KEY:
        raise RuntimeError("TAVILY_API_KEY is not set. Add it to your .env file.")
    return config.TAVILY_API_KEY


def search_news(query: str, max_results: int = 5) -> dict:
    """Search the web for a query and return Tavily's results (cached).

    The returned JSON includes a list of results, each with a title, url, and a
    short content snippet. The News agent uses the urls to fetch full articles.
    """
    key = _require_key()
    body = {
        "api_key": key,
        "query": query,
        "max_results": max_results,
        "topic": "news",
        "search_depth": "basic",
    }
    # The key is in the cache key only by its query, never the secret itself.
    data = cache.cached_post_json(
        BASE_URL,
        cache_key=f"tavily:search:{query}:{max_results}",
        json_body=body,
    )
    return data
