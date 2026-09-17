"""Small disk cache used by the external data fetchers.

Cached files live under ``.cache`` by default. Removing that folder is safe;
the next run will fetch the data again.
"""

import hashlib
import pickle
import time

from src import config

log = config.get_logger(__name__)

CACHE_DIR = config.CACHE_DIR
DEFAULT_MAX_AGE_HOURS = 24.0


def _path_for(namespace, key):
    """Return the cache path for one namespace/key pair."""
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / namespace / f"{digest}.pkl"


def load(namespace, key, max_age_hours=DEFAULT_MAX_AGE_HOURS):
    """Return ``(hit, value)`` for a fresh cache entry."""
    path = _path_for(namespace, key)
    if not path.exists():
        return False, None

    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > max_age_hours:
        return False, None

    try:
        with path.open("rb") as handle:
            return True, pickle.load(handle)
    except (
        OSError,
        pickle.PickleError,
        EOFError,
        AttributeError,
        ValueError,
        TypeError,
        ImportError,
    ) as error:
        log.warning("could not read cache file %s: %s", path, error)
        return False, None


def save(namespace, key, value):
    """Write one value without making the cache a hard dependency."""
    path = _path_for(namespace, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            pickle.dump(value, handle)
    except (OSError, pickle.PickleError, TypeError, AttributeError) as error:
        log.warning("could not write cache file %s: %s", path, error)


def cached(
    namespace,
    key,
    producer,
    max_age_hours=DEFAULT_MAX_AGE_HOURS,
    use_stale_on_failure=True,
):
    """Return ``(value, source)`` using the cache when possible.

    ``source`` is ``"live"`` when the producer ran successfully and
    ``"cached"`` when an existing value was reused. If the provider fails and
    a stale copy exists, the stale value is returned as cached data. If no
    usable copy exists, the original provider error is raised.
    """
    hit, value = load(namespace, key, max_age_hours)
    if hit:
        log.debug("cache hit %s/%s", namespace, key)
        return value, "cached"

    log.info("fetching %s/%s", namespace, key)
    try:
        fresh = producer()
    except Exception as error:
        # Producers call external services that can raise provider-specific
        # exceptions. Catching them here is intentional so stale data can be
        # used; the original error is re-raised when there is no fallback.
        if use_stale_on_failure:
            stale_hit, stale_value = load(
                namespace,
                key,
                max_age_hours=float("inf"),
            )
            if stale_hit:
                log.warning(
                    "fetch failed for %s/%s (%s) - using stale cached data",
                    namespace,
                    key,
                    error,
                )
                return stale_value, "cached"
        log.error("fetch failed for %s/%s: %s", namespace, key, error)
        raise

    save(namespace, key, fresh)
    return fresh, "live"


def clear(namespace=None):
    """Delete cached files and return the number removed."""
    target = CACHE_DIR / namespace if namespace else CACHE_DIR
    if not target.exists():
        return 0

    removed = 0
    for path in target.rglob("*.pkl"):
        try:
            path.unlink()
            removed += 1
        except OSError as error:
            log.warning("could not delete cache file %s: %s", path, error)
    return removed
