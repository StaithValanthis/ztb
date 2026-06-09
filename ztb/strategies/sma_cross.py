from __future__ import annotations

import pandas as pd
from pandas import Series

from ztb.strategies.base import Strategy


class SmaCross(Strategy):
    name = "sma_cross"
    symbols: list[str] = []
    timeframe: str = "60"
    params: dict[str, float | int | str] = {"fast": 10, "slow": 30}
    warmup: int = 30

    def generate_signals(self, df: pd.DataFrame) -> Series:
        fast = df["close"].rolling(window=int(self.params["fast"]), min_periods=int(self.params["fast"])).mean()
        slow = df["close"].rolling(window=int(self.params["slow"]), min_periods=int(self.params["slow"])).mean()
        signals = pd.Series(0.0, index=df.index, dtype="float64")
        signals[fast > slow] = 1.0
        signals.iloc[: self.warmup] = 0.0
        return signals
