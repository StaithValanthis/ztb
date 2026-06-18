from __future__ import annotations

import pandas as pd
from pandas import DataFrame, Series

from ztb.features.indicators import adx, atr, di_minus, di_plus, ema
from ztb.strategies.base import RiskProfile, Strategy
from ztb.strategies.registry import register


@register
class BearFlagContinuationShort(Strategy):
    name = "bear_flag_continuation_short"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "240"
    params: dict[str, float | int | str] = {
        "adx_macro_min": 50,
        "flag_lookback_bars": 20,
        "trail_atr_mult": 2.0,
        "target_atr_mult": 2.5,
        "max_hold_bars": 12,
    }
    warmup: int = 400
    risk_profile = RiskProfile(sl_pct=0.04, tp_pct=0.08, leverage=2.0)

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

        daily_adx_val = adx(daily["high"], daily["low"], daily["close"], 14)
        daily_ema200 = ema(daily["close"], 200)

        daily_ctx = DataFrame(index=daily.index)
        daily_ctx["_adx"] = daily_adx_val
        daily_ctx["_ema200"] = daily_ema200
        daily_ctx["_close"] = daily["close"]

        aligned = (
            pd.merge_asof(
                df[[]],
                daily_ctx,
                left_index=True,
                right_index=True,
                direction="backward",
            )
            .bfill()
            .ffill()
        )
        d_adx = aligned["_adx"]
        d_ema200 = aligned["_ema200"]
        d_close = aligned["_close"]

        di_plus_4h = di_plus(df["high"], df["low"], df["close"], 14)
        di_minus_4h = di_minus(df["high"], df["low"], df["close"], 14)
        atr_4h = atr(df["high"], df["low"], df["close"], 14)

        lookback = int(self.params["flag_lookback_bars"])
        flag_floor = df["low"].shift(1).rolling(window=lookback, min_periods=lookback).min()

        signals = Series(0.0, index=df.index)
        active = False
        entry_price = 0.0
        entry_bar = 0
        highest_high = 0.0
        atr_at_entry = 0.0

        for i in range(len(df)):
            if i < self.warmup:
                continue

            macro_bear = d_close.iloc[i] < d_ema200.iloc[i] and d_adx.iloc[i] > float(
                self.params["adx_macro_min"]
            )

            if active:
                highest_high = max(highest_high, df["high"].iloc[i])

                trail_stop = highest_high - float(self.params["trail_atr_mult"]) * atr_4h.iloc[i]
                target = entry_price - float(self.params["target_atr_mult"]) * atr_at_entry
                bars_held = i - entry_bar
                floor_breach = df["close"].iloc[i] > flag_floor.iloc[i]

                if (
                    df["high"].iloc[i] >= trail_stop
                    or df["low"].iloc[i] <= target
                    or bars_held >= int(self.params["max_hold_bars"])
                    or floor_breach
                ):
                    signals.iloc[i] = 0.0
                    active = False
                else:
                    signals.iloc[i] = -1.0
            else:
                if macro_bear:
                    entry_cond = (
                        di_minus_4h.iloc[i] > di_plus_4h.iloc[i]
                        and df["close"].iloc[i] < flag_floor.iloc[i]
                    )
                    if entry_cond:
                        signals.iloc[i] = -1.0
                        active = True
                        entry_price = df["close"].iloc[i]
                        entry_bar = i
                        highest_high = df["high"].iloc[i]
                        atr_at_entry = atr_4h.iloc[i]
                        continue

                signals.iloc[i] = 0.0

        signals.iloc[: self.warmup] = 0.0
        return signals
