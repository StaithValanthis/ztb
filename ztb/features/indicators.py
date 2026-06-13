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


def adx(high: Series, low: Series, close: Series, period: int = 14) -> Series:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    plus = di_plus(high, low, close, period)
    minus = di_minus(high, low, close, period)
    dx = (minus - plus).abs() / (minus + plus).replace(0, np.nan) * 100
    return dx.rolling(window=period, min_periods=period).mean()


def di_plus(high: Series, low: Series, close: Series, period: int = 14) -> Series:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    prev_close = close.shift(1)
    up_move = high - prev_close
    down_move = prev_close - low
    direction = (up_move > down_move) & (up_move > 0)
    plus_dm = pd.Series(np.where(direction, up_move, 0.0), index=high.index)
    atr_val = atr(high, low, close, period)
    dm_sum = plus_dm.rolling(window=period, min_periods=period).sum()
    return dm_sum / atr_val.replace(0, np.nan) * 100


def di_minus(high: Series, low: Series, close: Series, period: int = 14) -> Series:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    prev_close = close.shift(1)
    up_move = high - prev_close
    down_move = prev_close - low
    direction = (down_move > up_move) & (down_move > 0)
    minus_dm = pd.Series(np.where(direction, down_move, 0.0), index=high.index)
    atr_val = atr(high, low, close, period)
    dm_sum = minus_dm.rolling(window=period, min_periods=period).sum()
    return dm_sum / atr_val.replace(0, np.nan) * 100


def bb(close: Series, period: int = 20, std_dev: float = 2.0) -> tuple[Series, Series, Series]:
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    middle = close.rolling(window=period, min_periods=period).mean()
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def bb_width(close: Series, period: int = 20, std_dev: float = 2.0) -> Series:
    upper, middle, lower = bb(close, period, std_dev)
    return (upper - lower) / middle * 100
