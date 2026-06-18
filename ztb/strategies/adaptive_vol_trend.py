from __future__ import annotations

import pandas as pd
from pandas import DataFrame, Series

from ztb.features.indicators import atr, ema, sma
from ztb.strategies.base import Strategy
from ztb.strategies.registry import register


@register
class AdaptiveVolTrend(Strategy):
    name = "adaptive_vol_trend"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "60"
    params: dict[str, float | int | str] = {
        "vol_lookback": 63,
        "atr_period": 21,
        "sma_period": 50,
        "range_multiplier": 1.5,
        "vol_z_threshold": 0.5,
        "trend_fast": 12,
        "trend_slow": 26,
    }
    warmup: int = 84

    def generate_signals(self, df: DataFrame) -> Series:
        close = df["close"]
        high = df["high"]
        low = df["low"]

        vol_lookback = int(self.params["vol_lookback"])
        atr_period = int(self.params["atr_period"])
        sma_period = int(self.params["sma_period"])
        range_multiplier = float(self.params["range_multiplier"])
        vol_z_threshold = float(self.params["vol_z_threshold"])
        trend_fast = int(self.params["trend_fast"])
        trend_slow = int(self.params["trend_slow"])

        atr_val = atr(high, low, close, atr_period)
        atr_mean = atr_val.rolling(window=vol_lookback, min_periods=vol_lookback).mean()
        atr_std = atr_val.rolling(window=vol_lookback, min_periods=vol_lookback).std(ddof=0)
        z_score = (atr_val - atr_mean) / atr_std.replace(0, pd.NA)

        sma_val = sma(close, sma_period)
        ema_fast = ema(close, trend_fast)
        ema_slow = ema(close, trend_slow)

        signals = pd.Series(0.0, index=df.index)

        low_vol_mask = z_score < vol_z_threshold
        high_vol_mask = z_score >= vol_z_threshold

        long_low_vol = close > sma_val + range_multiplier * atr_val
        short_low_vol = close < sma_val - range_multiplier * atr_val
        long_high_vol = ema_fast > ema_slow
        short_high_vol = ema_fast < ema_slow

        signals[low_vol_mask & long_low_vol] = 1.0
        signals[low_vol_mask & short_low_vol] = -1.0
        signals[high_vol_mask & long_high_vol] = 1.0
        signals[high_vol_mask & short_high_vol] = -1.0

        signals.iloc[: self.warmup] = 0.0

        return signals
