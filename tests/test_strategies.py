from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame

from ztb.features.indicators import atr, ema, sma
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


class TestAdaptiveVolTrend:
    _PARAMS = {
        "vol_lookback": 63,
        "atr_period": 21,
        "sma_period": 50,
        "range_multiplier": 1.5,
        "vol_z_threshold": 0.5,
        "trend_fast": 12,
        "trend_slow": 26,
    }

    @staticmethod
    def _df(n: int = 300, seed: int = 42) -> DataFrame:
        np.random.seed(seed)
        close = 50000.0 + np.cumsum(np.random.randn(n) * 50)
        high = close + np.abs(np.random.randn(n)) * 30
        low = close - np.abs(np.random.randn(n)) * 30
        return DataFrame(
            {
                "open": close + np.random.randn(n) * 10,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2020-01-01", periods=n, freq="h"),
        )

    def test_registration(self) -> None:
        cls = get("adaptive_vol_trend")
        assert cls.name == "adaptive_vol_trend"
        assert "adaptive_vol_trend" in list_names()

    def test_generate_signals(self) -> None:
        cls = get("adaptive_vol_trend")
        strat = cls()
        df = self._df(200)
        signals = strat.generate_signals(df)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    def test_signals_in_range(self) -> None:
        s = get("adaptive_vol_trend")()
        df = self._df(200)
        signals = s.generate_signals(df)
        assert signals.dropna().between(-1.0, 1.0).all()

    def test_signals_no_nan(self) -> None:
        s = get("adaptive_vol_trend")()
        df = self._df(200)
        signals = s.generate_signals(df)
        assert signals.isna().sum() == 0

    def test_signals_are_float(self) -> None:
        s = get("adaptive_vol_trend")()
        df = self._df(200)
        signals = s.generate_signals(df)
        assert signals.dtype == float

    def test_warmup_is_flat(self) -> None:
        s = get("adaptive_vol_trend")()
        df = self._df(200)
        signals = s.generate_signals(df)
        assert (signals.iloc[:84] == 0.0).all()

    def test_name_and_params(self) -> None:
        cls = get("adaptive_vol_trend")
        assert cls.name == "adaptive_vol_trend"
        assert cls.params == self._PARAMS
        assert cls.warmup == 84

    def test_regime_classification(self) -> None:
        s = get("adaptive_vol_trend")()
        cls = get("adaptive_vol_trend")
        vol_lookback = int(cls.params["vol_lookback"])
        atr_period = int(cls.params["atr_period"])
        sma_period = int(cls.params["sma_period"])
        range_multiplier = float(cls.params["range_multiplier"])
        vol_z_threshold = float(cls.params["vol_z_threshold"])
        trend_fast = int(cls.params["trend_fast"])
        trend_slow = int(cls.params["trend_slow"])

        n = 200
        np.random.seed(99)
        close = 50000.0 + np.cumsum(np.random.randn(n) * 20)
        high = close + np.abs(np.random.randn(n)) * 15
        low = close - np.abs(np.random.randn(n)) * 15
        df = DataFrame(
            {
                "open": close + np.random.randn(n) * 5,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2020-01-01", periods=n, freq="h"),
        )

        atr_val = atr(df["high"], df["low"], df["close"], atr_period)
        atr_mean = atr_val.rolling(window=vol_lookback, min_periods=vol_lookback).mean()
        atr_std = atr_val.rolling(window=vol_lookback, min_periods=vol_lookback).std(ddof=0)
        z_score = (atr_val - atr_mean) / atr_std.replace(0, pd.NA)
        sma_val = sma(df["close"], sma_period)
        ema_fast = ema(df["close"], trend_fast)
        ema_slow = ema(df["close"], trend_slow)

        signals = s.generate_signals(df)
        post_mask = pd.Series(True, index=df.index)
        post_mask.iloc[: s.warmup] = False

        for i in range(s.warmup, len(df)):
            z = z_score.iloc[i]
            if pd.isna(z):
                assert signals.iloc[i] == 0.0, f"NaN z at {i}: signal={signals.iloc[i]}"
            elif z < vol_z_threshold:
                upper = sma_val.iloc[i] + range_multiplier * atr_val.iloc[i]
                lower = sma_val.iloc[i] - range_multiplier * atr_val.iloc[i]
                if df["close"].iloc[i] > upper:
                    msg = (
                        f"LOW-VOL LONG fail at {i}: close={df['close'].iloc[i]:.1f},"
                        f" upper={upper:.1f}, sig={signals.iloc[i]}"
                    )
                    assert signals.iloc[i] == 1.0, msg
                elif df["close"].iloc[i] < lower:
                    msg = (
                        f"LOW-VOL SHORT fail at {i}: close={df['close'].iloc[i]:.1f},"
                        f" lower={lower:.1f}, sig={signals.iloc[i]}"
                    )
                    assert signals.iloc[i] == -1.0, msg
                else:
                    msg = (
                        f"LOW-VOL FLAT fail at {i}: close={df['close'].iloc[i]:.1f},"
                        f" upper={upper:.1f}, lower={lower:.1f}, sig={signals.iloc[i]}"
                    )
                    assert signals.iloc[i] == 0.0, msg
            else:
                if ema_fast.iloc[i] > ema_slow.iloc[i]:
                    msg = (
                        f"HIGH-VOL LONG fail at {i}: fast={ema_fast.iloc[i]:.1f},"
                        f" slow={ema_slow.iloc[i]:.1f}, sig={signals.iloc[i]}"
                    )
                    assert signals.iloc[i] == 1.0, msg
                elif ema_fast.iloc[i] < ema_slow.iloc[i]:
                    msg = (
                        f"HIGH-VOL SHORT fail at {i}: fast={ema_fast.iloc[i]:.1f},"
                        f" slow={ema_slow.iloc[i]:.1f}, sig={signals.iloc[i]}"
                    )
                    assert signals.iloc[i] == -1.0, msg
                else:
                    msg = (
                        f"HIGH-VOL FLAT fail at {i}: fast={ema_fast.iloc[i]:.1f},"
                        f" slow={ema_slow.iloc[i]:.1f}, sig={signals.iloc[i]}"
                    )
                    assert signals.iloc[i] == 0.0, msg

    def test_no_lookahead(self) -> None:
        s = get("adaptive_vol_trend")()
        df = self._df(300)
        full_signals = s.generate_signals(df)

        for truncation_point in range(100, 250, 25):
            truncated = df.iloc[: truncation_point + 1].copy()
            trunc_signals = s.generate_signals(truncated)
            msg = (
                f"Lookahead at {truncation_point}:"
                f" full={full_signals.iloc[truncation_point]},"
                f" trunc={trunc_signals.iloc[truncation_point]}"
            )
            assert full_signals.iloc[truncation_point] == trunc_signals.iloc[truncation_point], msg
