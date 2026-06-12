from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame, DatetimeIndex

from ztb.data.errors import SchemaError
from ztb.data.schema import validate_schema


def _make_valid_df(n: int = 10) -> DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC", name="open_time")
    rng = np.random.default_rng(42)
    base = 50000.0
    opens = base + rng.random(n) * 100
    closes = opens + rng.random(n) * 50 - 25
    lows = np.minimum(opens, closes) - rng.random(n) * 20
    highs = np.maximum(opens, closes) + rng.random(n) * 20
    data = {
        "open": opens.astype("float64"),
        "high": highs.astype("float64"),
        "low": lows.astype("float64"),
        "close": closes.astype("float64"),
        "volume": (np.abs(rng.random(n)) + 1).astype("float64"),
        "turnover": (np.abs(rng.random(n)) + 1).astype("float64"),
    }
    df = DataFrame(data, index=idx)
    df.index.name = "open_time"
    return df


def test_round_trip() -> None:
    df = _make_valid_df()
    result = validate_schema(df)
    pd.testing.assert_frame_equal(df, result)


def test_naive_datetime_raises() -> None:
    df = _make_valid_df()
    df.index = pd.date_range("2025-01-01", periods=len(df), freq="1h")  # no tz
    with pytest.raises(SchemaError, match="timezone-aware"):
        validate_schema(df)


def test_missing_column_raises() -> None:
    df = _make_valid_df()
    df = df.drop(columns=["open"])
    with pytest.raises(SchemaError, match="Missing column"):
        validate_schema(df)


def test_extra_column_raises() -> None:
    df = _make_valid_df()
    df["extra"] = 1.0
    with pytest.raises(SchemaError, match="Unexpected column"):
        validate_schema(df)


def test_wrong_dtype_raises() -> None:
    df = _make_valid_df()
    df["open"] = df["open"].astype("int64")
    with pytest.raises(SchemaError, match="dtype"):
        validate_schema(df)


def test_negative_volume_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "volume"] = -1.0
    with pytest.raises(SchemaError, match="negative"):
        validate_schema(df)


def test_negative_turnover_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "turnover"] = -1.0
    with pytest.raises(SchemaError, match="negative"):
        validate_schema(df)


def test_nan_ohlc_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "close"] = np.nan
    with pytest.raises(SchemaError, match="NaN"):
        validate_schema(df)


def test_nat_index_raises() -> None:
    df = _make_valid_df()
    df.index = DatetimeIndex([pd.NaT] * len(df), tz="UTC")
    with pytest.raises(SchemaError, match="NaT"):
        validate_schema(df)


def test_non_unique_index_raises() -> None:
    df = _make_valid_df()
    df.index = DatetimeIndex([df.index[0]] * len(df), tz="UTC")
    with pytest.raises(SchemaError, match="unique"):
        validate_schema(df)


def test_non_ascending_index_raises() -> None:
    df = _make_valid_df()
    df = df.sort_index(ascending=False)
    with pytest.raises(SchemaError, match="ascending"):
        validate_schema(df)


def test_non_utc_tz_raises() -> None:
    df = _make_valid_df()
    df.index = pd.date_range(
        "2025-01-01", periods=len(df), freq="1h", tz="America/New_York", name="open_time"
    )
    with pytest.raises(SchemaError, match="UTC"):
        validate_schema(df)


def test_valid_ohlc_still_passes() -> None:
    df = _make_valid_df()
    result = validate_schema(df)
    pd.testing.assert_frame_equal(df, result)


def test_inf_ohlc_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "close"] = np.inf
    with pytest.raises(SchemaError, match="infinite"):
        validate_schema(df)


def test_neg_inf_ohlc_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "high"] = -np.inf
    with pytest.raises(SchemaError, match="infinite"):
        validate_schema(df)


def test_nan_volume_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "volume"] = np.nan
    with pytest.raises(SchemaError, match="NaN"):
        validate_schema(df)


def test_inf_volume_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "volume"] = np.inf
    with pytest.raises(SchemaError, match="infinite"):
        validate_schema(df)


def test_nan_turnover_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "turnover"] = np.nan
    with pytest.raises(SchemaError, match="NaN"):
        validate_schema(df)


def test_negative_close_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "close"] = -1.0
    with pytest.raises(SchemaError, match="Close <= 0"):
        validate_schema(df)


def test_zero_close_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "close"] = 0.0
    with pytest.raises(SchemaError, match="Close <= 0"):
        validate_schema(df)


def test_high_less_than_low_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "high"] = df.loc[df.index[0], "low"] - 1.0
    with pytest.raises(SchemaError, match="High < Low"):
        validate_schema(df)


def test_high_less_than_close_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "high"] = df.loc[df.index[0], "close"] - 1.0
    with pytest.raises(SchemaError, match="High < Close"):
        validate_schema(df)


def test_low_greater_than_close_raises() -> None:
    df = _make_valid_df()
    df.loc[df.index[0], "low"] = df.loc[df.index[0], "close"] + 1.0
    with pytest.raises(SchemaError, match="Low > Close"):
        validate_schema(df)
