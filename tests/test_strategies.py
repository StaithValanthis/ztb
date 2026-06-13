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
        assert cls.params == {"fast": 5, "slow": 20}
        assert cls.warmup == 20


@pytest.fixture
def bearish_4h_df() -> DataFrame:
    n = 500
    np.random.seed(42)
    base = 50000.0
    trend = np.linspace(0, -20000, n)
    noise = np.random.randn(n) * 200
    closes = base + trend + noise
    opens = closes + np.random.randn(n) * 50
    highs = np.maximum(opens, closes) + np.abs(np.random.randn(n)) * 100
    lows = np.minimum(opens, closes) - np.abs(np.random.randn(n)) * 100
    return DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": np.ones(n) * 1000},
        index=pd.date_range("2021-06-01", periods=n, freq="4h"),
    )


class TestBearishResumption:
    def test_registration(self) -> None:
        cls = get("bearish_resumption")
        assert cls.name == "bearish_resumption"
        assert "bearish_resumption" in list_names()

    def test_params_defaults(self) -> None:
        cls = get("bearish_resumption")
        expected = {
            "adx_threshold": 25,
            "ema_fast": 20,
            "ema_slow": 100,
            "ema_mid": 50,
            "bb_width_threshold": 2.0,
            "daily_ema_trend": 200,
            "min_retrace_pct": 3.0,
            "exhaustion_adx": 20,
            "bb_z_threshold": -0.5,
            "trail_atr_mult": 2.5,
        }
        assert cls.params == expected

    def test_generate_signals_len(self, bearish_4h_df: DataFrame) -> None:
        s = get("bearish_resumption")()
        signals = s.generate_signals(bearish_4h_df)
        assert len(signals) == len(bearish_4h_df)

    def test_signals_in_range(self, bearish_4h_df: DataFrame) -> None:
        s = get("bearish_resumption")()
        signals = s.generate_signals(bearish_4h_df)
        valid = signals.dropna()
        assert valid.between(-1.0, 0.0).all()
        assert (valid != 1.0).all()

    def test_warmup_is_flat(self, bearish_4h_df: DataFrame) -> None:
        s = get("bearish_resumption")()
        signals = s.generate_signals(bearish_4h_df)
        assert (signals.iloc[: s.warmup] == 0.0).all()

    def test_no_nan(self, bearish_4h_df: DataFrame) -> None:
        s = get("bearish_resumption")()
        signals = s.generate_signals(bearish_4h_df)
        assert signals.iloc[s.warmup :].isna().sum() == 0

    def test_multi_tf_resampling(self, bearish_4h_df: DataFrame) -> None:
        _ = get("bearish_resumption")().generate_signals(bearish_4h_df)
        daily = (
            bearish_4h_df.resample("D")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )
        assert len(daily) > 0
        assert daily.index[0] <= bearish_4h_df.index[0] + pd.Timedelta(hours=28)
        assert "close" in daily.columns

    def test_common_precondition(self) -> None:
        n = 400
        closes = np.linspace(50000, 55000, n)
        cols = {
            "open": closes - 100,
            "high": closes + 100,
            "low": closes - 100,
            "close": closes,
            "volume": np.ones(n) * 1000,
        }
        df = DataFrame(cols, index=pd.date_range("2022-01-01", periods=n, freq="4h"))
        s = get("bearish_resumption")()
        signals = s.generate_signals(df)
        assert (signals == 0.0).all()

    @staticmethod
    def _crash_bounce_4h() -> DataFrame:
        n = 1200
        np.random.seed(42)
        closes = np.ones(n) * 50000
        for i in range(1, 300):
            closes[i] = closes[i - 1] - 2 + np.random.randn() * 20
        for i in range(300, 800):
            closes[i] = closes[i - 1] - 10 + np.random.randn() * 5
        for i in range(800, 830):
            closes[i] = closes[i - 1] - 200 + np.random.randn() * 30
        for i in range(830, 860):
            closes[i] = closes[i - 1] + 100 + np.random.randn() * 20
        for i in range(860, n):
            closes[i] = closes[i - 1] - 8 + np.random.randn() * 10
        opens = closes + np.random.randn(n) * 20
        highs = np.maximum(opens, closes) + np.abs(np.random.randn(n)) * 40
        lows = np.minimum(opens, closes) - np.abs(np.random.randn(n)) * 40
        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2021-01-01", periods=n, freq="4h"),
        )

    @staticmethod
    def _low_vol_1h(df: DataFrame) -> DataFrame:
        idx_start = df.index[0] - pd.Timedelta(hours=48)
        n_bar = int((df.index[-1] - idx_start).total_seconds() / 3600) + 1
        np.random.seed(99)
        amp = np.linspace(100, 0.5, n_bar)
        c = 50000 + np.random.randn(n_bar) * amp
        o = c + np.random.randn(n_bar) * amp * 0.1
        h = np.maximum(o, c) + np.abs(np.random.randn(n_bar)) * amp * 0.2
        l = np.minimum(o, c) - np.abs(np.random.randn(n_bar)) * amp * 0.2
        return DataFrame(
            {"open": o, "high": h, "low": l, "close": c, "volume": np.ones(n_bar) * 1000},
            index=pd.date_range(idx_start, periods=n_bar, freq="1h"),
        )

    @staticmethod
    def _mode_b_1h(df: DataFrame) -> DataFrame:
        idx_start = df.index[0] - pd.Timedelta(hours=48)
        n_bar = int((df.index[-1] - idx_start).total_seconds() / 3600) + 1
        np.random.seed(99)
        c = 50000 + np.linspace(0, -3000, n_bar) + np.random.randn(n_bar) * 25
        o = c + np.random.randn(n_bar) * 15
        h = np.maximum(o, c) + np.abs(np.random.randn(n_bar)) * 35
        l = np.minimum(o, c) - np.abs(np.random.randn(n_bar)) * 35
        return DataFrame(
            {"open": o, "high": h, "low": l, "close": c, "volume": np.ones(n_bar) * 1000},
            index=pd.date_range(idx_start, periods=n_bar, freq="1h"),
        )

    def test_mode_a_entry(self) -> None:
        from unittest.mock import patch

        df = self._crash_bounce_4h()
        df_1h = self._low_vol_1h(df)
        with patch("ztb.data.loader.load") as mock_load:
            mock_load.return_value = df_1h
            s = get("bearish_resumption")()
            signals = s.generate_signals(df)

        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Mode A entry should produce -1 signals"
        assert post.dropna().between(-1.0, 0.0).all()

    def test_mode_b_entry(self) -> None:
        from unittest.mock import patch

        df = self._crash_bounce_4h()
        df_1h = self._mode_b_1h(df)
        with patch("ztb.data.loader.load") as mock_load:
            mock_load.return_value = df_1h
            s = get("bearish_resumption")()
            signals = s.generate_signals(df)

        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Mode B entry should produce -1 signals"
        assert post.dropna().between(-1.0, 0.0).all()

    def test_exit_on_trailing_stop(self) -> None:
        from unittest.mock import patch

        df = self._crash_bounce_4h()
        df_1h = self._low_vol_1h(df)
        with patch("ztb.data.loader.load") as mock_load:
            mock_load.return_value = df_1h
            s = get("bearish_resumption")()
            signals = s.generate_signals(df)

        post = signals.iloc[s.warmup :]
        entry_indices = post[post == -1.0].index.tolist()
        exit_indices = post[post == 0.0].index.tolist()
        assert len(entry_indices) >= 2, "Should have at least one entry followed by exit"
        first_entry = entry_indices[0]
        later_zeros = [idx for idx in exit_indices if idx > first_entry]
        assert len(later_zeros) > 0, "Should have exit after entry"

    def test_live_disarmed(self) -> None:
        from ztb.execution.errors import LiveDisarmedError
        from ztb.execution.live_guard import LiveGuard

        LiveGuard.disarm()
        with pytest.raises(LiveDisarmedError):
            LiveGuard.assert_live_allowed()
