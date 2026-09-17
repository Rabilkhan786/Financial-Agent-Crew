"""Tests for the disk cache."""

import os
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


def test_a_value_older_than_max_age_is_a_miss():
    cache.save(NAMESPACE, "k", "value")
    path = cache._path_for(NAMESPACE, "k")
    old = time.time() - 3600
    os.utime(path, (old, old))

    hit, _ = cache.load(NAMESPACE, "k", max_age_hours=0.1)
    assert hit is False


def test_first_fetch_is_live_and_second_fetch_is_cached():
    calls = []

    def producer():
        calls.append(1)
        return "made"

    first, first_source = cache.cached(NAMESPACE, "k", producer)
    second, second_source = cache.cached(NAMESPACE, "k", producer)

    assert first == second == "made"
    assert first_source == "live"
    assert second_source == "cached"
    assert len(calls) == 1


def test_cached_falls_back_to_stale_data_when_producer_fails():
    cache.cached(NAMESPACE, "k", lambda: "first version")

    def failing():
        raise RuntimeError("provider is down")

    result, source = cache.cached(
        NAMESPACE,
        "k",
        failing,
        max_age_hours=0,
    )

    assert result == "first version"
    assert source == "cached"


def test_cached_raises_when_there_is_no_stale_copy():
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
