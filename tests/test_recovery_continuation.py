from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame

from ztb.strategies.base import RiskProfile
from ztb.strategies.registry import get, list_names


def _rc_sample_df(bars: int = 3000) -> DataFrame:
    if bars < 2500:
        bars = 2500
    np.random.seed(42)
    n = bars

    bull_end = min(1000, n // 3)
    crash_end = min(bull_end + 900, n - 700)

    close = np.zeros(n)
    close[:bull_end] = np.linspace(100, 150, bull_end)
    close[bull_end:crash_end] = np.linspace(150, 60, crash_end - bull_end)
    comp_end = min(crash_end + 420, n - 300)
    comp_len = comp_end - crash_end
    close[crash_end:comp_end] = 60 + np.random.normal(0, 0.4, comp_len).clip(-1.5, 1.5)
    close[comp_end] = 68.0
    hold_end = min(comp_end + 50, n - 200)
    hold_len = hold_end - comp_end - 1
    if hold_len > 0:
        close[comp_end + 1 : hold_end] = 67 + np.random.normal(0, 0.4, hold_len).clip(-1, 1)
    remaining = n - hold_end
    if remaining > 0:
        close[hold_end:] = np.linspace(68, 76, remaining) + np.random.normal(
            0, 0.4, remaining
        ).clip(-0.8, 0.8)

    high = np.zeros(n)
    low = np.zeros(n)
    for i in range(n):
        hi_noise = np.abs(np.random.normal(0, 0.8))
        lo_noise = np.abs(np.random.normal(0, 0.8))
        if i == comp_end:
            high[i] = close[i] + 2.0
            low[i] = close[i] - 1.5
        else:
            high[i] = close[i] + max(hi_noise, 0.2)
            low[i] = close[i] - max(lo_noise, 0.2)

    open_ = np.full(n, np.nan)
    open_[0] = close[0]
    for i in range(1, n):
        open_[i] = high[i - 1] + np.random.normal(0, 0.3)

    return DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=pd.date_range("2020-01-01", periods=n, freq="4h"),
    )


def test_recovery_continuation_registered() -> None:
    cls = get("recovery_continuation")
    assert cls is not None
    assert cls.name == "recovery_continuation"
    names = list_names()
    assert "recovery_continuation" in names


def test_recovery_continuation_profile() -> None:
    p = get("recovery_continuation")().get_risk_profile()
    assert isinstance(p, RiskProfile)


class TestRecoveryContinuation:
    def test_signal_range(self) -> None:
        cls = get("recovery_continuation")
        strat = cls()
        df = _rc_sample_df()
        signals = strat.generate_signals(df)
        unique = set(signals.dropna().unique())
        assert unique.issubset({0.0, 1.0}), f"Unexpected values: {unique}"

    def test_warmup_flat(self) -> None:
        cls = get("recovery_continuation")
        strat = cls()
        df = _rc_sample_df()
        signals = strat.generate_signals(df)
        assert (signals.iloc[: strat.warmup] == 0.0).all()

    def test_no_nan_after_warmup(self) -> None:
        cls = get("recovery_continuation")
        strat = cls()
        df = _rc_sample_df()
        signals = strat.generate_signals(df)
        assert signals.iloc[strat.warmup :].isna().sum() == 0

    @pytest.mark.parametrize(
        "param,min_val,max_val,default",
        [
            ("bb_width_compressed_pct", 4.0, 7.0, 5.5),
            ("min_bb_width_pct", 0.5, 2.0, 1.0),
            ("lookback_bars", 10, 40, 20),
            ("min_bar_atr_ratio", 0.3, 0.8, 0.5),
            ("min_gap_hours", 24, 48, 32),
            ("trail_atr_mult", 1.0, 2.5, 1.5),
            ("target_atr_mult", 1.2, 2.5, 1.8),
            ("max_hold_bars", 8, 24, 16),
        ],
    )
    def test_parameter_ranges(
        self,
        param: str,
        min_val: float,
        max_val: float,
        default: float,
    ) -> None:
        cls = get("recovery_continuation")

        strat_default = cls()
        assert strat_default.params[param] == default

        df = _rc_sample_df(500)

        for val in [min_val, max_val, default]:
            params_copy = dict(strat_default.params)
            params_copy[param] = val
            strat = cls()
            strat.params = params_copy
            signals = strat.generate_signals(df)
            assert signals.dtype == float
            assert len(signals) == len(df)
            assert signals.iloc[strat.warmup :].isna().sum() == 0

    def test_signal_length_matches_data(self) -> None:
        cls = get("recovery_continuation")
        strat = cls()
        df = _rc_sample_df(500)
        signals = strat.generate_signals(df)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    def test_entry_exit_cycles(self) -> None:
        cls = get("recovery_continuation")
        strat = cls()
        df = _rc_sample_df(3000)
        signals = strat.generate_signals(df)
        n_signals = len(signals)
        assert n_signals == len(df)

        diffs = signals.diff()
        entries = (diffs > 0).sum()
        exits = (diffs < 0).sum()
        assert entries >= 1, f"Expected at least 1 entry, got {entries}"
        assert exits >= 1, f"Expected at least 1 exit, got {exits}"
        assert entries == exits, f"Entries ({entries}) != Exits ({exits})"
