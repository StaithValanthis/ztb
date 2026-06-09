from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame, DatetimeIndex

from ztb.data.errors import SchemaError
from ztb.data.schema import OHLCV_COLUMNS, validate_schema


def _make_valid_df(n: int = 10) -> DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC", name="open_time")
    data = {col: np.random.randn(n) * 100 + 50000 for col in OHLCV_COLUMNS}
    data["volume"] = np.abs(data["volume"]) + 1
    data["turnover"] = np.abs(data["turnover"]) + 1
    df = DataFrame(data, index=idx)
    df.index.name = "open_time"
    for col in OHLCV_COLUMNS:
        df[col] = df[col].astype("float64")
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
