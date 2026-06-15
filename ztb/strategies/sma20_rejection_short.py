from __future__ import annotations

from pandas import DataFrame, Series

from ztb.features.indicators import atr, sma
from ztb.strategies.base import Strategy
from ztb.strategies.registry import register


@register
class SMA20RejectionShort(Strategy):
    name = "sma20_rejection_short"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "240"
    params: dict[str, float | int | str] = {
        "volume_spike_mult": 3.0,
        "volume_spike_lookback": 5,
        "volume_collapse_ratio": 0.5,
        "trail_atr_mult": 2.0,
        "max_hold_bars": 10,
    }
    warmup: int = 200

    def generate_signals(self, df: DataFrame) -> Series:
        sma200 = sma(df["close"], 200)
        sma20 = sma(df["close"], 20)
        vol_sma = sma(df["volume"], 20)
        atr14 = atr(df["high"], df["low"], df["close"], 14)

        bear_macro = df["close"] < sma200
        rejection = df["close"] < sma20

        spike_mult = float(self.params["volume_spike_mult"])
        lookback = int(self.params["volume_spike_lookback"])
        spike_bar = (df["volume"] > spike_mult * vol_sma) & (df["high"] >= sma20)

        spike_vol_series = df["volume"].where(spike_bar, 0.0)
        had_spike_recently = spike_bar.rolling(lookback, min_periods=1).max() > 0
        max_spike_vol = spike_vol_series.rolling(lookback, min_periods=1).max()

        collapse_ratio = float(self.params["volume_collapse_ratio"])
        volume_collapse = df["volume"] < collapse_ratio * max_spike_vol

        signals = Series(0.0, index=df.index)
        active = False
        entry_bar = 0
        highest_since_entry = 0.0
        trail_mult = float(self.params["trail_atr_mult"])
        max_hold = int(self.params["max_hold_bars"])

        for i in range(len(df)):
            if i < self.warmup:
                continue

            if active:
                highest_since_entry = max(highest_since_entry, df["high"].iloc[i])
                stop_level = highest_since_entry - trail_mult * atr14.iloc[i]
                bars_held = i - entry_bar

                trail_hit = df["low"].iloc[i] <= stop_level
                sma20_reclaim = df["close"].iloc[i] > sma20.iloc[i]
                time_up = bars_held >= max_hold

                if trail_hit or sma20_reclaim or time_up:
                    signals.iloc[i] = 0.0
                    active = False
                else:
                    signals.iloc[i] = -1.0
            else:
                can_enter = (
                    bool(bear_macro.iloc[i])
                    and bool(rejection.iloc[i])
                    and bool(had_spike_recently.iloc[i])
                    and bool(volume_collapse.iloc[i])
                )

                if can_enter:
                    signals.iloc[i] = -1.0
                    active = True
                    entry_bar = i
                    highest_since_entry = df["high"].iloc[i]
                else:
                    signals.iloc[i] = 0.0

        signals.iloc[: self.warmup] = 0.0
        return signals
