"""Tests for api_client.py - specifically, that chart URLs never regress
back to using the server-to-server address.

The bug this guards against: api_client had only one URL, API_URL, used both
for requests this server makes itself AND for the <img> tag a chart is shown
in. That tag is fetched by the reader's browser, not this server, so inside
Docker Compose - where API_URL is the internal service name "http://api:8000"
- every chart silently broke, because the browser has never heard of a host
named "api". API_PUBLIC_URL is the fix; these tests are what stop it drifting
back to the broken version.
"""

import importlib

from src import api_client, config


def test_url_for_uses_the_internal_address(monkeypatch):
    monkeypatch.setattr(config, "API_URL", "http://api:8000")
    assert api_client.url_for("/health") == "http://api:8000/health"


def test_public_url_for_uses_the_browser_facing_address(monkeypatch):
    monkeypatch.setattr(config, "API_PUBLIC_URL", "http://localhost:8000")
    assert api_client.public_url_for("/charts/x.png") == "http://localhost:8000/charts/x.png"


def test_chart_url_uses_the_public_address_not_the_internal_one(monkeypatch):
    # This is the actual regression: API_URL and API_PUBLIC_URL set to two
    # different things, exactly as docker-compose.yml does it. chart_url()
    # must pick the one a browser can reach.
    monkeypatch.setattr(config, "API_URL", "http://api:8000")
    monkeypatch.setattr(config, "API_PUBLIC_URL", "http://localhost:8000")
    url = api_client.chart_url("/charts/AAPL_price.png")
    assert url == "http://localhost:8000/charts/AAPL_price.png"
    assert "api:8000" not in url


def test_health_and_stream_use_the_internal_address_not_the_public_one(monkeypatch):
    # The other half of the same guarantee: server-to-server calls must not
    # accidentally start using the browser-facing address either.
    monkeypatch.setattr(config, "API_URL", "http://api:8000")
    monkeypatch.setattr(config, "API_PUBLIC_URL", "http://localhost:8000")
    assert api_client.url_for("/health") == "http://api:8000/health"
    assert api_client.url_for("/analyse/stream") == "http://api:8000/analyse/stream"


# --- config.py: the fallback that makes API_PUBLIC_URL optional -------------

def test_api_public_url_falls_back_to_api_url_when_unset(monkeypatch):
    # A plain local run, or a single container, sets only API_URL - and both
    # halves share one "localhost", so falling back is the correct behaviour,
    # not a workaround. Reloaded fresh so config.py's module-level read of
    # the environment actually re-runs with these values.
    monkeypatch.setenv("API_URL", "http://localhost:9000")
    monkeypatch.delenv("API_PUBLIC_URL", raising=False)
    reloaded = importlib.reload(config)
    try:
        assert reloaded.API_PUBLIC_URL == "http://localhost:9000"
    finally:
        importlib.reload(config)   # restore the real environment for later tests


def test_api_public_url_overrides_when_set(monkeypatch):
    monkeypatch.setenv("API_URL", "http://api:8000")
    monkeypatch.setenv("API_PUBLIC_URL", "http://localhost:8000")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.API_URL == "http://api:8000"
        assert reloaded.API_PUBLIC_URL == "http://localhost:8000"
    finally:
        importlib.reload(config)
