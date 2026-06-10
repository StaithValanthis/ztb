from __future__ import annotations


def dd_budget_scalar(
    current_dd: float,
    max_dd: float = 0.25,
    scalar: float = 3.0,
) -> float:
    if current_dd <= 0.0:
        return 1.0
    if current_dd >= max_dd:
        return 0.0
    return float(max(0.0, 1.0 - (current_dd / max_dd) ** scalar))
