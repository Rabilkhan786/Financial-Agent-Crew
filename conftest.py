"""Test settings.

Fast tests run offline. Tests that need Groq or Yahoo are marked "live" and
skipped unless you add --live:

    pytest tests/ -q            the fast suite
    pytest tests/ -q --live     the fast suite plus the live checks
"""

import pytest


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False,
                     help="also run the checks that need the network and an API key")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs the network and a working API key")


def pytest_collection_modifyitems(config, items):
    """Skip the live checks unless --live was passed."""
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
