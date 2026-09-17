"""Convert pandas values to and from JSON-safe data."""

import math

import pandas as pd


def clean_number(value):
    """Return a finite float or None."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def series_to_records(series):
    """Convert a Series into ordered period/value records."""
    records = []
    for index_value, value in series.items():
        if hasattr(index_value, "date"):
            period = index_value.date().isoformat()
        else:
            period = str(index_value)
        records.append({"period": period, "value": clean_number(value)})
    return records


def records_to_series(records):
    """Convert period/value records back to a pandas Series."""
    if not records:
        return pd.Series(dtype=float)

    periods = [item["period"] for item in records]
    values = [item["value"] for item in records]
    index = pd.to_datetime(periods, errors="coerce")
    if index.isna().all():
        index = periods
    return pd.Series(values, index=index, dtype=float)


def to_jsonable(value):
    """Recursively convert crew output into JSON-safe values."""
    if isinstance(value, pd.Series):
        return series_to_records(value)
    if isinstance(value, pd.DataFrame):
        return {
            str(name): series_to_records(column)
            for name, column in value.items()
        }
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return clean_number(value)
    if hasattr(value, "item"):
        try:
            return to_jsonable(value.item())
        except (AttributeError, ValueError):
            return str(value)
    if isinstance(value, (str, int)) or value is None:
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
