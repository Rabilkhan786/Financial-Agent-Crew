"""Disk cache for every external call.

Rule 6 of the project: nothing is fetched twice. Prices, statements, news and
social posts all go through here, keyed by ticker and date, so re-running an
analysis costs nothing and a demo works even when a provider is rate-limiting.

The cache is a folder of pickled files under `.cache/`. Pickle is used rather
than JSON because it stores a pandas DataFrame and a plain dict through exactly
the same code path — one way in, one way out, nothing to special-case. The
folder is local, disposable and gitignored: deleting it only costs a re-fetch.
"""

import hashlib
import pickle
import time
from pathlib import Path
from typing import Any, Callable

from src import config

log = config.get_logger(__name__)

CACHE_DIR = config.CACHE_DIR
DEFAULT_MAX_AGE_HOURS = 24.0


def _path_for(namespace, key):
    """Where one cached value lives.

    The key is hashed because it contains characters (colons, slashes, dots)
    that are not safe in a filename. The namespace stays readable so the cache
    folder can be inspected by eye.
    """
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / namespace / f"{digest}.pkl"


def age_hours(namespace, key):
    """How old the cached value is, or None if it was never stored."""
    path = _path_for(namespace, key)
    if not path.exists():
        return None
    return (time.time() - path.stat().st_mtime) / 3600


def load(namespace, key, max_age_hours=DEFAULT_MAX_AGE_HOURS):
    """Read a cached value. Returns (hit, value); (False, None) when there is no
    fresh copy. A corrupt file is treated as a miss rather than an error."""
    path = _path_for(namespace, key)
    if not path.exists():
        return False, None
    if (time.time() - path.stat().st_mtime) / 3600 > max_age_hours:
        return False, None
    try:
        with path.open("rb") as handle:
            return True, pickle.load(handle)
    except Exception:
        return False, None


def save(namespace, key, value):
    """Write a value to the cache. Never raises — a cache failure must not take
    down a run that already has its data."""
    path = _path_for(namespace, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            pickle.dump(value, handle)
    except Exception:
        pass


def cached(namespace, key, producer, max_age_hours=DEFAULT_MAX_AGE_HOURS, use_stale_on_failure=True):
    """Return a cached value, or produce and store it.

    If the producer fails (a provider is down or throttling) and a stale copy
    exists, the stale copy is returned rather than letting the whole run die.
    Old data clearly beats no data here, and every caller reports the date its
    data came from anyway.
    """
    hit, value = load(namespace, key, max_age_hours)
    if hit:
        log.debug("cache hit  %s/%s", namespace, key)
        return value

    log.info("fetching   %s/%s", namespace, key)
    try:
        fresh = producer()
    except Exception as error:
        if use_stale_on_failure:
            stale_hit, stale_value = load(namespace, key, max_age_hours=float("inf"))
            if stale_hit:
                log.warning("fetch failed for %s/%s (%s) - using the stale cached copy",
                            namespace, key, error)
                return stale_value
        log.error("fetch failed for %s/%s: %s", namespace, key, error)
        raise

    save(namespace, key, fresh)
    return fresh


def clear(namespace=None):
    """Delete cached files. Returns how many were removed."""
    target = CACHE_DIR / namespace if namespace else CACHE_DIR
    if not target.exists():
        return 0
    removed = 0
    for path in target.rglob("*.pkl"):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed
