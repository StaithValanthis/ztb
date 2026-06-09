from __future__ import annotations

import pandas as pd

from ztb.features.indicators import sma
from ztb.strategies.base import Strategy
from ztb.strategies.registry import register


@register
class SMACross(Strategy):
    name = "sma_cross"
    symbols: list[str] = []
    timeframe: str = "60"
    params: dict[str, float | int | str] = {"fast": 5, "slow": 20}
    warmup: int = 20

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_period = int(self.params["fast"])
        slow_period = int(self.params["slow"])
        fast = sma(df["close"], fast_period)
        slow = sma(df["close"], slow_period)
        signals = pd.Series(0.0, index=df.index)
        signals[fast > slow] = 1.0
        signals[: self.warmup] = 0.0
        return signals
