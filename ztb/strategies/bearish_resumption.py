from __future__ import annotations

import pandas as pd
from pandas import DataFrame, DatetimeIndex, Series

from ztb.data.loader import load as _load
from ztb.features.indicators import adx, atr, bb, bb_width, di_minus, di_plus, ema
from ztb.strategies.base import Strategy
from ztb.strategies.registry import register


@register
class BearishResumption(Strategy):
    name = "bearish_resumption"
    symbols: list[str] = ["BTCUSDT"]
    timeframe: str = "240"
    params: dict[str, float | int | str] = {
        "adx_threshold": 25,
        "ema_fast": 20,
        "ema_slow": 100,
        "ema_mid": 50,
        "bb_width_threshold": 2.0,
        "daily_ema_trend": 200,
        "min_retrace_pct": 3.0,
        "exhaustion_adx": 20,
        "bb_z_threshold": -0.5,
        "trail_atr_mult": 2.5,
    }
    warmup: int = 300

    def generate_signals(self, df: DataFrame) -> Series:
        idx = df.index
        if isinstance(idx, DatetimeIndex) and idx.tz is None:
            df = df.tz_localize("UTC")
        close_sh = df["close"].shift(1)

        daily = (
            df.resample("D")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )

        daily_adx_val = adx(daily["high"], daily["low"], daily["close"], 14)
        daily_di_plus_val = di_plus(daily["high"], daily["low"], daily["close"], 14)
        daily_di_minus_val = di_minus(daily["high"], daily["low"], daily["close"], 14)
        daily_ema_trend = ema(daily["close"], int(self.params["daily_ema_trend"]))
        daily_ema_50 = ema(daily["close"], int(self.params["ema_fast"]))

        daily_idx = DataFrame(index=daily.index)
        daily_idx["_adx"] = daily_adx_val
        daily_idx["_di_plus"] = daily_di_plus_val
        daily_idx["_di_minus"] = daily_di_minus_val
        daily_idx["_ema_trend"] = daily_ema_trend
        daily_idx["_ema_50"] = daily_ema_50
        daily_idx["_close"] = daily["close"]
        daily_4h = (
            pd.merge_asof(
                df[[]],
                daily_idx,
                left_index=True,
                right_index=True,
                direction="backward",
            )
            .bfill()
            .ffill()
        )
        d_adx = daily_4h["_adx"]
        d_di_plus = daily_4h["_di_plus"]
        d_di_minus = daily_4h["_di_minus"]
        d_ema_trend = daily_4h["_ema_trend"]
        d_ema_50 = daily_4h["_ema_50"]
        d_close = daily_4h["_close"]

        ema_fast_val = ema(df["close"], int(self.params["ema_fast"]))
        ema_slow_val = ema(df["close"], int(self.params["ema_slow"]))
        ema_mid_val = ema(df["close"], int(self.params["ema_mid"]))
        adx_4h = adx(df["high"], df["low"], df["close"], 14)
        atr_4h = atr(df["high"], df["low"], df["close"], 14)
        lowest_50 = df["close"].rolling(window=50, min_periods=50).min()

        start_dt = (df.index[0] - pd.Timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_dt = df.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
        df_1h = _load("BTCUSDT", "60", start=start_dt, end=end_dt)
        adx_1h_f = adx(df_1h["high"], df_1h["low"], df_1h["close"], 14)
        bb_u_1h_f, bb_m_1h_f, bb_l_1h_f = bb(df_1h["close"], 20, 2)
        bb_w_1h_f = bb_width(df_1h["close"], 20, 2)
        bb_w_1h_mean = bb_w_1h_f.rolling(50).mean()
        bb_w_1h_std = bb_w_1h_f.rolling(50).std(ddof=0)
        bb_z_1h_f = (bb_w_1h_f - bb_w_1h_mean) / bb_w_1h_std.replace(0, pd.NA)

        df_1h_idx = DataFrame({"close_1h": df_1h["close"]}, index=df_1h.index)
        df_1h_idx["adx_1h"] = adx_1h_f
        df_1h_idx["bb_u_1h"] = bb_u_1h_f
        df_1h_idx["bb_m_1h"] = bb_m_1h_f
        df_1h_idx["bb_l_1h"] = bb_l_1h_f
        df_1h_idx["bb_w_1h"] = bb_w_1h_f
        df_1h_idx["bb_z_1h"] = bb_z_1h_f

        aligned_1h = pd.merge_asof(
            df[[]],
            df_1h_idx,
            left_index=True,
            right_index=True,
            direction="backward",
        )
        close_1h_a = aligned_1h["close_1h"]
        adx_1h_a = aligned_1h["adx_1h"]
        bb_u_1h_a = aligned_1h["bb_u_1h"]
        bb_l_1h_a = aligned_1h["bb_l_1h"]
        bb_w_1h_a = aligned_1h["bb_w_1h"]
        bb_z_1h_a = aligned_1h["bb_z_1h"]

        signals = pd.Series(0.0, index=df.index)
        active = False
        highest_close = 0.0
        entry_type: str | None = None

        for i in range(len(df)):
            if i < self.warmup:
                continue

            if active:
                stop_level = highest_close - float(self.params["trail_atr_mult"]) * atr_4h.iloc[i]
                cond_exit_a = close_sh.iloc[i] <= ema_fast_val.iloc[i]
                cond_exit_b = d_adx.iloc[i] <= self.params["adx_threshold"]
                cond_exit_c = d_close.iloc[i] > d_ema_50.iloc[i]
                cond_exit_d = close_sh.iloc[i] <= stop_level
                cond_exit_e = entry_type == "B" and close_1h_a.iloc[i] > bb_u_1h_a.iloc[i]

                if cond_exit_a or cond_exit_b or cond_exit_c or cond_exit_d or cond_exit_e:
                    signals.iloc[i] = 0.0
                    active = False
                else:
                    signals.iloc[i] = -1.0
                    highest_close = max(highest_close, df["close"].iloc[i])
            else:
                pre_a = d_adx.iloc[i] > self.params["adx_threshold"]
                pre_b = d_di_minus.iloc[i] > d_di_plus.iloc[i]
                pre_c = d_close.iloc[i] < d_ema_trend.iloc[i]
                precondition = pre_a and pre_b and pre_c

                if precondition:
                    min_retrace = 1 + float(self.params["min_retrace_pct"]) / 100
                    mode_a = (
                        close_sh.iloc[i] > ema_fast_val.iloc[i]
                        and close_sh.iloc[i] >= min_retrace * lowest_50.iloc[i]
                        and adx_1h_a.iloc[i] < self.params["exhaustion_adx"]
                        and bb_z_1h_a.iloc[i] < self.params["bb_z_threshold"]
                        and close_sh.iloc[i] < ema_slow_val.iloc[i]
                    )

                    if mode_a:
                        signals.iloc[i] = -1.0
                        active = True
                        highest_close = df["close"].iloc[i]
                        entry_type = "A"
                        continue

                    mode_b = (
                        adx_4h.iloc[i] > self.params["adx_threshold"]
                        and close_sh.iloc[i] > ema_fast_val.iloc[i]
                        and close_sh.iloc[i] < ema_slow_val.iloc[i]
                        and bb_w_1h_a.iloc[i] < self.params["bb_width_threshold"]
                        and close_1h_a.iloc[i] < bb_l_1h_a.iloc[i]
                        and close_sh.iloc[i] < ema_mid_val.iloc[i]
                    )

                    if mode_b:
                        signals.iloc[i] = -1.0
                        active = True
                        highest_close = df["close"].iloc[i]
                        entry_type = "B"
                        continue

                signals.iloc[i] = 0.0

        signals.iloc[: self.warmup] = 0.0
        return signals
