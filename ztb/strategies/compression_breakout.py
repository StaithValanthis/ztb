from __future__ import annotations

import numpy as np
import pandas as pd

from ztb.features.indicators import sma
from ztb.strategies.base import Strategy
from ztb.strategies.registry import register


def _bb(
    close: pd.Series, period: int = 20, width: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = mid + width * std
    lower = mid - width * std
    return upper, mid, lower


def _bb_width_pct(close: pd.Series, period: int = 20, width: float = 2.0) -> pd.Series:
    mid = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    bb_range = 2 * width * std
    return bb_range / mid * 100.0


def _bb_width_zscore(
    close: pd.Series, bb_period: int = 20, bb_width: float = 2.0, z_period: int = 50
) -> pd.Series:
    width_pct = _bb_width_pct(close, bb_period, bb_width)
    mean = width_pct.rolling(window=z_period, min_periods=z_period).mean()
    std = width_pct.rolling(window=z_period, min_periods=z_period).std(ddof=0)
    z = (width_pct - mean) / std.replace(0, np.nan)
    return z


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
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


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = pd.Series(0.0, index=high.index)
    minus_dm = pd.Series(0.0, index=high.index)

    up_gt_down = (up_move > down_move) & (up_move > 0)
    down_gt_up = (down_move > up_move) & (down_move > 0)

    plus_dm[up_gt_down] = up_move[up_gt_down]
    minus_dm[down_gt_up] = down_move[down_gt_up]

    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    tr_smooth = tr.ewm(span=period, min_periods=period, adjust=False).mean()
    plus_dm_smooth = plus_dm.ewm(span=period, min_periods=period, adjust=False).mean()
    minus_dm_smooth = minus_dm.ewm(span=period, min_periods=period, adjust=False).mean()

    plus_di = 100.0 * plus_dm_smooth / tr_smooth.replace(0, np.nan)
    minus_di = 100.0 * minus_dm_smooth / tr_smooth.replace(0, np.nan)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)

    adx_series = dx.ewm(span=period, min_periods=period, adjust=False).mean()
    return adx_series


@register
class CompressionBreakout(Strategy):
    name = "compression_breakout"
    symbols: list[str] = []
    timeframe: str = "60"
    params: dict[str, float | int | str] = {
        "bb_z_entry": -1.0,
        "bb_width_max_pct": 1.5,
        "min_vol_pct": 0.3,
        "adx_entry": 25,
        "adx_exit": 20,
        "trail_atr_mult": 2.0,
        "max_hold_bars": 24,
    }
    warmup: int = 200

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        bb_upper, _, _ = _bb(close, 20, 2.0)
        bb_lower, _, _ = _bb(close, 20, 2.0)
        bb_width_pct = _bb_width_pct(close, 20, 2.0)
        bb_width_z = _bb_width_zscore(close, 20, 2.0, 50)
        atr_val = _atr(high, low, close, 14)
        atr_close_pct = atr_val / close * 100.0
        adx_val = _adx(high, low, close, 14)
        vol_sma = sma(volume, 20)

        bb_z_entry = float(self.params["bb_z_entry"])
        bb_width_max_pct = float(self.params["bb_width_max_pct"])
        min_vol_pct = float(self.params["min_vol_pct"])
        adx_entry = float(self.params["adx_entry"])
        adx_exit = float(self.params["adx_exit"])
        trail_atr_mult = float(self.params["trail_atr_mult"])
        max_hold_bars = int(self.params["max_hold_bars"])

        signals = pd.Series(0.0, index=df.index)
        position = 0.0
        entry_bar = -max_hold_bars - 1
        extreme_since_entry = 0.0

        for i in range(len(df)):
            if i < self.warmup:
                continue

            bb_z = bb_width_z.iloc[i]
            bb_w = bb_width_pct.iloc[i]
            atr_pct = atr_close_pct.iloc[i]
            adx = adx_val.iloc[i]
            vol_ok = not pd.isna(vol_sma.iloc[i]) and volume.iloc[i] > vol_sma.iloc[i]

            if position != 0.0:
                bars_held = i - entry_bar
                if position == 1.0:
                    extreme_since_entry = max(extreme_since_entry, high.iloc[i])
                    stop_price = extreme_since_entry - trail_atr_mult * atr_val.iloc[i]
                else:
                    extreme_since_entry = min(extreme_since_entry, low.iloc[i])
                    stop_price = extreme_since_entry + trail_atr_mult * atr_val.iloc[i]

                exit_signal = False
                if (
                    adx < adx_exit
                    or position == 1.0
                    and close.iloc[i] <= bb_lower.iloc[i]
                    or position == -1.0
                    and close.iloc[i] >= bb_upper.iloc[i]
                    or (position == 1.0 and close.iloc[i] <= stop_price)
                    or (position == -1.0 and close.iloc[i] >= stop_price)
                    or bars_held >= max_hold_bars
                ):
                    exit_signal = True

                if exit_signal:
                    position = 0.0

            if position == 0.0:
                in_compression = (
                    not pd.isna(bb_z)
                    and bb_z < bb_z_entry
                    and not pd.isna(bb_w)
                    and bb_w < bb_width_max_pct
                    and not pd.isna(atr_pct)
                    and atr_pct > min_vol_pct
                )

                if in_compression:
                    if (
                        vol_ok
                        and not pd.isna(close.iloc[i])
                        and not pd.isna(bb_upper.iloc[i])
                        and close.iloc[i] > bb_upper.iloc[i]
                        and not pd.isna(adx)
                        and adx > adx_entry
                    ):
                        position = 1.0
                        entry_bar = i
                        extreme_since_entry = high.iloc[i]
                    elif (
                        vol_ok
                        and not pd.isna(close.iloc[i])
                        and not pd.isna(bb_lower.iloc[i])
                        and close.iloc[i] < bb_lower.iloc[i]
                        and not pd.isna(adx)
                        and adx > adx_entry
                    ):
                        position = -1.0
                        entry_bar = i
                        extreme_since_entry = low.iloc[i]

            signals.iloc[i] = position

        signals.iloc[: self.warmup] = 0.0
        return signals
