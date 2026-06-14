from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from ztb.strategies.base import Strategy


@dataclass
class LookaheadResult:
    passed: bool
    details: list[str]
    bars_checked: int
    mode: str


_SENTINEL = -999999.0


def run_lookahead_tripwire(
    strategy: Strategy,
    data_factory: Callable[[], pd.DataFrame],
) -> LookaheadResult:
    clean = data_factory()
    if clean.empty:
        return LookaheadResult(passed=True, details=[], bars_checked=0, mode="frame")

    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(clean.columns)
    if missing:
        return LookaheadResult(
            passed=False,
            details=[f"Missing required columns: {missing}"],
            bars_checked=0,
            mode="frame",
        )

    baseline_signals = strategy.generate_signals(clean)
    if len(baseline_signals) != len(clean):
        return LookaheadResult(
            passed=False,
            details=[f"Signal length {len(baseline_signals)} != data length {len(clean)}"],
            bars_checked=0,
            mode="frame",
        )

    corrupted = clean.copy()
    for col in ["open", "high", "low", "close", "volume"]:
        corrupted[col] = corrupted[col].astype(float)
    corrupted.iloc[-1] = _SENTINEL

    corrupted_signals = strategy.generate_signals(corrupted)
    if len(corrupted_signals) != len(corrupted):
        return LookaheadResult(
            passed=False,
            details=[
                f"Corrupted signal length {len(corrupted_signals)} != data length {len(corrupted)}"
            ],
            bars_checked=0,
            mode="frame",
        )

    n = len(clean) - 1
    violations: list[str] = []
    for i in range(n):
        orig = float(baseline_signals.iloc[i])
        corr = float(corrupted_signals.iloc[i])
        if abs(orig - corr) > 1e-10:
            violations.append(f"Signal mismatch at bar {i}: clean={orig:.6f}, corrupted={corr:.6f}")

    if violations:
        return LookaheadResult(
            passed=False,
            details=violations,
            bars_checked=n,
            mode="frame",
        )

    return LookaheadResult(passed=True, details=[], bars_checked=n, mode="frame")
