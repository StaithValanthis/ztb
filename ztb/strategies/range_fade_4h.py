from __future__ import annotations

import pandas as pd

from ztb.strategies.base import Strategy
from ztb.strategies.registry import register


@register
class RangeFade4h(Strategy):
    name = "range_fade_4h"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "240"
    params: dict[str, float | int | str] = {
        "lookback": 30,
        "long_entry_bps": 200,
        "short_entry_bps": 100,
        "stop_bps": 80,
        "range_min_bps": 200,
        "range_max_bps": 1500,
    }
    warmup: int = 30

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        lookback = int(self.params["lookback"])
        long_entry_bps = int(self.params["long_entry_bps"])
        short_entry_bps = int(self.params["short_entry_bps"])
        range_min_bps = int(self.params["range_min_bps"])
        range_max_bps = int(self.params["range_max_bps"])

        recent_high = df["high"].rolling(window=lookback, min_periods=lookback).max()
        recent_low = df["low"].rolling(window=lookback, min_periods=lookback).min()
        range_bps = (recent_high - recent_low) / recent_low * 10000

        signals = pd.Series(0.0, index=df.index)

        near_low = df["close"] <= recent_low * (1 + long_entry_bps / 10000)
        near_high = df["close"] >= recent_high * (1 - short_entry_bps / 10000)
        in_range = (range_bps >= range_min_bps) & (range_bps <= range_max_bps)

        signals.loc[in_range & near_low & ~near_high] = 1.0
        signals.loc[in_range & near_high] = -1.0
        signals.iloc[: self.warmup] = 0.0
        signals = signals.fillna(0.0)

        return signals
