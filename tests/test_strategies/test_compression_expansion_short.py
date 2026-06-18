from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame, Series

from ztb.strategies.registry import get, list_names

RNG_SEED = 42


def _build_df(n: int = 8000, entry_bar: int = 4917) -> tuple[DataFrame, int]:
    rng = np.random.default_rng(RNG_SEED)
    closes = np.ones(n) * 60000.0
    for i in range(1, 3000):
        closes[i] = closes[i - 1] - 5 + rng.normal() * 20
    for i in range(3000, 4800):
        closes[i] = closes[i - 1] - 20 + rng.normal() * 30
    for i in range(4800, entry_bar):
        closes[i] = closes[i - 1] - 2 + rng.normal() * 8
    closes[entry_bar] = closes[entry_bar - 1] - 50
    for i in range(entry_bar + 1, n):
        closes[i] = closes[i - 1] - rng.normal() * 4

    opens = closes + rng.normal(size=n) * 3
    highs = np.maximum(opens, closes) + np.abs(rng.normal(size=n)) * 6
    lows = np.minimum(opens, closes) - np.abs(rng.normal(size=n)) * 6
    volume = np.ones(n) * 1000.0
    volume[entry_bar] = 5000.0

    df = DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume},
        index=pd.date_range("2020-01-01", periods=n, freq="h"),
    )
    return df, entry_bar


def _signals(df: DataFrame, params: dict | None = None) -> Series:
    s = get("compression_expansion_short")(**(params or {}))
    return s.generate_signals(df)


class TestCompressionExpansionShort:
    def test_registration(self) -> None:
        cls = get("compression_expansion_short")
        assert cls.name == "compression_expansion_short"
        assert "compression_expansion_short" in list_names()

    def test_params_defaults(self) -> None:
        cls = get("compression_expansion_short")
        expected = {
            "bb_width_max": 2.0,
            "adx_min": 25,
            "vol_expansion_mult": 1.5,
            "trail_atr_mult": 2.0,
            "target_atr_mult": 2.5,
            "max_hold_bars": 48,
        }
        assert cls.params == expected

    def test_generate_signals_len(self) -> None:
        df, _ = _build_df()
        signals = _signals(df)
        assert len(signals) == len(df)

    def test_signals_in_range(self) -> None:
        df, _ = _build_df()
        signals = _signals(df)
        valid = signals.dropna()
        assert valid.between(-1.0, 0.0).all()
        assert (valid != 1.0).all()

    def test_warmup_is_flat(self) -> None:
        df, _ = _build_df()
        s = get("compression_expansion_short")()
        signals = s.generate_signals(df)
        assert (signals.iloc[: s.warmup] == 0.0).all()

    def test_no_nan(self) -> None:
        df, _ = _build_df()
        s = get("compression_expansion_short")()
        signals = s.generate_signals(df)
        assert signals.iloc[s.warmup :].isna().sum() == 0

    def test_precondition_fires(self) -> None:
        df, _ = _build_df()
        signals = _signals(df)
        post = signals.iloc[400:]
        assert (post == -1.0).any(), "Precondition + entry should produce -1 signal"

    def test_entry_short_on_bb_breakdown(self) -> None:
        df, entry_bar = _build_df()
        signals = _signals(df)
        post = signals.iloc[400:]
        neg = post[post == -1.0]
        assert len(neg) > 0, "Entry should fire -1 on BB breakdown"
        first_entry = df.index.get_loc(neg.index[0])
        assert first_entry == entry_bar, f"Entry should fire at {entry_bar}, got {first_entry}"

    def test_no_long_entries(self) -> None:
        df, _ = _build_df()
        signals = _signals(df)
        assert (signals != 1.0).all(), "No +1.0 signals should ever fire"

    def test_volume_expansion(self) -> None:
        df, entry_bar = _build_df()
        signals = _signals(df)
        post = signals.iloc[400:]
        entry_idx = post[post == -1.0].index
        assert len(entry_idx) > 0
        first_entry = entry_idx[0]
        df_entry = df.loc[first_entry]
        vol_sma20 = df["volume"].rolling(20).mean().loc[first_entry]
        assert df_entry["volume"] > 1.5 * vol_sma20

    def test_exit_trailing_stop(self) -> None:
        df, entry_bar = _build_df()
        entry_price = df["close"].iloc[entry_bar]
        n = len(df)
        rng = np.random.default_rng(99)
        idx = entry_bar + 1
        rally_bars = 15
        for i in range(rally_bars):
            if idx + i < n:
                pct = (i + 1) / rally_bars
                df.loc[df.index[idx + i], "close"] = entry_price + 120.0 * pct + rng.normal() * 3
        for i in range(rally_bars, 30):
            if idx + i < n:
                prev_c = df.loc[df.index[idx + i - 1], "close"]
                df.loc[df.index[idx + i], "close"] = prev_c + rng.normal() * 10

        signals = _signals(df)
        post = signals.iloc[400:]
        neg = post[post == -1.0]
        assert len(neg) > 0, "Entry should fire"
        entry_idx = neg.index[0]
        later_zeros = post[post == 0.0].index
        exits_after_entry = [e for e in later_zeros if e > entry_idx]
        assert len(exits_after_entry) > 0, "Exit should fire after entry"

    def test_exit_profit_target(self) -> None:
        df, entry_bar = _build_df()
        n = len(df)
        rng = np.random.default_rng(99)
        idx = entry_bar + 1
        entry_price = df["close"].iloc[entry_bar]
        for i in range(10):
            if idx + i < n:
                pct = (i + 1) / 10
                new_close = entry_price - 60.0 * pct + rng.normal() * 2
                df.loc[df.index[idx + i], "close"] = new_close

        signals = _signals(df)
        post = signals.iloc[400:]
        neg = post[post == -1.0]
        assert len(neg) > 0, "Entry should fire"
        entry_idx = neg.index[0]
        later_zeros = post[post == 0.0].index
        exits_after_entry = [e for e in later_zeros if e > entry_idx]
        assert len(exits_after_entry) > 0, "Profit target exit should fire"

    def test_exit_time_stop(self) -> None:
        df, entry_bar = _build_df()
        n = len(df)
        for i in range(entry_bar + 1, min(entry_bar + 10, n)):
            df.loc[df.index[i], "close"] = 6945.0
            df.loc[df.index[i], "open"] = 6945.0
            df.loc[df.index[i], "high"] = 6946.0
            df.loc[df.index[i], "low"] = 6944.0

        s = get("compression_expansion_short")()
        s.params = dict(s.params)
        s.params["max_hold_bars"] = 3
        signals = s.generate_signals(df)
        post = signals.iloc[400:]
        neg = post[post == -1.0]
        assert len(neg) > 0, "Entry should fire"
        entry_idx = df.index.get_loc(neg.index[0])
        post_from_entry = signals.iloc[entry_idx:]
        streak = 0
        for v in post_from_entry:
            if v == -1.0:
                streak += 1
            else:
                break
        assert streak == 3, f"Time stop should fire at max_hold_bars=3, got streak={streak}"

    def test_exit_breakdown_failed(self) -> None:
        df, entry_bar = _build_df()
        entry_price = df["close"].iloc[entry_bar]
        n = len(df)
        rng = np.random.default_rng(99)
        idx = entry_bar + 1
        for i in range(10):
            if idx + i < n:
                df.loc[df.index[idx + i], "close"] = entry_price - 15.0 + rng.normal() * 2
        for i in range(10, 22):
            if idx + i < n:
                c = entry_price + 120.0 + (i - 10) * 5.0 + rng.normal() * 5
                df.loc[df.index[idx + i], "close"] = c

        signals = _signals(df)
        post = signals.iloc[400:]
        neg = post[post == -1.0]
        assert len(neg) > 0, "Entry should fire"
        entry_idx = neg.index[0]
        later_zeros = post[post == 0.0].index
        exits_after_entry = [e for e in later_zeros if e > entry_idx]
        assert len(exits_after_entry) > 0, "Breakdown failed exit should fire"
