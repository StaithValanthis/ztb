from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame

from ztb.strategies.base import RiskProfile
from ztb.strategies.registry import get, list_names


def _sample_df(bars: int = 250) -> DataFrame:
    if bars < 250:
        bars = 250
    np.random.seed(42)
    n = bars

    closes = np.zeros(n)
    closes[:100] = np.linspace(100, 150, 100)
    closes[100:] = np.linspace(150, 80, n - 100)

    volume = np.ones(n) * 1000
    volume[175] = 5000
    volume[176] = 6000
    volume[177] = 400
    volume[178] = 300
    volume[179] = 350

    opens = closes + np.random.normal(0, 2, n)
    highs = np.maximum(opens, closes) + np.abs(np.random.normal(0, 3, n))
    lows = np.minimum(opens, closes) - np.abs(np.random.normal(0, 3, n))
    highs[175] = max(highs[175], 142.0)
    highs[176] = max(highs[176], 140.0)

    return DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volume,
        },
        index=pd.date_range("2021-01-01", periods=n, freq="4h"),
    )


def _bear_rejection_df() -> DataFrame:
    n = 400
    rng = np.random.default_rng(42)

    closes = 50000.0 - np.arange(n) * 50.0

    closes[252] = 37900
    closes[253] = 38200
    closes[254] = 38100
    closes[255] = 37800

    volume = np.ones(n) * 1000
    volume[253] = 12000
    volume[255] = 300

    opens = closes + rng.normal(0, 20, n)
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, 40, n))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, 40, n))
    highs[253] = max(highs[253], 38500)

    return DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volume,
        },
        index=pd.date_range("2021-01-01", periods=n, freq="4h"),
    )


def _bull_macro_df() -> DataFrame:
    n = 400
    rng = np.random.default_rng(43)

    closes = 30000.0 + np.arange(n) * 50.0

    opens = closes + rng.normal(0, 20, n)
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, 40, n))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, 40, n))
    volume = np.ones(n) * 1000

    return DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volume,
        },
        index=pd.date_range("2021-01-01", periods=n, freq="4h"),
    )


def _entry_exit_cycles_df() -> DataFrame:
    n = 600
    rng = np.random.default_rng(44)

    closes = np.zeros(n)
    closes[:100] = np.linspace(50000, 55000, 100)
    closes[100:200] = np.linspace(55000, 60000, 100)
    closes[200:280] = np.linspace(60000, 30000, 80)
    closes[280:300] = np.linspace(30000, 32000, 20)
    closes[300:305] = np.linspace(32000, 28000, 5)
    closes[305:320] = np.linspace(28000, 26000, 15)
    closes[320:330] = np.linspace(26000, 27000, 10)
    closes[330:335] = np.linspace(27000, 24000, 5)
    closes[335:340] = np.linspace(24000, 23500, 5)
    closes[340:350] = np.linspace(23500, 24500, 10)
    closes[350:360] = np.linspace(24500, 22000, 10)
    closes[360:n] = 22000 - rng.exponential(1, n - 360) * 500

    volume = np.ones(n) * 1000
    volume[303] = 8000
    volume[304] = 7000
    volume[305] = 400
    volume[333] = 9000
    volume[334] = 6000
    volume[335] = 300

    opens = closes + rng.normal(0, 50, n)
    highs = np.maximum(opens, closes) + np.abs(rng.normal(0, 100, n))
    lows = np.minimum(opens, closes) - np.abs(rng.normal(0, 100, n))
    highs[303] = max(highs[303], 31500)
    highs[333] = max(highs[333], 26500)

    return DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volume,
        },
        index=pd.date_range("2021-01-01", periods=n, freq="4h"),
    )


# SR-P1
def test_sma20_rejection_short_registered() -> None:
    cls = get("sma20_rejection_short")
    assert cls is not None
    assert cls.name == "sma20_rejection_short"
    names = list_names()
    assert "sma20_rejection_short" in names


# SR-P2
def test_sma20_rejection_short_profile() -> None:
    p = get("sma20_rejection_short")().get_risk_profile()
    assert isinstance(p, RiskProfile)


# SR-P3
class TestSMA20RejectionShort:
    def test_signal_range(self) -> None:
        cls = get("sma20_rejection_short")
        strat = cls()
        df = _sample_df()
        signals = strat.generate_signals(df)
        unique = set(signals.dropna().unique())
        assert unique.issubset({0.0, -1.0}), f"Unexpected values: {unique}"

    # SR-P4
    def test_warmup_flat(self) -> None:
        cls = get("sma20_rejection_short")
        strat = cls()
        df = _sample_df()
        signals = strat.generate_signals(df)
        assert (signals.iloc[: strat.warmup] == 0.0).all()

    # SR-P5
    def test_no_nan_after_warmup(self) -> None:
        cls = get("sma20_rejection_short")
        strat = cls()
        df = _sample_df()
        signals = strat.generate_signals(df)
        assert signals.iloc[strat.warmup :].isna().sum() == 0

    # SR-P6
    @pytest.mark.parametrize(
        "param,min_val,max_val,default",
        [
            ("volume_spike_mult", 2.0, 5.0, 3.0),
            ("volume_spike_lookback", 3, 10, 5),
            ("volume_collapse_ratio", 0.3, 0.7, 0.5),
            ("trail_atr_mult", 1.5, 3.0, 2.0),
            ("max_hold_bars", 5, 20, 10),
        ],
    )
    def test_parameter_ranges(
        self,
        param: str,
        min_val: float,
        max_val: float,
        default: float,
    ) -> None:
        cls = get("sma20_rejection_short")

        strat_default = cls()
        assert strat_default.params[param] == default

        df = _sample_df(500)

        for val in [min_val, max_val, default]:
            params_copy = dict(strat_default.params)
            params_copy[param] = val
            strat = cls()
            strat.params = params_copy
            signals = strat.generate_signals(df)
            assert signals.dtype == float
            assert len(signals) == len(df)
            assert signals.iloc[strat.warmup :].isna().sum() == 0

    # SR-P7
    def test_signal_length_matches_data(self) -> None:
        cls = get("sma20_rejection_short")
        strat = cls()
        df = _sample_df(500)
        signals = strat.generate_signals(df)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    # SR-P8
    def test_entry_exit_cycles(self) -> None:
        cls = get("sma20_rejection_short")
        strat = cls()
        df = _entry_exit_cycles_df()
        signals = strat.generate_signals(df)
        n_signals = len(signals)
        assert n_signals == len(df)

        diffs = signals.diff()
        entries = (diffs < 0).sum()
        exits = (diffs > 0).sum()
        assert entries >= 1, f"Expected at least 1 entry, got {entries}"
        assert exits >= 1, f"Expected at least 1 exit, got {exits}"
        assert entries == exits, f"Entries ({entries}) != Exits ({exits})"

    def test_bear_macro_entry(self) -> None:
        cls = get("sma20_rejection_short")
        strat = cls()
        df = _bear_rejection_df()
        signals = strat.generate_signals(df)
        post = signals.iloc[strat.warmup :]
        assert (post == -1.0).any(), "Bear macro entry should produce -1 signals"
        assert post.dropna().between(-1.0, 0.0).all()

    def test_no_entry_in_bull_macro(self) -> None:
        cls = get("sma20_rejection_short")
        strat = cls()
        df = _bull_macro_df()
        signals = strat.generate_signals(df)
        post = signals.iloc[strat.warmup :]
        assert (post == 0.0).all(), "Bull macro should produce no entries"
