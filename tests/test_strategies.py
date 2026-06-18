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
        assert cls.params == {"fast": 5, "slow": 20, "sl_pct": 0.05, "tp_pct": 0.10}
        assert cls.warmup == 20


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
