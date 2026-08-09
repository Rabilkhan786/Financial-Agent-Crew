"""Tests for the pure-Python risk math — fixture-based, no network, no LLM.

Because the math is simple, we can state the expected answers by hand and also
check internal consistency (annualized vol equals the daily std dev times
sqrt(252)).
"""

import statistics
from math import sqrt

import pytest

from investpanel.tools.volatility import (
    annualized_volatility,
    daily_returns,
    max_drawdown,
)


def test_daily_returns_basic():
    # 100 -> 110 is +10%; 110 -> 121 is +10%.
    assert daily_returns([100, 110, 121]) == pytest.approx([0.10, 0.10])


def test_daily_returns_needs_two_prices():
    with pytest.raises(ValueError):
        daily_returns([100])


def test_constant_growth_has_zero_volatility():
    # A perfectly steady +10% each step has no variation -> zero volatility.
    assert annualized_volatility([100, 110, 121, 133.1]) == pytest.approx(0.0)


def test_annualized_volatility_matches_manual_formula():
    prices = [100, 110, 100, 120, 108]
    returns = daily_returns(prices)
    expected = statistics.stdev(returns) * sqrt(252)
    assert annualized_volatility(prices) == pytest.approx(expected)


def test_annualized_volatility_needs_three_prices():
    with pytest.raises(ValueError):
        annualized_volatility([100, 110])


def test_max_drawdown_hand_computed():
    # Peak 110, trough 90 -> (90-110)/110 = -18.18% -> 0.1818 magnitude.
    prices = [100, 110, 90, 95]
    assert max_drawdown(prices) == pytest.approx(20 / 110)


def test_rising_series_has_no_drawdown():
    assert max_drawdown([100, 101, 102, 103]) == pytest.approx(0.0)
