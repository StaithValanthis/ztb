from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd
from pandas import Series


class Strategy(ABC):
    name: str
    symbols: list[str]
    timeframe: str
    params: dict[str, float | int | str]
    warmup: int

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> Series: ...


class StrategyError(Exception):
    pass
