from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame

from ztb.data.errors import SchemaError
from ztb.data.ohlc_validator import check_nan_inf, validate_ohlc_values


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


def _make_valid_single_value(open_v=100.0, high=110.0, low=90.0, close=105.0) -> DataFrame:
    idx = pd.DatetimeIndex([pd.Timestamp("2025-01-01 00:00", tz="UTC")], name="open_time")
    data = {
        "open": np.float64(open_v),
        "high": np.float64(high),
        "low": np.float64(low),
        "close": np.float64(close),
        "volume": np.float64(100.0),
        "turnover": np.float64(5000.0),
    }
    return DataFrame(data, index=idx)


class TestValidateOHLCValues:

    def test_valid_ohlc_round_trip(self) -> None:
        df = _make_valid_df(10)
        result = validate_ohlc_values(df)
        pd.testing.assert_frame_equal(df, result)

    def test_valid_single_bar(self) -> None:
        df = _make_valid_single_value()
        result = validate_ohlc_values(df)
        pd.testing.assert_frame_equal(df, result)

    def test_high_low_equal_passes(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=100.0, low=100.0, close=100.0)
        result = validate_ohlc_values(df)
        pd.testing.assert_frame_equal(df, result)

    def test_high_less_than_low_raises(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=90.0, low=110.0, close=105.0)
        with pytest.raises(SchemaError, match="High < Low"):
            validate_ohlc_values(df)

    def test_high_less_than_open_raises(self) -> None:
        df = _make_valid_single_value(open_v=200.0, high=150.0, low=90.0, close=105.0)
        with pytest.raises(SchemaError, match="High < Open"):
            validate_ohlc_values(df)

    def test_high_less_than_close_raises(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=90.0, low=85.0, close=200.0)
        with pytest.raises(SchemaError, match="High < Close"):
            validate_ohlc_values(df)

    def test_low_greater_than_open_raises(self) -> None:
        df = _make_valid_single_value(open_v=50.0, high=200.0, low=80.0, close=105.0)
        with pytest.raises(SchemaError, match="Low > Open"):
            validate_ohlc_values(df)

    def test_low_greater_than_close_raises(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=200.0, low=150.0, close=50.0)
        with pytest.raises(SchemaError, match="Low > Close"):
            validate_ohlc_values(df)

    def test_multiple_violations_reported(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=50.0, low=200.0, close=150.0)
        with pytest.raises(SchemaError) as excinfo:
            validate_ohlc_values(df)
        msg = str(excinfo.value)
        assert "High < Low" in msg
        assert "High < Open" in msg
        assert "High < Close" in msg
        assert "Low > Open" in msg
        assert "Low > Close" in msg

    def test_violation_in_one_row_of_many(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[5], "high"] = df.loc[df.index[5], "low"] - 1.0
        with pytest.raises(SchemaError, match="High < Low"):
            validate_ohlc_values(df)

    def test_missing_column_raises(self) -> None:
        df = _make_valid_df(10)
        df = df.drop(columns=["open"])
        with pytest.raises(SchemaError, match="Missing column"):
            validate_ohlc_values(df)

    def test_nan_in_column_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "high"] = np.nan
        with pytest.raises(SchemaError, match="NaN"):
            validate_ohlc_values(df)

    def test_inf_in_column_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "close"] = np.inf
        with pytest.raises(SchemaError, match="infinite"):
            validate_ohlc_values(df)

    def test_neg_inf_in_column_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "open"] = -np.inf
        with pytest.raises(SchemaError, match="infinite"):
            validate_ohlc_values(df)

    def test_empty_df_passes(self) -> None:
        cols = ["open", "high", "low", "close", "volume", "turnover"]
        df = DataFrame(columns=cols).set_index(
            pd.DatetimeIndex([], tz="UTC", name="open_time")
        )
        for c in cols:
            df[c] = df[c].astype("float64")
        result = validate_ohlc_values(df)
        assert len(result) == 0

    def test_negative_close_raises(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=110.0, low=90.0, close=-1.0)
        with pytest.raises(SchemaError, match="Close <= 0"):
            validate_ohlc_values(df)

    def test_zero_close_raises(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=110.0, low=90.0, close=0.0)
        with pytest.raises(SchemaError, match="Close <= 0"):
            validate_ohlc_values(df)

    def test_negative_open_raises(self) -> None:
        df = _make_valid_single_value(open_v=-1.0, high=110.0, low=90.0, close=105.0)
        with pytest.raises(SchemaError, match="Open <= 0"):
            validate_ohlc_values(df)

    def test_zero_open_raises(self) -> None:
        df = _make_valid_single_value(open_v=0.0, high=110.0, low=90.0, close=105.0)
        with pytest.raises(SchemaError, match="Open <= 0"):
            validate_ohlc_values(df)

    def test_negative_high_raises(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=-1.0, low=90.0, close=105.0)
        with pytest.raises(SchemaError, match="High <= 0"):
            validate_ohlc_values(df)

    def test_zero_high_raises(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=0.0, low=90.0, close=105.0)
        with pytest.raises(SchemaError, match="High <= 0"):
            validate_ohlc_values(df)

    def test_negative_low_raises(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=110.0, low=-1.0, close=105.0)
        with pytest.raises(SchemaError, match="Low <= 0"):
            validate_ohlc_values(df)

    def test_zero_low_raises(self) -> None:
        df = _make_valid_single_value(open_v=100.0, high=110.0, low=0.0, close=105.0)
        with pytest.raises(SchemaError, match="Low <= 0"):
            validate_ohlc_values(df)


class TestCheckNanInf:

    def test_pass_on_valid_data(self) -> None:
        df = _make_valid_df(10)
        result = check_nan_inf(df)
        pd.testing.assert_frame_equal(df, result)

    def test_nan_in_open_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "open"] = np.nan
        with pytest.raises(SchemaError, match="NaN"):
            check_nan_inf(df)

    def test_nan_in_high_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "high"] = np.nan
        with pytest.raises(SchemaError, match="NaN"):
            check_nan_inf(df)

    def test_nan_in_low_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "low"] = np.nan
        with pytest.raises(SchemaError, match="NaN"):
            check_nan_inf(df)

    def test_nan_in_close_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "close"] = np.nan
        with pytest.raises(SchemaError, match="NaN"):
            check_nan_inf(df)

    def test_nan_in_volume_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "volume"] = np.nan
        with pytest.raises(SchemaError, match="NaN"):
            check_nan_inf(df)

    def test_nan_in_turnover_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "turnover"] = np.nan
        with pytest.raises(SchemaError, match="NaN"):
            check_nan_inf(df)

    def test_inf_in_ohlc_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "close"] = np.inf
        with pytest.raises(SchemaError, match="Inf"):
            check_nan_inf(df)

    def test_neg_inf_raises(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "high"] = -np.inf
        with pytest.raises(SchemaError, match="Inf"):
            check_nan_inf(df)

    def test_custom_columns(self) -> None:
        df = _make_valid_df(10)
        df["indicator"] = np.float64(1.0)
        df.loc[df.index[0], "indicator"] = np.nan
        with pytest.raises(SchemaError, match="NaN"):
            check_nan_inf(df, columns=("indicator",))

    def test_missing_column_raises(self) -> None:
        df = _make_valid_df(10)
        df = df.drop(columns=["high"])
        with pytest.raises(SchemaError, match="Missing column"):
            check_nan_inf(df)

    def test_empty_df_passes(self) -> None:
        cols = ["open", "high", "low", "close", "volume", "turnover"]
        df = DataFrame(columns=cols).set_index(
            pd.DatetimeIndex([], tz="UTC", name="open_time")
        )
        for c in cols:
            df[c] = df[c].astype("float64")
        result = check_nan_inf(df)
        assert len(result) == 0

    def test_custom_columns_passthrough(self) -> None:
        df = _make_valid_df(10)
        result = check_nan_inf(df, columns=("open", "close"))
        pd.testing.assert_frame_equal(df, result)

    def test_volume_allows_zero(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "volume"] = np.float64(0.0)
        result = check_nan_inf(df)
        pd.testing.assert_frame_equal(df, result)

    def test_multiple_nan_raises_first(self) -> None:
        df = _make_valid_df(10)
        df.loc[df.index[0], "open"] = np.nan
        df.loc[df.index[1], "close"] = np.nan
        with pytest.raises(SchemaError, match="NaN"):
            check_nan_inf(df)
