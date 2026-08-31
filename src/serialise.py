"""Turns the report data into a format that can be sent over the internet
(JSON).

Pandas data and NaN values are not valid JSON, so they get converted here.
"""

import math

import pandas as pd


def clean_number(value):
    """A float that JSON can actually carry, or None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def period_label(index_value):
    """One Series index entry as a plain string."""
    if hasattr(index_value, "date"):
        return index_value.date().isoformat()
    return str(index_value)


def series_to_records(series):
    """A pandas Series as [{"period": ..., "value": ...}, ...].

    Records rather than a bare dict because the order matters - these are
    fiscal years and trading days, and a chart drawn out of order is wrong.
    """
    records = []
    for index_value, value in series.items():
        records.append({"period": period_label(index_value),
                        "value": clean_number(value)})
    return records


def records_to_series(records):
    """The other direction, for the client that wants to plot them."""
    if not records:
        return pd.Series(dtype=float)
    periods = [record["period"] for record in records]
    values = [record["value"] for record in records]
    index = pd.to_datetime(periods, errors="coerce")
    if index.isna().all():
        index = periods
    return pd.Series(values, index=index, dtype=float)


def to_jsonable(value):
    """Anything from the crew state, as something json.dumps can write."""
    if isinstance(value, pd.Series):
        return series_to_records(value)
    if isinstance(value, pd.DataFrame):
        return {str(name): series_to_records(column) for name, column in value.items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, bool):
        return value                      # before the number check: a bool is an int
    if isinstance(value, float):
        return clean_number(value)
    if hasattr(value, "item"):
        # A numpy scalar. .item() gives back the plain Python number.
        try:
            return to_jsonable(value.item())
        except (AttributeError, ValueError):
            return str(value)
    if isinstance(value, (str, int)) or value is None:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
