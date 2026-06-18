from __future__ import annotations

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
    """BF-P1 through BF-P10 per contract-ZTB-3625.md."""

    @staticmethod
    def _synthetic_4h_bear_flag(n: int = 4000) -> DataFrame:
        """Synthetic 4h dataset engineered to produce a bear flag breakdown entry
        when the strategy runs with default params.  Daily macro is structurally
        bearish (close < EMA200, ADX >= 50) after the warmup period."""
        import numpy as np

        rng = np.random.default_rng(42)

        closes = np.empty(n)
        opens = np.empty(n)
        highs = np.empty(n)
        lows = np.empty(n)

        # Phase 1: downtrend for the first ~2800 bars (covers warmup + daily macro)
        closes[0] = 100_000.0
        opens[0] = 100_000.0
        highs[0] = 100_100.0
        lows[0] = 99_900.0

        for i in range(1, 2800):
            closes[i] = closes[i - 1] - 8 + rng.normal() * 4
            opens[i] = closes[i - 1] - 4
            highs[i] = max(opens[i], closes[i]) + 5 + rng.normal() * 3
            lows[i] = min(opens[i], closes[i]) - 5 - rng.normal() * 3

        # Phase 2: flag consolidation (bars 2800-2805)
        flag_base = closes[2799]
        for i in range(2800, 2806):
            noise = rng.normal() * 2
            closes[i] = flag_base + noise
            opens[i] = closes[i - 1] + rng.normal() * 1
            highs[i] = max(opens[i], closes[i]) + 3
            lows[i] = min(opens[i], closes[i]) - 3

        # Phase 3: flag floor breakdown
        flag_floor_val = min(lows[2800:2806])
        closes[2806] = flag_floor_val - 60
        opens[2806] = flag_floor_val - 10
        highs[2806] = flag_floor_val + 10
        lows[2806] = flag_floor_val - 70

        # Phase 4: continuation downtrend
        for i in range(2807, 3100):
            closes[i] = closes[i - 1] - 4 + rng.normal() * 3
            opens[i] = closes[i - 1] - 2
            highs[i] = max(opens[i], closes[i]) + 3 + rng.normal() * 2
            lows[i] = min(opens[i], closes[i]) - 4 - rng.normal() * 2

        # Phase 5: recovery / chop
        for i in range(3100, n):
            closes[i] = closes[i - 1] + rng.normal() * 2
            opens[i] = closes[i - 1]
            highs[i] = max(opens[i], closes[i]) + 5
            lows[i] = min(opens[i], closes[i]) - 5

        return DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 2000,
            },
            index=pd.date_range("2020-01-01", periods=n, freq="4h"),
        )

    # --- BF-P1: Registration ---
    def test_bear_flag_registered(self) -> None:
        cls = get("bear_flag_continuation_short")
        assert cls.name == "bear_flag_continuation_short"
        assert "bear_flag_continuation_short" in list_names()

    # --- BF-P2: RiskProfile ---
    def test_bear_flag_risk_profile(self) -> None:
        s = get("bear_flag_continuation_short")()
        p = s.get_risk_profile()
        assert p.sl_pct == 0.04
        assert p.tp_pct == 0.08
        assert p.leverage == 2.0

    # --- BF-P3: Signal range ---
    def test_bear_flag_signal_range(self) -> None:
        df = self._synthetic_4h_bear_flag()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        valid = signals.dropna()
        assert valid.between(-1.0, 0.0).all()
        assert (valid != 1.0).all()

    # --- BF-P4: Warmup flat ---
    def test_bear_flag_warmup_flat(self) -> None:
        df = self._synthetic_4h_bear_flag()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        assert (signals.iloc[: s.warmup] == 0.0).all()

    # --- BF-P5: No NaN after warmup ---
    def test_bear_flag_no_nan(self) -> None:
        df = self._synthetic_4h_bear_flag()
        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        assert signals.iloc[s.warmup :].isna().sum() == 0

    # --- BF-P6: Trailing stop highest_high order (THE FIX VERIFICATION) ---
    def test_bear_flag_trailing_stop_highest_high_order(self) -> None:
        """Verify the trailing stop does NOT auto-fire unconditionally.

        The fix ensures trail_stop is computed from prior-bar highest_high
        BEFORE the current bar's high can extend it.  After entry, a bar where
        high stays below trail_stop must keep the position active (-1).
        This proves the trailing stop is working as a trailing stop and not as
        an unconditional exit on every bar.
        """
        import numpy as np

        # Need enough bars for daily EMA(200) to have a non-NaN value:
        # warmup=400 + daily_ema200_stabilize ~= 1600+
        n = 3000
        rng = np.random.default_rng(99)
        closes = np.empty(n)
        opens = np.empty(n)
        highs = np.empty(n)
        lows = np.empty(n)

        # Start with moderate price
        closes[0] = 105_000.0
        opens[0] = 105_000.0
        highs[0] = 105_100.0
        lows[0] = 104_900.0

        # Long downtrend for macro bear (~2780 bars to cover warmup + daily EMA200)
        for i in range(1, 2780):
            closes[i] = closes[i - 1] - 8 + rng.normal() * 4
            opens[i] = closes[i - 1] - 4
            highs[i] = max(opens[i], closes[i]) + 3
            lows[i] = min(opens[i], closes[i]) - 6

        # Flag consolidation
        flag_base = closes[2779]
        for i in range(2780, 2786):
            noise = rng.normal() * 2
            closes[i] = flag_base + noise
            opens[i] = closes[i - 1]
            highs[i] = max(opens[i], closes[i]) + 2
            lows[i] = min(opens[i], closes[i]) - 2

        # Breakdown entry
        closes[2786] = flag_base - 60
        opens[2786] = flag_base - 10
        highs[2786] = opens[2786] + 5
        lows[2786] = closes[2786] - 10

        # Continuation lower - position should stay active
        for i in range(2787, 2792):
            closes[i] = closes[i - 1] - 20 + rng.normal() * 3
            opens[i] = closes[i - 1] - 5
            highs[i] = max(opens[i], closes[i]) + 2
            lows[i] = min(opens[i], closes[i]) - 8

        df = DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 2000,
            },
            index=pd.date_range("2020-01-01", periods=n, freq="4h"),
        )

        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]

        entry_idx = post[post == -1.0].index
        assert len(entry_idx) >= 1, "Must have at least one entry"

        first_entry = entry_idx[0]
        entry_pos = df.index.get_loc(first_entry)

        # At least one bar after entry must remain active
        active_after = signals.iloc[entry_pos + 1 : entry_pos + 4]
        assert (active_after == -1.0).any(), (
            "Trailing stop should NOT auto-fire on every bar. "
            "At least one bar after entry must remain active (-1)."
        )

    # --- BF-P7: Max hold bars exit ---
    def test_bear_flag_max_hold_bars_exit(self) -> None:
        df = self._synthetic_4h_bear_flag()

        s = get("bear_flag_continuation_short")()
        s.params["max_hold_bars"] = 1
        sig1 = s.generate_signals(df)

        # All entries must exit within max_hold_bars=1 bar (bars_held >= 1)
        post1 = sig1.iloc[s.warmup :]
        entries1 = post1[post1 == -1.0]
        assert len(entries1) >= 1, "Must have at least one entry"
        for entry_ts in entries1.index:
            ep = df.index.get_loc(entry_ts)
            dur = 0
            for k in range(1, min(10, len(sig1) - ep)):
                if sig1.iloc[ep + k] == 0.0:
                    dur = k
                    break
            assert dur <= 1, f"Entry at bar {ep} held {dur} bars (max_hold_bars=1)"

    # --- BF-P8: Flag floor breach exit ---
    def test_bear_flag_flag_floor_breach_exit(self) -> None:
        """Exit must fire at the first bar where close > flag_floor after entry."""
        import numpy as np

        n = 3000
        rng = np.random.default_rng(42)
        closes = np.empty(n)
        opens = np.empty(n)
        highs = np.empty(n)
        lows = np.empty(n)

        # Phase 1: uptrend (no macro bear) for first ~2600 bars
        closes[0] = 90_000.0
        opens[0] = 90_000.0
        highs[0] = 90_100.0
        lows[0] = 89_900.0

        for i in range(1, 2600):
            closes[i] = closes[i - 1] + 5 + rng.normal() * 3
            opens[i] = closes[i - 1] + 2
            highs[i] = max(opens[i], closes[i]) + 5
            lows[i] = min(opens[i], closes[i]) - 5

        # Phase 2: sharp downtrend to establish macro bear
        for i in range(2600, 2780):
            closes[i] = closes[i - 1] - 12 + rng.normal() * 4
            opens[i] = closes[i - 1] - 5
            highs[i] = max(opens[i], closes[i]) + 3
            lows[i] = min(opens[i], closes[i]) - 8

        # Fixed value arrays to ensure the breakdown works
        flag_base = 100_000.0  # price level near end of downtrend
        closes[2778] = flag_base
        opens[2778] = flag_base + 3
        highs[2778] = flag_base + 5
        lows[2778] = flag_base - 5

        for i in range(2779, 2785):
            closes[i] = flag_base - 2 + rng.normal() * 1
            opens[i] = closes[i - 1]
            highs[i] = max(opens[i], closes[i]) + 2
            lows[i] = min(opens[i], closes[i]) - 2

        closes[2785] = flag_base - 2
        opens[2785] = flag_base - 1
        highs[2785] = flag_base + 1
        lows[2785] = flag_base - 3

        # Breakdown entry
        closes[2786] = flag_base - 40
        opens[2786] = flag_base - 5
        highs[2786] = flag_base
        lows[2786] = flag_base - 45

        # Bar after entry: close above flag floor -> exit
        flag_floor_val = float(flag_base - 5)
        closes[2787] = flag_floor_val + 10
        opens[2787] = flag_floor_val - 3
        highs[2787] = flag_floor_val + 15
        lows[2787] = flag_floor_val - 5

        df = DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 2000,
            },
            index=pd.date_range("2020-01-01", periods=n, freq="4h"),
        )

        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        floor = df["low"].shift(1).rolling(20, min_periods=20).min()
        for i in range(s.warmup, n - 1):
            if (
                signals.iloc[i] == -1.0
                and signals.iloc[i + 1] == 0.0
                and closes[i + 1] > floor.iloc[i + 1]
            ):
                return  # Found floor breach exit
        raise AssertionError("No flag floor breach exit detected")

    # --- BF-P9: No entry without macro bear ---
    def test_bear_flag_no_entry_without_macro_bear(self) -> None:
        import numpy as np

        n = 500
        # Uptrend data: close always above EMA200, ADX low
        close = [110_000.0 + i * 10 for i in range(n)]
        open_p = [110_000.0 + i * 10 for i in range(n)]
        high = [110_000.0 + i * 10 + 50 for i in range(n)]
        low = [110_000.0 + i * 10 - 50 for i in range(n)]

        df = DataFrame(
            {
                "open": open_p,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.ones(n) * 2000,
            },
            index=pd.date_range("2020-01-01", periods=n, freq="4h"),
        )

        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        assert not (post == -1.0).any(), "No entry should fire without macro bear conditions"

    # --- BF-P10: Profit target exit ---
    def test_bear_flag_target_exit(self) -> None:
        import numpy as np

        n = 3000
        rng = np.random.default_rng(99)
        closes = np.empty(n)
        opens = np.empty(n)
        highs = np.empty(n)
        lows = np.empty(n)

        closes[0] = 105_000.0
        opens[0] = 105_000.0
        highs[0] = 105_100.0
        lows[0] = 104_900.0

        for i in range(1, 2780):
            closes[i] = closes[i - 1] - 8 + rng.normal() * 4
            opens[i] = closes[i - 1] - 4
            highs[i] = max(opens[i], closes[i]) + 3
            lows[i] = min(opens[i], closes[i]) - 6

        flag_base = closes[2779]
        for i in range(2780, 2786):
            noise = rng.normal() * 2
            closes[i] = flag_base + noise
            opens[i] = closes[i - 1]
            highs[i] = max(opens[i], closes[i]) + 2
            lows[i] = min(opens[i], closes[i]) - 2

        # Breakdown entry
        closes[2786] = flag_base - 60
        opens[2786] = flag_base - 10
        highs[2786] = opens[2786] + 10
        lows[2786] = closes[2786] - 10

        entry_close = closes[2786]
        # Bar after entry: low far below entry -> profit target hit
        closes[2787] = entry_close - 3000
        opens[2787] = entry_close - 500
        highs[2787] = entry_close + 20
        lows[2787] = entry_close - 3500

        for i in range(2788, n):
            closes[i] = closes[i - 1] + rng.normal() * 2
            opens[i] = closes[i - 1]
            highs[i] = max(opens[i], closes[i]) + 5
            lows[i] = min(opens[i], closes[i]) - 5

        df = DataFrame(
            {
                "open": opens,
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": np.ones(n) * 2000,
            },
            index=pd.date_range("2020-01-01", periods=n, freq="4h"),
        )

        s = get("bear_flag_continuation_short")()
        signals = s.generate_signals(df)
        post = signals.iloc[s.warmup :]
        entry_idx = post[post == -1.0].index
        assert len(entry_idx) >= 1
        first_entry = entry_idx[0]
        entry_pos = df.index.get_loc(first_entry)
        assert signals.iloc[entry_pos + 1] == 0.0, (
            f"Expected profit target exit at bar {entry_pos + 1}, got {signals.iloc[entry_pos + 1]}"
        )
