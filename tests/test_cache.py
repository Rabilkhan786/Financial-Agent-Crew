"""Tests for the disk cache.

cache.py had no tests before this. It backs every external fetch in the
project, and freshness() (added during the portfolio audit pass) is what lets
the app tell a reader "this figure is live" from "this figure is a few hours
old" - worth pinning down directly rather than only through the tools that
happen to call it.

Uses a throwaway namespace and cleans up after itself, so it does not disturb
a real .cache/ directory a live run might be relying on.
"""

import time

import pytest

from src import cache

NAMESPACE = "test_cache_namespace"


@pytest.fixture(autouse=True)
def clean_namespace():
    cache.clear(NAMESPACE)
    yield
    cache.clear(NAMESPACE)


def test_a_miss_returns_false_and_none():
    assert cache.load(NAMESPACE, "absent-key") == (False, None)


def test_save_then_load_round_trips_the_value():
    cache.save(NAMESPACE, "k", {"a": 1, "b": [1, 2, 3]})
    hit, value = cache.load(NAMESPACE, "k")
    assert hit is True
    assert value == {"a": 1, "b": [1, 2, 3]}


def test_a_value_older_than_max_age_is_reported_as_a_miss():
    import os

    cache.save(NAMESPACE, "k", "value")
    # Back-date the file so it is unambiguously older than the max age,
    # rather than relying on max_age_hours=0 racing real elapsed time.
    path = cache._path_for(NAMESPACE, "k")
    old = time.time() - 3600
    os.utime(path, (old, old))
    hit, _ = cache.load(NAMESPACE, "k", max_age_hours=0.1)
    assert hit is False


def test_cached_calls_the_producer_only_once():
    calls = []

    def producer():
        calls.append(1)
        return "made"

    first = cache.cached(NAMESPACE, "k", producer)
    second = cache.cached(NAMESPACE, "k", producer)
    assert first == second == "made"
    assert len(calls) == 1


def test_cached_falls_back_to_a_stale_copy_when_the_producer_fails():
    cache.cached(NAMESPACE, "k", lambda: "first version")

    def failing():
        raise RuntimeError("provider is down")

    # max_age_hours=0 forces the fresh copy to be treated as stale so the
    # producer is called; it fails, and the same stale value comes back
    # anyway rather than losing the run.
    result = cache.cached(NAMESPACE, "k", failing, max_age_hours=0)
    assert result == "first version"


def test_cached_raises_when_there_is_no_stale_copy_to_fall_back_to():
    def failing():
        raise RuntimeError("provider is down")

    with pytest.raises(RuntimeError):
        cache.cached(NAMESPACE, "never-cached-key", failing)


def test_clear_removes_files_and_reports_how_many():
    cache.save(NAMESPACE, "a", 1)
    cache.save(NAMESPACE, "b", 2)
    removed = cache.clear(NAMESPACE)
    assert removed == 2
    assert cache.load(NAMESPACE, "a") == (False, None)


# --- freshness() --------------------------------------------------------

def test_freshness_is_unavailable_when_nothing_was_ever_stored():
    assert cache.freshness(NAMESPACE, "never-stored") == "unavailable"


def test_freshness_is_live_right_after_a_fresh_write():
    cache.save(NAMESPACE, "k", "value")
    assert cache.freshness(NAMESPACE, "k") == "live"


def test_freshness_is_cached_for_an_older_file():
    cache.save(NAMESPACE, "k", "value")
    # Back-date the file's mtime past the just-fetched window without
    # actually waiting for real time to pass.
    path = cache._path_for(NAMESPACE, "k")
    old = time.time() - (cache.JUST_FETCHED_SECONDS + 5)
    import os
    os.utime(path, (old, old))
    assert cache.freshness(NAMESPACE, "k") == "cached"
