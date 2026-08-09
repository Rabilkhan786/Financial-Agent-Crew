"""One place for every external HTTP call — with a disk cache and retries.

Hard rule for this project: every API response, search, and page fetch is cached
to disk, so re-running the evaluation never re-pays for the same query. Rather
than repeat cache-and-retry logic inside each client, all three clients (FMP,
Alpha Vantage, Tavily) and the article fetcher call the helpers here. That keeps
each client tiny and puts the caching guarantee in a single auditable file.

The cache key is chosen by the caller (e.g. "fmp:profile:AAPL"), so a human can
look at the on-disk cache and understand what each entry is.
"""

import time

import diskcache
import httpx

from investpanel import config

# A single shared cache backed by a folder on disk. diskcache handles the file
# layout, locking, and expiry for us — we just give it keys and values.
_cache = diskcache.Cache(str(config.CACHE_DIR))


def _request_with_retries(
    method: str,
    url: str,
    *,
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Make one HTTP request, retrying a few times on network/5xx errors.

    We retry because external APIs occasionally time out or return a transient
    5xx. We do NOT retry on a 4xx (like a bad key or bad ticker) — that is our
    mistake and retrying would not help, so we let it raise immediately.
    """
    last_error: Exception | None = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            response = httpx.request(
                method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=config.HTTP_TIMEOUT_SECONDS,
            )
            # 4xx means we sent something wrong — do not retry, surface it now.
            if 400 <= response.status_code < 500:
                response.raise_for_status()
            # 5xx means the server had a hiccup — worth retrying.
            if response.status_code >= 500:
                response.raise_for_status()
            return response
        except (httpx.HTTPStatusError, httpx.RequestError) as error:
            # A 4xx already raised above and re-raises here without retrying.
            if isinstance(error, httpx.HTTPStatusError) and error.response.status_code < 500:
                raise
            last_error = error
            if attempt < config.MAX_RETRIES:
                # Wait a little longer after each failed attempt (linear backoff).
                time.sleep(config.RETRY_BACKOFF_SECONDS * attempt)

    # If we get here, every attempt failed on a retryable error.
    raise RuntimeError(f"Request to {url} failed after {config.MAX_RETRIES} attempts") from last_error


def cached_get_json(
    url: str,
    cache_key: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
) -> dict | list:
    """GET a URL and return parsed JSON, using the disk cache first."""
    if cache_key in _cache:
        return _cache[cache_key]
    response = _request_with_retries("GET", url, params=params, headers=headers)
    data = response.json()
    _cache.set(cache_key, data, expire=config.CACHE_TTL_SECONDS)
    return data


def cached_post_json(
    url: str,
    cache_key: str,
    *,
    json_body: dict,
    headers: dict | None = None,
) -> dict | list:
    """POST a JSON body and return parsed JSON, using the disk cache first."""
    if cache_key in _cache:
        return _cache[cache_key]
    response = _request_with_retries("POST", url, json_body=json_body, headers=headers)
    data = response.json()
    _cache.set(cache_key, data, expire=config.CACHE_TTL_SECONDS)
    return data


def cached_get_text(url: str, cache_key: str) -> str:
    """GET a URL and return the raw text (used to fetch article HTML)."""
    if cache_key in _cache:
        return _cache[cache_key]
    response = _request_with_retries("GET", url)
    text = response.text
    _cache.set(cache_key, text, expire=config.CACHE_TTL_SECONDS)
    return text
