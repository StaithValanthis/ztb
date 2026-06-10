from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import Series


def sma(series: Series, period: int) -> Series:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: Series, period: int) -> Series:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    return series.ewm(span=period, min_periods=period, adjust=False).mean()


def rsi(series: Series, period: int = 14) -> Series:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    rsi_series = rsi_series.bfill()
    rsi_series = rsi_series.fillna(50.0)
    return rsi_series


def atr(high: Series, low: Series, close: Series, period: int = 14) -> Series:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


def crossover(series1: Series, series2: Series) -> Series:
    prev_above = series1.shift(1) >= series2.shift(1)
    now_below = series1 < series2
    return (prev_above & now_below).astype(int)
