from __future__ import annotations

import pandas as pd

from ztb.features.indicators import atr, sma
from ztb.strategies.base import RiskProfile, Strategy
from ztb.strategies.registry import register


@register
class SMA20RejectionShort(Strategy):
    name = "sma20_rejection_short"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "4h"
    params: dict[str, float | int | str] = {
        "volume_spike_mult": 3.0,
        "volume_spike_lookback": 5,
        "volume_collapse_ratio": 0.5,
        "trail_atr_mult": 2.0,
        "max_hold_bars": 10,
    }
    warmup: int = 200
    risk_profile = RiskProfile()

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        sma20 = sma(df["close"], 20)
        sma200 = sma(df["close"], 200)
        vol_sma20 = sma(df["volume"], 20)
        atr14 = atr(df["high"], df["low"], df["close"], 14)

        signals = pd.Series(0.0, index=df.index)
        active = False
        entry_bar = 0
        highest_high_since_entry = 0.0

        vol_lookback = int(self.params["volume_spike_lookback"])
        vol_spike_mult = float(self.params["volume_spike_mult"])
        vol_collapse = float(self.params["volume_collapse_ratio"])
        trail_mult = float(self.params["trail_atr_mult"])
        max_hold = int(self.params["max_hold_bars"])

        for i in range(len(df)):
            if i < self.warmup:
                continue

            if active:
                bars_since_entry = i - entry_bar
                trail_stop = highest_high_since_entry - trail_mult * atr14.iloc[i]

                exit_trail = df["low"].iloc[i] <= trail_stop
                exit_sma20 = df["close"].iloc[i] > sma20.iloc[i]
                exit_time = bars_since_entry >= max_hold

                if exit_trail or exit_sma20 or exit_time:
                    signals.iloc[i] = 0.0
                    active = False
                else:
                    signals.iloc[i] = -1.0
                    highest_high_since_entry = max(highest_high_since_entry, df["high"].iloc[i])
            else:
                bear_macro = df["close"].iloc[i] < sma200.iloc[i]
                below_sma20 = df["close"].iloc[i] < sma20.iloc[i]

                if not bear_macro or not below_sma20:
                    signals.iloc[i] = 0.0
                    continue

                lookback_start = max(0, i - vol_lookback)
                spike_found = False
                max_spike_vol = 0.0

                for j in range(lookback_start, i + 1):
                    vol_threshold = vol_spike_mult * vol_sma20.iloc[j]
                    if df["volume"].iloc[j] > vol_threshold and df["high"].iloc[j] >= sma20.iloc[j]:
                        spike_found = True
                        max_spike_vol = max(max_spike_vol, df["volume"].iloc[j])

                if not spike_found:
                    signals.iloc[i] = 0.0
                    continue

                vol_collapsed = df["volume"].iloc[i] < vol_collapse * max_spike_vol
                if not vol_collapsed:
                    signals.iloc[i] = 0.0
                    continue

                signals.iloc[i] = -1.0
                active = True
                entry_bar = i
                highest_high_since_entry = df["high"].iloc[i]

        signals.iloc[: self.warmup] = 0.0
        return signals
