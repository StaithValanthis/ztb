from __future__ import annotations

from typing import Any

import numpy as np
from pandas import DataFrame

NDArray = np.ndarray[Any, Any]


def compute_heat(weights: NDArray, cov: NDArray) -> float:
    return float(np.sqrt(weights.T @ cov @ weights))


def rolling_correlation(returns: DataFrame, window: int = 21) -> dict[tuple[str, str], float]:
    corr_dict: dict[tuple[str, str], float] = {}
    cols = returns.columns.tolist()
    for i in range(len(cols)):
        for j in range(i, len(cols)):
            pair_corr = returns.iloc[-window:][cols[i]].corr(returns.iloc[-window:][cols[j]])
            val = float(pair_corr) if not np.isnan(pair_corr) else 0.0
            corr_dict[(cols[i], cols[j])] = val
            corr_dict[(cols[j], cols[i])] = val
    return corr_dict


def heat_cap_check(heat: float, max_heat: float = 1.0) -> tuple[bool, str]:
    if heat > max_heat:
        return (False, f"heat {heat:.4f} exceeds cap {max_heat}")
    return (True, "")


def correlation_check(
    weights: dict[str, float],
    corr_matrix: dict[tuple[str, str], float],
    max_corr: float = 0.80,
) -> tuple[bool, str]:
    symbols = list(weights.keys())
    total_weight = sum(abs(w) for w in weights.values())
    if total_weight == 0:
        return (True, "")
    weighted_corr_sum = 0.0
    total_weighted: float = 0.0
    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            w_i = abs(weights[symbols[i]]) / total_weight
            w_j = abs(weights[symbols[j]]) / total_weight
            corr = corr_matrix.get((symbols[i], symbols[j]), 0.0)
            weighted_corr_sum += w_i * w_j * corr
            total_weighted += w_i * w_j
    avg_corr = weighted_corr_sum / total_weighted if total_weighted > 0 else 0.0
    if avg_corr > max_corr:
        return (False, f"weighted avg correlation {avg_corr:.4f} exceeds cap {max_corr}")
    return (True, "")
