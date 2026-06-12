from __future__ import annotations

import pandas as pd
from pandas import DataFrame

from ztb.data.errors import SchemaError
from ztb.data.ohlc_validator import validate_ohlc_values

OHLCV_COLUMNS: list[str] = ["open", "high", "low", "close", "volume", "turnover"]

CATEGORY_TIMEFRAMES: dict[str, list[str]] = {
    "linear": ["1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"],
    "inverse": ["1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"],
    "spot": ["1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"],
    "option": ["1", "3", "5", "15", "30", "60", "120", "240", "360", "720", "D", "W", "M"],
}

VALID_INTERVALS: set[str] = set()
for _tf in CATEGORY_TIMEFRAMES.values():
    VALID_INTERVALS.update(_tf)


def validate_schema(df: DataFrame) -> DataFrame:
    """Validate a DataFrame matches the canonical OHLCV schema.

    Raises SchemaError on:
      - missing or extra columns
      - wrong dtypes
      - non-UTC or non-datetime index
      - index has NaT
      - index not unique or not ascending
      - any NaN in open/high/low/close
      - negative volume or turnover
    """
    for col in OHLCV_COLUMNS:
        if col not in df.columns:
            raise SchemaError(f"Missing column: {col}")

    for col in df.columns:
        if col not in OHLCV_COLUMNS:
            raise SchemaError(f"Unexpected column: {col}")

    for col in OHLCV_COLUMNS:
        if df[col].dtype != "float64":
            raise SchemaError(f"Column '{col}' has dtype {df[col].dtype}, expected float64")

    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise SchemaError(f"Index must be DatetimeIndex, got {type(idx).__name__}")

    if idx.tz is None:
        raise SchemaError("Index must be timezone-aware (UTC)")

    if str(idx.tz) != "UTC":
        raise SchemaError(f"Index must be UTC, got {idx.tz}")

    if idx.hasnans:
        raise SchemaError("Index contains NaT values")

    if not idx.is_unique:
        raise SchemaError("Index is not unique")

    if not idx.is_monotonic_increasing:
        raise SchemaError("Index is not ascending")

    for col in ("open", "high", "low", "close"):
        if df[col].isna().any():
            raise SchemaError(f"Column '{col}' contains NaN values")

    validate_ohlc_values(df)

    if (df["volume"] < 0).any():
        raise SchemaError("Column 'volume' contains negative values")

    if (df["turnover"] < 0).any():
        raise SchemaError("Column 'turnover' contains negative values")

    return df
