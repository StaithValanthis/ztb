from __future__ import annotations

import pandas as pd

from ztb.features.indicators import adx, atr, di_minus, di_plus, ema
from ztb.strategies.base import RiskProfile, Strategy
from ztb.strategies.registry import register


@register
class ReversalConfirmationLong(Strategy):
    name = "reversal_confirmation_long"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "4h"
    params: dict[str, float | int | str] = {
        "adx_macro_min": 25,
        "adx_macro_max": 50,
        "trail_atr_mult": 2.0,
        "target_atr_mult": 5.0,
        "max_hold_bars": 180,
    }
    warmup: int = 400
    risk_profile = RiskProfile()

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        high = df["high"]
        low = df["low"]

        # Daily macro from 4h resample (fully-closed daily candles only)
        daily_high = high.resample("1D").max()
        daily_low = low.resample("1D").min()
        daily_close = close.resample("1D").last()

        # Shift by 1 day so every value is from a completed daily bar
        daily_high_s = daily_high.shift(1)
        daily_low_s = daily_low.shift(1)
        daily_close_s = daily_close.shift(1)

        # Daily indicators
        daily_adx_val = adx(daily_high_s, daily_low_s, daily_close_s, 14)
        daily_di_plus_val = di_plus(daily_high_s, daily_low_s, daily_close_s, 14)
        daily_di_minus_val = di_minus(daily_high_s, daily_low_s, daily_close_s, 14)
        daily_ema20_val = ema(daily_close_s, 20)

        # Reindex daily to 4h via forward-fill
        daily_adx_4h = daily_adx_val.reindex(close.index, method="ffill")
        daily_di_plus_4h = daily_di_plus_val.reindex(close.index, method="ffill")
        daily_di_minus_4h = daily_di_minus_val.reindex(close.index, method="ffill")
        daily_ema20_4h = daily_ema20_val.reindex(close.index, method="ffill")

        # 4h ATR for volatility-based stops
        atr14 = atr(high, low, close, 14)

        # Precondition: maturing bear trend (ADX trending but not climax)
        pre = (
            (daily_adx_4h > self.params["adx_macro_min"])
            & (daily_adx_4h < self.params["adx_macro_max"])
        ).fillna(False)

        # Entry conditions
        entry = pre & (daily_di_plus_4h > daily_di_minus_4h) & (close > daily_ema20_4h)

        # Iterative signal construction with position management
        signals = pd.Series(0.0, index=df.index)
        in_position = False
        entry_price = 0.0
        entry_idx = 0
        lowest_since_entry = float("inf")

        for i in range(len(df)):
            if in_position:
                cur_low = low.iloc[i]
                cur_high = high.iloc[i]
                cur_atr = atr14.iloc[i]

                lowest_since_entry = min(lowest_since_entry, cur_low)

                trail_stop = lowest_since_entry - self.params["trail_atr_mult"] * cur_atr
                profit_target = entry_price + self.params["target_atr_mult"] * cur_atr
                bars_held = i - entry_idx
                max_bars = int(self.params["max_hold_bars"])

                di_reversal = (
                    pd.notna(daily_di_minus_4h.iloc[i])
                    and pd.notna(daily_di_plus_4h.iloc[i])
                    and daily_di_minus_4h.iloc[i] > daily_di_plus_4h.iloc[i]
                )

                exit_signal = (
                    (pd.notna(cur_atr) and cur_low <= trail_stop)
                    or (pd.notna(cur_atr) and cur_high >= profit_target)
                    or di_reversal
                    or bars_held >= max_bars
                )

                if exit_signal:
                    in_position = False
                    signals.iloc[i] = 0.0
                else:
                    signals.iloc[i] = 1.0
            else:
                if entry.iloc[i]:
                    in_position = True
                    entry_price = close.iloc[i]
                    entry_idx = i
                    lowest_since_entry = low.iloc[i]
                    signals.iloc[i] = 1.0
                else:
                    signals.iloc[i] = 0.0

        signals[: self.warmup] = 0.0
        return signals
