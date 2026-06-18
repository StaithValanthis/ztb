from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame

from ztb.strategies.base import RiskProfile
from ztb.strategies.registry import get, list_names


def _rcl_sample_df(bars: int = 4000) -> DataFrame:
    if bars < 3500:
        bars = 3500
    np.random.seed(42)
    n = bars

    # Phase boundaries:
    bear_end = min(1800, n - 1600)
    base_end = min(bear_end + 800, n - 800)

    close = np.zeros(n)
    # Phase 1: Bear trend (price declines) — builds ADX trending with DI- > DI+
    close[:bear_end] = np.linspace(100, 45, bear_end) + np.random.normal(0, 0.5, bear_end)
    # Phase 2: Base / bottoming — price oscillates, ADX declines from extreme
    base_len = base_end - bear_end
    close[bear_end:base_end] = 45 + np.random.normal(0, 0.8, base_len).clip(-2, 2)
    # Phase 3: Reversal — price rallies above EMA20, DI+ crosses DI-
    rev_len = n - base_end
    noise = np.random.normal(0, 0.6, rev_len).clip(-1.5, 1.5)
    close[base_end:] = np.linspace(45, 70, rev_len) + noise

    # Build high/low
    high = np.zeros(n)
    low = np.zeros(n)
    for i in range(n):
        hi = np.abs(np.random.normal(0, 0.8))
        lo = np.abs(np.random.normal(0, 0.8))
        high[i] = close[i] + max(hi, 0.3)
        low[i] = close[i] - max(lo, 0.3)

    open_ = np.full(n, np.nan)
    open_[0] = close[0]
    for i in range(1, n):
        open_[i] = close[i - 1] + np.random.normal(0, 0.3)

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


# RC-P1
def test_reversal_confirmation_long_registered() -> None:
    cls = get("reversal_confirmation_long")
    assert cls is not None
    assert cls.name == "reversal_confirmation_long"
    names = list_names()
    assert "reversal_confirmation_long" in names


# RC-P2
def test_reversal_confirmation_long_profile() -> None:
    p = get("reversal_confirmation_long")().get_risk_profile()
    assert isinstance(p, RiskProfile)


class TestReversalConfirmationLong:
    # RC-P3
    def test_signal_range(self) -> None:
        cls = get("reversal_confirmation_long")
        strat = cls()
        df = _rcl_sample_df()
        signals = strat.generate_signals(df)
        unique = set(signals.dropna().unique())
        assert unique.issubset({0.0, 1.0}), f"Unexpected values: {unique}"

    # RC-P4
    def test_warmup_flat(self) -> None:
        cls = get("reversal_confirmation_long")
        strat = cls()
        df = _rcl_sample_df()
        signals = strat.generate_signals(df)
        assert (signals.iloc[: strat.warmup] == 0.0).all()

    # RC-P5
    def test_no_nan_after_warmup(self) -> None:
        cls = get("reversal_confirmation_long")
        strat = cls()
        df = _rcl_sample_df()
        signals = strat.generate_signals(df)
        assert signals.iloc[strat.warmup :].isna().sum() == 0

    # RC-P6
    @pytest.mark.parametrize(
        "param,min_val,max_val,default",
        [
            ("adx_macro_min", 20, 30, 25),
            ("adx_macro_max", 45, 60, 50),
            ("trail_atr_mult", 1.5, 3.0, 2.0),
            ("target_atr_mult", 3.0, 8.0, 5.0),
            ("max_hold_bars", 90, 360, 180),
        ],
    )
    def test_parameter_ranges(
        self,
        param: str,
        min_val: float,
        max_val: float,
        default: float,
    ) -> None:
        cls = get("reversal_confirmation_long")

        strat_default = cls()
        assert strat_default.params[param] == default

        df = _rcl_sample_df(500)

        for val in [min_val, max_val, default]:
            params_copy = dict(strat_default.params)
            params_copy[param] = val
            strat = cls()
            strat.params = params_copy
            signals = strat.generate_signals(df)
            assert signals.dtype == float
            assert len(signals) == len(df)
            assert signals.iloc[strat.warmup :].isna().sum() == 0

    # RC-P7
    def test_signal_length_matches_data(self) -> None:
        cls = get("reversal_confirmation_long")
        strat = cls()
        df = _rcl_sample_df(500)
        signals = strat.generate_signals(df)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    # RC-P8
    def test_entry_exit_cycles(self) -> None:
        cls = get("reversal_confirmation_long")
        strat = cls()
        df = _rcl_sample_df(4000)
        signals = strat.generate_signals(df)
        n_signals = len(signals)
        assert n_signals == len(df)

        diffs = signals.diff()
        entries = (diffs > 0).sum()
        exits = (diffs < 0).sum()
        assert entries >= 1, f"Expected at least 1 entry, got {entries}"
        assert exits >= 1, f"Expected at least 1 exit, got {exits}"
        assert entries == exits, f"Entries ({entries}) != Exits ({exits})"
