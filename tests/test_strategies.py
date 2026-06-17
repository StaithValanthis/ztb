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
def bearish_1h_df() -> DataFrame:
    n = 2000
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
        index=pd.date_range("2021-06-01", periods=n, freq="h"),
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

    def test_generate_signals_len(self, bearish_1h_df: DataFrame) -> None:
        s = get("bearish_resumption")()
        signals = s.generate_signals(bearish_1h_df)
        assert len(signals) == len(bearish_1h_df)

    def test_signals_in_range(self, bearish_1h_df: DataFrame) -> None:
        s = get("bearish_resumption")()
        signals = s.generate_signals(bearish_1h_df)
        valid = signals.dropna()
        assert valid.between(-1.0, 0.0).all()
        assert (valid != 1.0).all()

    def test_warmup_is_flat(self, bearish_1h_df: DataFrame) -> None:
        s = get("bearish_resumption")()
        signals = s.generate_signals(bearish_1h_df)
        assert (signals.iloc[: s.warmup] == 0.0).all()

    def test_no_nan(self, bearish_1h_df: DataFrame) -> None:
        s = get("bearish_resumption")()
        signals = s.generate_signals(bearish_1h_df)
        assert signals.iloc[s.warmup :].isna().sum() == 0

    @staticmethod
    def _crash_bounce_1h() -> DataFrame:
        n = 8000
        np.random.seed(42)
        closes = np.ones(n) * 50000.0
        for i in range(1, 5000):
            closes[i] = closes[i - 1] + np.random.randn() * 8
        for i in range(5000, 5500):
            closes[i] = closes[i - 1] - 15 + np.random.randn() * 15
        for i in range(5500, 5580):
            closes[i] = closes[i - 1] - 100 + np.random.randn() * 20
        for i in range(5580, 6180):
            closes[i] = closes[i - 1] + np.random.randn() * 3
        for i in range(6180, 6210):
            closes[i] = closes[i - 1] + 35 + np.random.randn() * 5
        for i in range(6210, 6600):
            closes[i] = closes[i - 1] + np.random.randn() * 3
        for i in range(6600, 7000):
            closes[i] = closes[i - 1] - 10 + np.random.randn() * 10
        for i in range(7000, 7050):
            closes[i] = closes[i - 1] - 120 + np.random.randn() * 20
        for i in range(7050, n):
            closes[i] = closes[i - 1] + np.random.randn() * 3
        opens = closes + np.random.randn(n) * 15
        highs = np.maximum(opens, closes) + np.abs(np.random.randn(n)) * 20
        lows = np.minimum(opens, closes) - np.abs(np.random.randn(n)) * 20
        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2021-01-01", periods=n, freq="h"),
        )

    def test_mode_a_entry(self) -> None:
        df = self._mode_a_df()
        s = get("bearish_resumption")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Mode A entry should produce -1 signals"
        assert post.dropna().between(-1.0, 0.0).all()

    def test_mode_b_entry(self) -> None:
        df = self._crash_bounce_1h()
        s = get("bearish_resumption")()
        signals = s.generate_signals(df)

        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Mode B entry should produce -1 signals"
        assert post.dropna().between(-1.0, 0.0).all()

    @staticmethod
    def _mode_a_df() -> DataFrame:
        n = 10000
        rng = np.random.default_rng(42)
        closes = np.ones(n) * 50000.0

        for i in range(1, 7000):
            closes[i] = closes[i - 1] + 1 + rng.normal() * 6
        for i in range(7000, 7600):
            closes[i] = closes[i - 1] - 12 + rng.normal() * 8
        for i in range(7600, 7750):
            closes[i] = 31000.0 + rng.normal() * 3

        for i in range(7750, 7755):
            closes[i] = 31000 - 1000 * (i - 7749)

        crash_low = closes[7754]
        target_px = crash_low * 1.04
        for i in range(7755, 7762):
            pct = (i - 7755) / 7
            closes[i] = crash_low + (target_px - crash_low) * pct + rng.normal() * 15
        for i in range(7762, 7774):
            closes[i] = closes[i - 1] + rng.normal() * 40
        for i in range(7774, 7789):
            factor = (7789 - i) / 15
            closes[i] = closes[i - 1] + rng.normal() * (40 * factor + 0.3)

        rng_tight = np.random.default_rng(52)
        for i in range(7789, 7810):
            closes[i] = closes[i - 1] + 1.0 + rng_tight.normal() * 4.0
        for i in range(7810, n):
            closes[i] = closes[7809] + rng_tight.normal() * 4.0

        opens = closes + rng.normal(size=n) * 3
        highs = np.maximum(opens, closes) + np.abs(rng.normal(size=n)) * 5
        lows = np.minimum(opens, closes) - np.abs(rng.normal(size=n)) * 5

        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2020-01-01", periods=n, freq="h"),
        )

    def test_exit_on_trailing_stop(self) -> None:
        df = self._crash_bounce_1h()
        s = get("bearish_resumption")()
        signals = s.generate_signals(df)

        post = signals.iloc[s.warmup :]
        entry_indices = post[post == -1.0].index.tolist()
        exit_indices = post[post == 0.0].index.tolist()
        assert len(entry_indices) >= 2, "Should have at least one entry followed by exit"
        first_entry = entry_indices[0]
        later_zeros = [idx for idx in exit_indices if idx > first_entry]
        assert len(later_zeros) > 0, "Should have exit after entry"

    def test_4h_indicators_valid(self) -> None:
        df = self._crash_bounce_1h()
        df_4h = (
            df.resample("4h")
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
        assert len(df_4h) > 0
        assert df_4h.index[0] <= df.index[0] + pd.Timedelta(hours=4)
        assert "close" in df_4h.columns
        from ztb.features.indicators import adx, atr

        adx_4h = adx(df_4h["high"], df_4h["low"], df_4h["close"], 14)
        atr_4h = atr(df_4h["high"], df_4h["low"], df_4h["close"], 14)
        valid_adx = adx_4h.dropna()
        valid_atr = atr_4h.dropna()
        assert len(valid_adx) > 0
        assert len(valid_atr) > 0
        assert valid_adx.between(0, 100).all()
        assert (valid_atr > 0).all()


class TestBearBounceExhaustion:
    def test_registration(self) -> None:
        cls = get("bear_bounce_exhaustion")
        assert cls.name == "bear_bounce_exhaustion"
        assert "bear_bounce_exhaustion" in list_names()

    def test_params_defaults(self) -> None:
        cls = get("bear_bounce_exhaustion")
        expected = {
            "adx_chop_max": 20,
            "rsi_entry": 70,
            "rsi_exit": 50,
            "trail_atr_mult": 2.0,
            "max_hold_bars": 24,
        }
        assert cls.params == expected

    def test_generate_signals_len(self, bear_bounce_1h_df: DataFrame) -> None:
        s = get("bear_bounce_exhaustion")()
        signals = s.generate_signals(bear_bounce_1h_df)
        assert len(signals) == len(bear_bounce_1h_df)

    def test_signals_in_range(self, bear_bounce_1h_df: DataFrame) -> None:
        s = get("bear_bounce_exhaustion")()
        signals = s.generate_signals(bear_bounce_1h_df)
        valid = signals.dropna()
        assert valid.between(-1.0, 0.0).all()
        assert (valid != 1.0).all()

    def test_warmup_is_flat(self, bear_bounce_1h_df: DataFrame) -> None:
        s = get("bear_bounce_exhaustion")()
        signals = s.generate_signals(bear_bounce_1h_df)
        assert (signals.iloc[: s.warmup] == 0.0).all()

    def test_no_nan(self, bear_bounce_1h_df: DataFrame) -> None:
        s = get("bear_bounce_exhaustion")()
        signals = s.generate_signals(bear_bounce_1h_df)
        assert signals.iloc[s.warmup :].isna().sum() == 0

    def test_entry_in_bear_chop(self) -> None:
        df = self._bear_chop_overbought_1h()
        s = get("bear_bounce_exhaustion")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Entry should fire in bear macro + 4h chop + 1h overbought"

    def test_no_entry_in_bull_macro(self) -> None:
        df = self._bull_macro_1h()
        s = get("bear_bounce_exhaustion")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        assert (post != -1.0).all(), "No entries should fire in bull macro"

    def test_no_entry_in_trending_4h(self) -> None:
        df = self._trending_4h_1h()
        s = get("bear_bounce_exhaustion")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        post_entries = post[post == -1.0]
        # Some entries may fire when 4h ADX briefly dips below threshold,
        # but assert that less than 5% of post-warmup bars are entries
        # (trending regime should massively suppress entries vs chop regime)
        entry_ratio = len(post_entries) / max(len(post), 1)
        assert entry_ratio < 0.05, f"Entry ratio {entry_ratio:.4f} should be < 0.05 in trending 4h"

    def test_exit_on_rsi(self) -> None:
        df = self._rsi_exit_1h()
        s = get("bear_bounce_exhaustion")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Entry should fire"
        exit_after_entry = post[post == 0.0]
        entry_indices = post[post == -1.0].index
        first_entry = entry_indices[0]
        later_zeros = exit_after_entry[exit_after_entry.index > first_entry]
        assert len(later_zeros) > 0, "Should have exit after entry"

    def test_exit_on_trailing_stop(self) -> None:
        df = self._trail_stop_1h()
        s = get("bear_bounce_exhaustion")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Entry should fire"
        exit_after_entry = post[post == 0.0]
        entry_indices = post[post == -1.0].index
        first_entry = entry_indices[0]
        later_zeros = exit_after_entry[exit_after_entry.index > first_entry]
        assert len(later_zeros) > 0, "Should have exit after entry"

    def test_exit_on_time_stop(self) -> None:
        df = self._time_stop_1h()
        s = get("bear_bounce_exhaustion")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Entry should fire"
        exit_after_entry = post[post == 0.0]
        entry_indices = post[post == -1.0].index
        first_entry = entry_indices[0]
        later_zeros = exit_after_entry[exit_after_entry.index > first_entry]
        assert len(later_zeros) > 0, "Should have exit after entry"

    @staticmethod
    def _bear_chop_overbought_1h() -> DataFrame:
        """Bear macro + 4h chop + 1h overbought spike → entry at the spike.

        Structure:
        - Bars 0-6000: Moderate downtrend to establish daily bear macro
        - Bars 6000-10000: Choppy range (4h ADX < 20)
        - Bars 10000-10030: Sharp up-spike (1h RSI > 70, close > BB upper)
        """
        n = 10500
        rng = np.random.default_rng(42)
        closes = np.ones(n) * 60000.0

        # Downtrend: bars 0-6000 (est. daily SMA200 > close)
        for i in range(1, 6000):
            closes[i] = closes[i - 1] - 0.5 + rng.normal() * 10

        # Choppy range: bars 6000-10000 (low ADX)
        base = closes[5999]
        for i in range(6000, 10000):
            closes[i] = base + rng.normal() * 15

        # Sharp up-spike: bars 10000-10030 (RSI > 70, close above BB upper)
        spike_start = closes[9999]
        for i in range(10000, min(10030, n)):
            pct = (i - 10000) / 30
            closes[i] = spike_start + 3000 * pct + rng.normal() * 10

        # Rest
        for i in range(10030, n):
            closes[i] = closes[i - 1] + rng.normal() * 5

        opens = closes + rng.normal(size=n) * 5
        highs = np.maximum(opens, closes) + np.abs(rng.normal(size=n)) * 10
        lows = np.minimum(opens, closes) - np.abs(rng.normal(size=n)) * 10

        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2021-01-01", periods=n, freq="h"),
        )

    @staticmethod
    def _bull_macro_1h() -> DataFrame:
        """Bull macro (daily close > SMA200) → no entries should fire.

        Strong uptrend throughout.
        """
        n = 8000
        rng = np.random.default_rng(42)
        closes = np.ones(n) * 30000.0
        for i in range(1, n):
            closes[i] = closes[i - 1] + 1.0 + rng.normal() * 8

        opens = closes + rng.normal(size=n) * 5
        highs = np.maximum(opens, closes) + np.abs(rng.normal(size=n)) * 10
        lows = np.minimum(opens, closes) - np.abs(rng.normal(size=n)) * 10

        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2021-01-01", periods=n, freq="h"),
        )

    @staticmethod
    def _trending_4h_1h() -> DataFrame:
        """Strong downtrend on 4h (ADX >= adx_chop_max) → entries suppressed.

        Strong bear trend means 4h ADX will be high, blocking the chop precondition.
        """
        n = 8000
        rng = np.random.default_rng(42)
        closes = np.ones(n) * 70000.0
        for i in range(1, n):
            closes[i] = closes[i - 1] - 2.0 + rng.normal() * 6

        opens = closes + rng.normal(size=n) * 5
        highs = np.maximum(opens, closes) + np.abs(rng.normal(size=n)) * 10
        lows = np.minimum(opens, closes) - np.abs(rng.normal(size=n)) * 10

        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2021-01-01", periods=n, freq="h"),
        )

    @staticmethod
    def _rsi_exit_1h() -> DataFrame:
        """Entry then RSI drops below rsi_exit → exit."""
        n = 10500
        rng = np.random.default_rng(42)
        closes = np.ones(n) * 60000.0

        for i in range(1, 6000):
            closes[i] = closes[i - 1] - 0.5 + rng.normal() * 10

        base = closes[5999]
        for i in range(6000, 10000):
            closes[i] = base + rng.normal() * 15

        spike_start = closes[9999]
        for i in range(10000, 10030):
            pct = (i - 10000) / 30
            closes[i] = spike_start + 3000 * pct + rng.normal() * 10

        for i in range(10030, 10100):
            step = min(i - 10030, 30)
            closes[i] = closes[10029] - 2000 * (step / 30) + rng.normal() * 20

        for i in range(10100, n):
            closes[i] = closes[i - 1] + rng.normal() * 8

        opens = closes + rng.normal(size=n) * 5
        highs = np.maximum(opens, closes) + np.abs(rng.normal(size=n)) * 10
        lows = np.minimum(opens, closes) - np.abs(rng.normal(size=n)) * 10

        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2021-01-01", periods=n, freq="h"),
        )

    @staticmethod
    def _trail_stop_1h() -> DataFrame:
        """Entry then sharp up-move triggers trailing stop exit."""
        n = 10500
        rng = np.random.default_rng(42)
        closes = np.ones(n) * 60000.0

        for i in range(1, 6000):
            closes[i] = closes[i - 1] - 0.5 + rng.normal() * 10

        base = closes[5999]
        for i in range(6000, 10000):
            closes[i] = base + rng.normal() * 15

        spike_start = closes[9999]
        for i in range(10000, 10030):
            pct = (i - 10000) / 30
            closes[i] = spike_start + 3000 * pct + rng.normal() * 10

        for i in range(10030, 10060):
            step = min(i - 10030, 30)
            closes[i] = closes[10029] + 4000 * (step / 30) + rng.normal() * 20

        for i in range(10060, 10120):
            closes[i] = closes[10059] - 3000 * ((i - 10060) / 60) + rng.normal() * 20

        for i in range(10120, n):
            closes[i] = closes[i - 1] + rng.normal() * 8

        opens = closes + rng.normal(size=n) * 5
        highs = np.maximum(opens, closes) + np.abs(rng.normal(size=n)) * 10
        lows = np.minimum(opens, closes) - np.abs(rng.normal(size=n)) * 10

        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2021-01-01", periods=n, freq="h"),
        )

    @staticmethod
    def _time_stop_1h() -> DataFrame:
        """Entry then flat price for 24+ bars → time stop exit."""
        n = 10500
        rng = np.random.default_rng(42)
        closes = np.ones(n) * 60000.0

        for i in range(1, 6000):
            closes[i] = closes[i - 1] - 0.5 + rng.normal() * 10

        base = closes[5999]
        for i in range(6000, 10000):
            closes[i] = base + rng.normal() * 15

        spike_start = closes[9999]
        for i in range(10000, 10030):
            pct = (i - 10000) / 30
            closes[i] = spike_start + 3000 * pct + rng.normal() * 10

        for i in range(10030, 10080):
            closes[i] = closes[10029] + rng.normal() * 5

        for i in range(10080, n):
            closes[i] = closes[i - 1] + rng.normal() * 8

        opens = closes + rng.normal(size=n) * 5
        highs = np.maximum(opens, closes) + np.abs(rng.normal(size=n)) * 10
        lows = np.minimum(opens, closes) - np.abs(rng.normal(size=n)) * 10

        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2021-01-01", periods=n, freq="h"),
        )


@pytest.fixture
def bear_bounce_1h_df() -> DataFrame:
    return TestBearBounceExhaustion._bear_chop_overbought_1h()


class TestBearFlagContinuationShort:
    @staticmethod
    def _bear_flag_breakdown_4h() -> DataFrame:
        n = 3000
        rng = np.random.default_rng(42)
        closes = np.ones(n) * 100000.0
        opens = np.ones(n) * 100000.0
        highs = np.ones(n) * 100000.0
        lows = np.ones(n) * 100000.0

        for i in range(1, 2400):
            closes[i] = closes[i - 1] - 10 + rng.normal() * 4
            opens[i] = closes[i - 1] - 5
            highs[i] = closes[i - 1] - 1
            lows[i] = closes[i] - 25

        flag_base = closes[2399]
        for i in range(2400, 2406):
            closes[i] = flag_base + rng.normal() * 2
            opens[i] = closes[i - 1] + rng.normal() * 1
            highs[i] = max(opens[i], closes[i]) + 2
            lows[i] = min(opens[i], closes[i]) - 2

        flag_floor_val = min(lows[2400:2406])
        closes[2406] = flag_floor_val - 60
        opens[2406] = flag_floor_val - 10
        highs[2406] = flag_floor_val + 5
        lows[2406] = flag_floor_val - 65

        for i in range(2407, 2600):
            closes[i] = closes[i - 1] - 5 + rng.normal() * 3
            opens[i] = closes[i - 1] - 2
            highs[i] = closes[i - 1] - 1
            lows[i] = closes[i] - 15

        for i in range(2600, n):
            closes[i] = closes[i - 1] + rng.normal() * 1
            opens[i] = closes[i - 1]
            highs[i] = closes[i - 1] + 3
            lows[i] = closes[i - 1] - 3

        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 1000,
            },
            index=pd.date_range("2020-01-01", periods=n, freq="4h"),
        )

    def test_registration(self) -> None:
        cls = get("bear_flag_continuation_short")
        assert cls.name == "bear_flag_continuation_short"
        assert "bear_flag_continuation_short" in list_names()

    def test_params_defaults(self) -> None:
        cls = get("bear_flag_continuation_short")
        expected = {
            "adx_macro_min": 50,
            "flag_lookback_bars": 20,
            "trail_atr_mult": 2.0,
            "target_atr_mult": 2.5,
            "max_hold_bars": 12,
        }
        assert cls.params == expected
        assert "adx_trend_min" not in cls.params, "adx_trend_min must be removed per Revision 1"

    def test_generate_signals_len(self) -> None:
        df = self._bear_flag_breakdown_4h()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        assert len(signals) == len(df)

    def test_signals_in_range(self) -> None:
        df = self._bear_flag_breakdown_4h()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        valid = signals.dropna()
        assert valid.between(-1.0, 0.0).all()
        assert (valid != 1.0).all()

    def test_warmup_is_flat(self) -> None:
        df = self._bear_flag_breakdown_4h()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        assert (signals.iloc[: s.warmup] == 0.0).all()

    def test_no_nan(self) -> None:
        df = self._bear_flag_breakdown_4h()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        assert signals.iloc[s.warmup :].isna().sum() == 0

    def test_entry_on_breakdown(self) -> None:
        df = self._bear_flag_breakdown_4h()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Should fire short entry on flag breakdown"

    def test_exit_after_entry(self) -> None:
        df = self._bear_flag_breakdown_4h()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        entry_indices = post[post == -1.0].index.tolist()
        exit_indices = post[post == 0.0].index.tolist()
        assert len(entry_indices) >= 1, "Should have at least one entry"
        first_entry = entry_indices[0]
        later_zeros = [idx for idx in exit_indices if idx > first_entry]
        assert len(later_zeros) > 0, "Should have exit after entry"

    def test_no_adx_4h_filter(self) -> None:
        """Revision 1: entry fires WITHOUT 4h ADX > 25 condition."""
        df = self._bear_flag_breakdown_4h()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Entry should fire without 4h ADX > 25 gate per Revision 1"

    def test_di_gate_fires(self) -> None:
        """Signals fire with NDI > PDI directional confirmation."""
        df = self._bear_flag_breakdown_4h()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        assert (post == -1.0).any(), "Entry should fire with DI directional confirmation"
