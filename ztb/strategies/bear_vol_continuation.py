from __future__ import annotations

import pandas as pd
from pandas import DataFrame, Series

from ztb.features.indicators import atr, bb, bb_width, ema
from ztb.strategies.base import Strategy
from ztb.strategies.registry import register


@register
class BearVolContinuation(Strategy):
    name = "bear_vol_continuation"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "240"
    params: dict[str, float | int | str] = {
        "bb_width_compressed_pct": 5.5,
        "min_bb_width_pct": 1.0,
        "min_bar_atr_ratio": 1.0,
        "trail_atr_mult": 1.5,
        "target_atr_mult": 1.5,
        "max_hold_bars": 12,
    }
    warmup: int = 300

    def generate_signals(self, df: DataFrame) -> Series:
        daily = (
            df.resample("D")
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

        daily_ema200 = ema(daily["close"], 200)
        daily_ema50 = ema(daily["close"], 50)

        daily_idx = DataFrame(index=daily.index)
        daily_idx["_close"] = daily["close"].shift(1)
        daily_idx["_ema200"] = daily_ema200.shift(1)
        daily_idx["_ema50"] = daily_ema50.shift(1)
        daily_idx = daily_idx.dropna()

        daily_aligned = pd.merge_asof(
            df[[]],
            daily_idx,
            left_index=True,
            right_index=True,
            direction="backward",
        )
        d_close = daily_aligned["_close"]
        d_ema200 = daily_aligned["_ema200"]
        d_ema50 = daily_aligned["_ema50"]

        bb_u, _, _ = bb(df["close"], 20, 2)
        bb_w = bb_width(df["close"], 20, 2)
        atr_14 = atr(df["high"], df["low"], df["close"], 14)
        bar_range = df["high"] - df["low"]

        signals = pd.Series(0.0, index=df.index)
        active = False
        entry_price = 0.0
        highest_high_since_entry = 0.0
        bars_since_entry = 0
        entry_atr = 0.0

        for i in range(len(df)):
            if i < self.warmup:
                continue

            atr_i = atr_14.iloc[i]
            if pd.isna(atr_i) or atr_i <= 0:
                signals.iloc[i] = 0.0
                active = False
                continue

            if active:
                bars_since_entry += 1
                highest_high_since_entry = max(highest_high_since_entry, df["high"].iloc[i])

                stop_level = highest_high_since_entry - float(self.params["trail_atr_mult"]) * atr_i
                exit_trail = df["close"].iloc[i] <= stop_level

                target_level = entry_price - float(self.params["target_atr_mult"]) * entry_atr
                exit_target = df["close"].iloc[i] <= target_level

                exit_time = bars_since_entry >= int(self.params["max_hold_bars"])

                exit_bb = df["close"].iloc[i] > bb_u.iloc[i]

                if exit_trail or exit_target or exit_time or exit_bb:
                    signals.iloc[i] = 0.0
                    active = False
                else:
                    signals.iloc[i] = -1.0
            else:
                bear_macro = d_close.iloc[i] < d_ema200.iloc[i]
                bb_compressed = bb_w.iloc[i] < float(self.params["bb_width_compressed_pct"])
                bb_min = bb_w.iloc[i] >= float(self.params["min_bb_width_pct"])
                precondition = bool(bear_macro and bb_compressed and bb_min)

                if precondition:
                    range_ratio = bar_range.iloc[i] / atr_i
                    strong_move = range_ratio > float(self.params["min_bar_atr_ratio"])
                    red_candle = df["close"].iloc[i] < df["open"].iloc[i]
                    bear_confirm = d_close.iloc[i] < d_ema50.iloc[i]

                    if strong_move and red_candle and bear_confirm:
                        signals.iloc[i] = -1.0
                        active = True
                        entry_price = df["close"].iloc[i]
                        highest_high_since_entry = df["high"].iloc[i]
                        bars_since_entry = 0
                        entry_atr = atr_i
                        continue

                signals.iloc[i] = 0.0

        signals.iloc[: self.warmup] = 0.0
        return signals
