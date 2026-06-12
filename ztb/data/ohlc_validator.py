from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame

from ztb.data.errors import SchemaError

OHLC_COLS = ("open", "high", "low", "close")
OHLCV_COLS = ("open", "high", "low", "close", "volume", "turnover")


def validate_ohlc_values(df: DataFrame) -> DataFrame:
    """Validate OHLC values are logically consistent and finite.

    Raises SchemaError on:
      - missing required columns
      - Infinity / -Infinity in any OHLCV column
      - NaN in any OHLCV column
      - High < Low in any row
      - High < Open in any row
      - High < Close in any row
      - Low > Open in any row
      - Low > Close in any row
    """
    for col in OHLCV_COLS:
        if col not in df.columns:
            raise SchemaError(f"Missing column for OHLC validation: {col}")

    for col in OHLCV_COLS:
        col_series = df[col]
        if col_series.isna().any():
            raise SchemaError(f"Column '{col}' contains NaN values")
        if np.isinf(col_series).any():
            raise SchemaError(f"Column '{col}' contains infinite values")

    violations: list[str] = []

    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    close = df["close"]

    mask = high < low
    if mask.any():
        indices = df.index[mask].tolist()
        violations.append(f"High < Low at {len(indices)} row(s): {_fmt_indices(indices)}")

    mask = high < open_
    if mask.any():
        indices = df.index[mask].tolist()
        violations.append(f"High < Open at {len(indices)} row(s): {_fmt_indices(indices)}")

    mask = high < close
    if mask.any():
        indices = df.index[mask].tolist()
        violations.append(f"High < Close at {len(indices)} row(s): {_fmt_indices(indices)}")

    mask = low > open_
    if mask.any():
        indices = df.index[mask].tolist()
        violations.append(f"Low > Open at {len(indices)} row(s): {_fmt_indices(indices)}")

    mask = low > close
    if mask.any():
        indices = df.index[mask].tolist()
        violations.append(f"Low > Close at {len(indices)} row(s): {_fmt_indices(indices)}")

    if violations:
        raise SchemaError("OHLC value validation failed: " + "; ".join(violations))

    return df


def check_nan_inf(df: DataFrame, *, columns: tuple[str, ...] = OHLCV_COLS) -> DataFrame:
    """NaN/Inf fail-safe killswitch for DataFrame columns.

    Raises SchemaError if any of the specified columns contain NaN or
    Infinity values.  Designed as a drop-in safety net that can be
    inserted at any pipeline boundary (data loading, engine entry,
    indicator output, signal generation).

    Returns the DataFrame unchanged when the check passes.
    """
    for col in columns:
        if col not in df.columns:
            raise SchemaError(f"Missing column for NaN/Inf check: {col}")
        col_series = df[col]
        if col_series.isna().any():
            raise SchemaError(f"NaN/Inf killswitch triggered: column '{col}' contains NaN")
        if np.isinf(col_series).any():
            raise SchemaError(f"NaN/Inf killswitch triggered: column '{col}' contains Inf")
    return df


def _fmt_indices(indices: list[pd.Timestamp]) -> str:
    if len(indices) <= 5:
        return ", ".join(str(ts) for ts in indices)
    return ", ".join(str(ts) for ts in indices[:5]) + f", ... ({len(indices) - 5} more)"
