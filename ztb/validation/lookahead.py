from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pandas import DataFrame, Series


@dataclass
class LookaheadReport:
    passed: bool
    forward_shift_applied: bool
    warmup_enforced: bool
    signal_before_close: bool
    trades_use_future_close: bool = False
    equity_use_future_close: bool = False
    details: list[str] = field(default_factory=list)
    score: float = 1.0


def check_lookahead(
    signals: Series,
    data: DataFrame,
    warmup: int = 0,
    trades: list[dict[str, Any]] | None = None,
    timestamps: list[Any] | None = None,
) -> LookaheadReport:
    details: list[str] = []
    issues = 0

    if len(signals) != len(data):
        return LookaheadReport(
            passed=False,
            forward_shift_applied=True,
            warmup_enforced=True,
            signal_before_close=True,
            details=["Signal length mismatch"],
            score=0.0,
        )

    forward_shift_applied = True
    if signals is not None and len(signals) > 1:
        close = data["close"].values
        sig_vals = signals.values
        non_zero = np.where(np.abs(sig_vals) > 1e-10)[0]
        if len(non_zero) > 0:
            first_signal_idx = non_zero[0]
            if first_signal_idx > 0:
                prev_close = close[first_signal_idx - 1]
                curr_close = close[first_signal_idx]
                if _same_bar(prev_close, curr_close) and first_signal_idx < len(data) - 1:
                    details.append("Signals may not be forward-shifted (use close of current bar)")
                    forward_shift_applied = False
                    issues += 1

    warmup_enforced = True
    if warmup > 0 and len(signals) > warmup:
        warmup_signals = signals.iloc[:warmup]
        if warmup_signals.abs().max() > 1e-10:
            details.append(f"Warmup period ({warmup} bars) contains non-zero signals")
            warmup_enforced = False
            issues += 1

    signal_before_close = True
    close_arr = data["close"].values
    if len(non_zero := np.where(np.abs(sig_vals) > 1e-10)[0]) > 0:
        for idx in non_zero[:10]:
            sig = float(sig_vals[idx])
            if abs(sig) > 1e-10 and idx < len(close_arr) - 1:
                today_close = close_arr[idx]
                tomorrow_close = close_arr[idx + 1]
                price_move = tomorrow_close - today_close
                expected_direction = np.sign(price_move) if price_move != 0 else 0
                signal_direction = np.sign(sig)
                if (expected_direction != 0 and signal_direction == expected_direction
                        and _is_suspicious(idx, sig_vals, close_arr)):
                    details.append(
                        f"Suspicious signal at index {idx}: aligns with next-close move"
                    )
                    signal_before_close = False
                    issues += 1
                    break

    trades_use_future_close = False
    if trades is not None and timestamps is not None and len(trades) > 0:
        from pandas import Timestamp

        trade_times = []
        for t in trades:
            ts = t.get("timestamp")
            if ts is not None:
                trade_times.append(Timestamp(ts) if not isinstance(ts, Timestamp) else ts)

        data_times = list(timestamps)
        if trade_times and data_times:
            last_data_time = max(data_times)
            for tt in trade_times[:5]:
                if tt > last_data_time:
                    trades_use_future_close = True
                    details.append(f"Trade timestamp {tt} beyond data range {last_data_time}")
                    issues += 1
                    break

    equity_use_future_close = False

    score = max(0.0, 1.0 - issues * 0.25)
    passed = issues == 0

    return LookaheadReport(
        passed=passed,
        forward_shift_applied=forward_shift_applied,
        warmup_enforced=warmup_enforced,
        signal_before_close=signal_before_close,
        trades_use_future_close=trades_use_future_close,
        equity_use_future_close=equity_use_future_close,
        details=details,
        score=score,
    )


def _same_bar(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) < tol


def _is_suspicious(idx: int, sig_vals: Any, close_vals: Any) -> bool:
    if idx < 1 or idx >= len(close_vals) - 1:
        return False
    prev_move = abs(close_vals[idx] - close_vals[idx - 1])
    next_move = abs(close_vals[idx + 1] - close_vals[idx])
    avg_move = (prev_move + next_move) / 2.0 if prev_move + next_move > 0 else 1.0
    if avg_move < 1e-10:
        return False
    ratio = float(abs(sig_vals[idx]) * (close_vals[idx + 1] - close_vals[idx]) / avg_move)
    return bool(abs(ratio) > 1.0)
