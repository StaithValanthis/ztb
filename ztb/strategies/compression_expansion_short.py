from __future__ import annotations

import pandas as pd
from pandas import DataFrame, Series

from ztb.features.indicators import adx, atr, bb, bb_width, di_minus, di_plus, ema, sma
from ztb.strategies.base import Strategy
from ztb.strategies.registry import register


@register
class CompressionExpansionShort(Strategy):
    name = "compression_expansion_short"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "60"
    params: dict[str, float | int | str] = {
        "bb_width_max": 2.0,
        "adx_min": 25,
        "vol_expansion_mult": 1.5,
        "trail_atr_mult": 2.0,
        "target_atr_mult": 2.5,
        "max_hold_bars": 48,
    }
    warmup: int = 400

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
        daily_ctx = DataFrame(index=daily.index)
        daily_ctx["_ema200"] = daily_ema200
        daily_ctx["_close"] = daily["close"]

        aligned_daily = (
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
        d_ema200 = aligned_daily["_ema200"]
        d_close = aligned_daily["_close"]

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
        di_minus_4h = di_minus(df_4h["high"], df_4h["low"], df_4h["close"], 14)
        di_plus_4h = di_plus(df_4h["high"], df_4h["low"], df_4h["close"], 14)

        ctx_4h = DataFrame(index=df_4h.index)
        ctx_4h["_di_minus"] = di_minus_4h
        ctx_4h["_di_plus"] = di_plus_4h

        aligned_4h = (
            pd.merge_asof(
                df[[]],
                ctx_4h,
                left_index=True,
                right_index=True,
                direction="backward",
            )
            .bfill()
            .ffill()
        )
        d4_di_minus = aligned_4h["_di_minus"]
        d4_di_plus = aligned_4h["_di_plus"]

        bb_u, bb_m, bb_l = bb(df["close"], 20, 2)
        bb_w = bb_width(df["close"], 20, 2)
        adx_1h = adx(df["high"], df["low"], df["close"], 14)
        atr_1h = atr(df["high"], df["low"], df["close"], 14)
        vol_sma20 = sma(df["volume"], 20)

        signals = Series(0.0, index=df.index)
        active = False
        entry_price = 0.0
        entry_bar = 0
        highest_high = 0.0
        atr_at_entry = 0.0

        for i in range(len(df)):
            if i < self.warmup:
                continue

            pre_bear = d_close.iloc[i] < d_ema200.iloc[i]
            pre_compress = bb_w.iloc[i] < float(self.params["bb_width_max"])
            pre_trend = adx_1h.iloc[i] > float(self.params["adx_min"])
            precondition = bool(pre_bear) and bool(pre_compress) and bool(pre_trend)

            if active:
                trail_stop = highest_high - float(self.params["trail_atr_mult"]) * atr_1h.iloc[i]
                profit_target = entry_price - float(self.params["target_atr_mult"]) * atr_at_entry
                bars_held = i - entry_bar
                breakdown_failed = df["close"].iloc[i] > bb_l.iloc[i]

                if (
                    df["high"].iloc[i] >= trail_stop
                    or df["low"].iloc[i] <= profit_target
                    or bars_held >= int(self.params["max_hold_bars"])
                    or breakdown_failed
                ):
                    signals.iloc[i] = 0.0
                    active = False
                else:
                    signals.iloc[i] = -1.0

                highest_high = max(highest_high, df["high"].iloc[i])
            else:
                if precondition:
                    entry_cond = (
                        df["close"].iloc[i] < bb_l.iloc[i]
                        and d4_di_minus.iloc[i] > d4_di_plus.iloc[i]
                        and df["volume"].iloc[i]
                        > float(self.params["vol_expansion_mult"]) * vol_sma20.iloc[i]
                    )
                    if entry_cond:
                        signals.iloc[i] = -1.0
                        active = True
                        entry_price = df["close"].iloc[i]
                        entry_bar = i
                        highest_high = df["high"].iloc[i]
                        atr_at_entry = atr_1h.iloc[i]
                        continue

                signals.iloc[i] = 0.0

        signals.iloc[: self.warmup] = 0.0
        return signals
