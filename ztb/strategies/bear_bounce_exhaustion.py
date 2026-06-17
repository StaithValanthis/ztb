from __future__ import annotations

import pandas as pd
from pandas import DataFrame, Series

from ztb.features.indicators import adx, atr, bb, rsi, sma
from ztb.strategies.base import Strategy
from ztb.strategies.registry import register


@register
class BearBounceExhaustion(Strategy):
    name = "bear_bounce_exhaustion"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "60"
    params: dict[str, float | int | str] = {
        "adx_chop_max": 20,
        "rsi_entry": 70,
        "rsi_exit": 50,
        "trail_atr_mult": 2.0,
        "max_hold_bars": 24,
    }
    warmup: int = 400

    def generate_signals(self, df: DataFrame) -> Series:
        # --- 1h indicators ---
        bb_u, bb_m, bb_l = bb(df["close"], 20, 2)
        rsi_1h = rsi(df["close"], 14)
        atr_1h = atr(df["high"], df["low"], df["close"], 14)

        # --- Daily macro context (SMA200) ---
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
        daily_sma200 = sma(daily["close"], 200)

        daily_idx = DataFrame(index=daily.index)
        daily_idx["_sma200"] = daily_sma200
        daily_idx["_close"] = daily["close"]

        daily_aligned = pd.merge_asof(
            df[[]],
            daily_idx,
            left_index=True,
            right_index=True,
            direction="backward",
        ).ffill()
        d_sma200 = daily_aligned["_sma200"]
        d_close = daily_aligned["_close"]

        # --- 4h context (ADX) ---
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
        adx_4h_val = adx(df_4h["high"], df_4h["low"], df_4h["close"], 14)

        df_4h_idx = DataFrame(index=df_4h.index)
        df_4h_idx["_adx"] = adx_4h_val

        four_h_aligned = pd.merge_asof(
            df[[]],
            df_4h_idx,
            left_index=True,
            right_index=True,
            direction="backward",
        )
        d4_adx = four_h_aligned["_adx"]

        # --- Signal loop ---
        signals = Series(0.0, index=df.index)
        active = False
        entry_bar = 0
        highest_high_since_entry = 0.0

        adx_chop_max = float(self.params["adx_chop_max"])
        rsi_entry_val = float(self.params["rsi_entry"])
        rsi_exit_val = float(self.params["rsi_exit"])
        trail_mult = float(self.params["trail_atr_mult"])
        max_hold = int(self.params["max_hold_bars"])

        for i in range(len(df)):
            if i < self.warmup:
                continue

            if active:
                bars_since_entry = i - entry_bar
                trail_stop = highest_high_since_entry - trail_mult * atr_1h.iloc[i]

                exit_rsi = rsi_1h.iloc[i] < rsi_exit_val
                exit_trail = df["low"].iloc[i] <= trail_stop
                exit_time = bars_since_entry >= max_hold

                if exit_rsi or exit_trail or exit_time:
                    signals.iloc[i] = 0.0
                    active = False
                else:
                    signals.iloc[i] = -1.0
                    highest_high_since_entry = max(highest_high_since_entry, df["high"].iloc[i])
            else:
                bear_macro = d_close.iloc[i] < d_sma200.iloc[i]
                four_h_chop = d4_adx.iloc[i] < adx_chop_max

                if not bear_macro or not four_h_chop:
                    signals.iloc[i] = 0.0
                    continue

                overbought_bb = df["close"].iloc[i] > bb_u.iloc[i]
                overbought_rsi = rsi_1h.iloc[i] > rsi_entry_val

                if overbought_bb and overbought_rsi:
                    signals.iloc[i] = -1.0
                    active = True
                    entry_bar = i
                    highest_high_since_entry = df["high"].iloc[i]
                else:
                    signals.iloc[i] = 0.0

        signals.iloc[: self.warmup] = 0.0
        return signals
