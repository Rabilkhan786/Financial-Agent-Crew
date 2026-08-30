"""Tests for the JSON conversion that sits between the API and the app.

This is the layer where a pandas object stops being a pandas object. Two
things here have bitten real projects and are worth pinning down: NaN, which
Python will happily write into JSON as a bare `NaN` that no browser can parse,
and a Timestamp index, which becomes a millisecond epoch number if left alone
and then needs the client to guess the unit.
"""

import json
import math

import numpy as np
import pandas as pd

from src import serialise


def test_a_nan_becomes_null_not_the_string_nan():
    assert serialise.clean_number(float("nan")) is None
    assert serialise.clean_number(float("inf")) is None
    assert serialise.clean_number(float("-inf")) is None


def test_an_ordinary_number_survives():
    assert serialise.clean_number(0.207) == 0.207
    assert serialise.clean_number(0) == 0.0
    assert serialise.clean_number(None) is None


def test_a_dated_series_becomes_iso_dates_not_epoch_numbers():
    series = pd.Series([1.0, 2.0], index=pd.to_datetime(["2023-01-01", "2024-01-01"]))
    records = serialise.series_to_records(series)
    assert records == [{"period": "2023-01-01", "value": 1.0},
                       {"period": "2024-01-01", "value": 2.0}]


def test_a_series_keeps_its_order():
    # These are fiscal years and trading days; out of order is simply wrong.
    series = pd.Series([3.0, 1.0, 2.0], index=["c", "a", "b"])
    periods = [record["period"] for record in serialise.series_to_records(series)]
    assert periods == ["c", "a", "b"]


def test_a_nan_inside_a_series_becomes_null():
    series = pd.Series([1.0, np.nan], index=["a", "b"])
    assert serialise.series_to_records(series)[1]["value"] is None


def test_records_round_trip_back_into_a_series():
    original = pd.Series([1.5, 2.5], index=pd.to_datetime(["2023-01-01", "2024-01-01"]))
    rebuilt = serialise.records_to_series(serialise.series_to_records(original))
    assert list(rebuilt.values) == [1.5, 2.5]
    assert list(rebuilt.index) == list(original.index)


def test_empty_records_give_an_empty_series():
    assert serialise.records_to_series([]).empty


# --- to_jsonable, the one the API actually calls ----------------------------

def test_a_whole_nested_state_becomes_json_safe():
    state = {
        "ticker": "AAPL",
        "fundamentals": {
            "metrics": {"operating_margin": np.float64(0.207), "net_margin": np.nan},
            "series": {"revenue": pd.Series([1.0, 2.0], index=["2023", "2024"])},
            "available": True,
        },
        "red_flags": [{"code": "high_leverage", "severity": "high"}],
        "count": np.int64(5),
    }
    result = serialise.to_jsonable(state)

    # The real test: it survives a round trip through strict JSON.
    text = json.dumps(result, allow_nan=False)
    back = json.loads(text)

    assert back["fundamentals"]["metrics"]["operating_margin"] == 0.207
    assert back["fundamentals"]["metrics"]["net_margin"] is None
    assert back["fundamentals"]["available"] is True
    assert back["count"] == 5
    assert back["fundamentals"]["series"]["revenue"][0] == {"period": "2023", "value": 1.0}


def test_a_bool_stays_a_bool_and_does_not_become_a_number():
    # bool is a subclass of int, so an ordering mistake in to_jsonable turns
    # True into 1 and the UI's `if available` checks start reading oddly.
    result = serialise.to_jsonable({"yes": True, "no": False})
    assert result["yes"] is True
    assert result["no"] is False


def test_a_timestamp_becomes_a_string():
    result = serialise.to_jsonable({"when": pd.Timestamp("2024-03-01")})
    assert isinstance(result["when"], str)
    assert result["when"].startswith("2024-03-01")


def test_nothing_in_a_converted_state_is_still_a_nan_float():
    state = {"a": float("nan"), "b": [float("inf"), 1.0], "c": {"d": np.nan}}
    result = serialise.to_jsonable(state)
    json.dumps(result, allow_nan=False)      # raises if any NaN survived
    assert result["a"] is None
    assert result["b"] == [None, 1.0]
    assert result["c"]["d"] is None
