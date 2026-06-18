from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame

from ztb.strategies.base import Strategy
from ztb.strategies.registry import all, get, list_names


def _sample_df(length: int = 50) -> DataFrame:
    return DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(length)],
            "high": [101.0 + i * 0.1 for i in range(length)],
            "low": [99.0 + i * 0.1 for i in range(length)],
            "close": [100.0 + i * 0.1 for i in range(length)],
            "volume": [1000.0] * length,
        },
        index=pd.date_range("2020-01-01", periods=length, freq="h"),
    )


def _compression_df(length: int = 500) -> DataFrame:
    np.random.seed(42)
    trend = np.linspace(0, 10, length)
    noise = np.random.randn(length) * 0.5
    c = 100.0 + trend + noise
    h = c + np.abs(np.random.randn(length)) * 0.8
    lo = c - np.abs(np.random.randn(length)) * 0.8
    v = 2000.0 + np.random.randn(length) * 100

    idx = pd.date_range("2020-01-01", periods=length, freq="h")
    return DataFrame(
        {
            "open": c - np.random.randn(length) * 0.1,
            "high": h,
            "low": lo,
            "close": c,
            "volume": v.clip(500),
        },
        index=idx,
    )


def test_strategy_is_abstract() -> None:
    with pytest.raises(TypeError):
        Strategy()  # type: ignore[abstract]


def test_get_unknown_raises() -> None:
    with pytest.raises(KeyError, match="Unknown"):
        get("nonexistent_test_strategy")


def test_list_names() -> None:
    names = list_names()
    assert isinstance(names, list)
    assert "sma_cross" in names


def test_all_returns_list() -> None:
    strategies = all()
    assert isinstance(strategies, list)
    assert len(strategies) > 0


def test_get_returns_strategy_class() -> None:
    cls = get("sma_cross")
    assert cls is not None
    assert cls.name == "sma_cross"


class TestSMACross:
    def test_generate_signals(self) -> None:
        cls = get("sma_cross")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    def test_signals_in_range(self) -> None:
        cls = get("sma_cross")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert signals.dropna().between(-1.0, 1.0).all()

    def test_signals_are_float(self) -> None:
        cls = get("sma_cross")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert signals.dtype == float

    def test_warmup_is_flat(self) -> None:
        cls = get("sma_cross")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert (signals.iloc[: strat.warmup] == 0.0).all()

    def test_name_and_params(self) -> None:
        cls = get("sma_cross")
        assert cls.name == "sma_cross"
        assert cls.params == {"fast": 5, "slow": 20, "sl_pct": 0.05, "tp_pct": 0.10}
        assert cls.warmup == 20


class TestCompressionBreakout:
    def test_generate_signals(self) -> None:
        cls = get("compression_breakout")
        strat = cls()
        df = _compression_df(500)
        signals = strat.generate_signals(df)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    def test_signals_in_range(self) -> None:
        cls = get("compression_breakout")
        strat = cls()
        df = _compression_df(500)
        signals = strat.generate_signals(df)
        assert signals.dropna().between(-1.0, 1.0).all()

    def test_signals_are_float(self) -> None:
        cls = get("compression_breakout")
        strat = cls()
        df = _compression_df(500)
        signals = strat.generate_signals(df)
        assert signals.dtype == float

    def test_warmup_is_flat(self) -> None:
        cls = get("compression_breakout")
        strat = cls()
        df = _compression_df(500)
        signals = strat.generate_signals(df)
        assert (signals.iloc[: strat.warmup] == 0.0).all()

    def test_name_and_params(self) -> None:
        cls = get("compression_breakout")
        assert cls.name == "compression_breakout"
        assert cls.warmup == 200

    def test_no_nan_after_warmup(self) -> None:
        cls = get("compression_breakout")
        strat = cls()
        df = _compression_df(500)
        signals = strat.generate_signals(df)
        assert not signals.iloc[strat.warmup :].isna().any()

    def test_signals_in_three_values(self) -> None:
        cls = get("compression_breakout")
        strat = cls()
        df = _compression_df(500)
        signals = strat.generate_signals(df)
        valid = {0.0, 1.0, -1.0}
        assert signals.dropna().isin(valid).all()

    def test_can_produce_long(self) -> None:
        cls = get("compression_breakout")
        strat = cls()
        np.random.seed(42)
        length = 500
        c = 100.0 + np.linspace(0, 20, length) + np.random.randn(length) * 0.5
        h = c + 1.0
        lo = c - 1.0
        v = np.ones(length) * 3000.0
        compress = np.sin(np.linspace(0, 4 * np.pi, length)) * 0.05 + 0.1
        c = c + compress * 10
        idx = pd.date_range("2020-01-01", periods=length, freq="h")
        df = DataFrame(
            {"open": c - 0.05, "high": h, "low": lo, "close": c, "volume": v},
            index=idx,
        )
        signals = strat.generate_signals(df)
        assert signals.iloc[strat.warmup :].nunique() >= 1

    def test_registered(self) -> None:
        names = list_names()
        assert "compression_breakout" in names

    def test_get_from_registry(self) -> None:
        cls = get("compression_breakout")
        assert cls is not None
        assert cls.name == "compression_breakout"

    def test_symbols_default(self) -> None:
        cls = get("compression_breakout")
        assert cls.symbols == []

    def test_timeframe_default(self) -> None:
        cls = get("compression_breakout")
        assert cls.timeframe == "60"

    def test_params_have_seven_keys(self) -> None:
        cls = get("compression_breakout")
        assert len(cls.params) == 7
        for key in (
            "bb_z_entry",
            "bb_width_max_pct",
            "min_vol_pct",
            "adx_entry",
            "adx_exit",
            "trail_atr_mult",
            "max_hold_bars",
        ):
            assert key in cls.params

    def test_default_params_values(self) -> None:
        cls = get("compression_breakout")
        assert cls.params["bb_z_entry"] == -1.0
        assert cls.params["bb_width_max_pct"] == 1.5
        assert cls.params["min_vol_pct"] == 0.3
        assert cls.params["adx_entry"] == 25
        assert cls.params["adx_exit"] == 20
        assert cls.params["trail_atr_mult"] == 2.0
        assert cls.params["max_hold_bars"] == 24

    def test_no_signals_in_flat_no_volume(self) -> None:
        cls = get("compression_breakout")
        strat = cls()
        length = 500
        c = np.ones(length) * 100.0
        idx = pd.date_range("2020-01-01", periods=length, freq="h")
        df = DataFrame(
            {
                "open": c,
                "high": c + 0.5,
                "low": c - 0.5,
                "close": c,
                "volume": np.ones(length) * 100.0,
            },
            index=idx,
        )
        signals = strat.generate_signals(df)
        assert (signals == 0.0).all()

    def test_warmup_200(self) -> None:
        cls = get("compression_breakout")
        strat = cls()
        assert strat.warmup == 200
