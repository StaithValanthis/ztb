from __future__ import annotations

import pandas as pd

from ztb.features.indicators import atr, bb, bb_width, ema
from ztb.strategies.base import RiskProfile, Strategy
from ztb.strategies.registry import register


@register
class RecoveryContinuation(Strategy):
    name = "recovery_continuation"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "4h"
    params: dict[str, float | int | str] = {
        "bb_width_compressed_pct": 5.5,
        "min_bb_width_pct": 1.0,
        "lookback_bars": 20,
        "min_bar_atr_ratio": 0.5,
        "min_gap_hours": 32,
        "trail_atr_mult": 1.5,
        "target_atr_mult": 1.8,
        "max_hold_bars": 16,
    }
    warmup: int = 350
    risk_profile = RiskProfile()

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        high = df["high"]
        low = df["low"]

        daily_close = close.resample("1D").last().shift(1)
        daily_ema200 = ema(daily_close, 200)
        daily_ema50 = ema(daily_close, 50)

        daily_ema200_4h = daily_ema200.reindex(close.index, method="ffill")
        daily_ema50_4h = daily_ema50.reindex(close.index, method="ffill")

        bbw = bb_width(close, 20, 2.0)
        _, _, bb_lower = bb(close, 20, 2.0)
        atr14 = atr(high, low, close, 14)

        bear_macro = (close < daily_ema200_4h) & (close < daily_ema50_4h)
        compressed = bbw < self.params["bb_width_compressed_pct"]
        not_dead = bbw >= self.params["min_bb_width_pct"]
        precondition = bear_macro & compressed & not_dead

        lookback = int(self.params["lookback_bars"])
        highest_high = (
            high.shift(1).rolling(window=lookback, min_periods=lookback).max()
        )

        bar_range = high - low
        min_atr_ratio = self.params["min_bar_atr_ratio"]
        strong_bar = bar_range / atr14 > min_atr_ratio

        entry_setup = (
            precondition.shift(1) & (close > highest_high) & strong_bar
        ).fillna(False)

        signals = pd.Series(0.0, index=df.index)
        in_position = False
        entry_price = 0.0
        entry_idx = 0
        lowest_since_entry = float("inf")
        min_gap_bars = int(self.params["min_gap_hours"]) // 4
        last_exit_idx = -min_gap_bars

        for i in range(len(df)):
            if in_position:
                cur_low = low.iloc[i]
                cur_high = high.iloc[i]
                cur_close = close.iloc[i]
                cur_atr = atr14.iloc[i]

                lowest_since_entry = min(lowest_since_entry, cur_low)

                trail_stop = (
                    lowest_since_entry - self.params["trail_atr_mult"] * cur_atr
                )

                profit_target = (
                    entry_price + self.params["target_atr_mult"] * cur_atr
                )

                bars_held = i - entry_idx
                max_bars = int(self.params["max_hold_bars"])

                bb_lower_val = bb_lower.iloc[i]

                exit_signal = (
                    (pd.notna(cur_atr) and cur_low <= trail_stop)
                    or (pd.notna(cur_atr) and cur_high >= profit_target)
                    or bars_held >= max_bars
                    or (pd.notna(bb_lower_val) and cur_close < bb_lower_val)
                )

                if exit_signal:
                    in_position = False
                    last_exit_idx = i
                    signals.iloc[i] = 0.0
                else:
                    signals.iloc[i] = 1.0
            else:
                if entry_setup.iloc[i] and (
                    i - last_exit_idx >= min_gap_bars
                ):
                    in_position = True
                    entry_price = close.iloc[i]
                    entry_idx = i
                    lowest_since_entry = low.iloc[i]
                    signals.iloc[i] = 1.0
                else:
                    signals.iloc[i] = 0.0

        signals[: self.warmup] = 0.0
        return signals
