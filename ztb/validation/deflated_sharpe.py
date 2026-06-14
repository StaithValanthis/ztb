from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class DeflatedSharpeResult:
    dsr: float
    n_trials_equivalent: int
    is_significant: bool


_EULER_MASCHERONI = 0.5772156649
_PI_SQ_OVER_12 = np.pi**2 / 12.0


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def compute_deflated_sharpe(
    sharpe: float,
    n_observations: int,
    n_trials: int = 1,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> DeflatedSharpeResult:
    if n_trials < 1:
        n_trials = 1

    v = 1.0 + (skew / 2.0) * sharpe + ((kurtosis - 3.0) / 4.0) * sharpe**2
    if v <= 0.0:
        v = 1.0

    z_star = sharpe * np.sqrt(n_observations / v)

    if n_trials <= 1:
        dsr = _norm_cdf(z_star)
        return DeflatedSharpeResult(dsr=dsr, n_trials_equivalent=1, is_significant=dsr >= 0.95)

    n_float = float(n_trials)
    ln_n = np.log(n_float)
    e_max_z = np.sqrt(2.0 * ln_n) + _EULER_MASCHERONI / np.sqrt(2.0 * ln_n) if ln_n > 0 else 0.0
    var_max_z = _PI_SQ_OVER_12 / ln_n if ln_n > 0 else 0.0

    if var_max_z <= 0.0:
        dsr = 1.0 if z_star > e_max_z else 0.0
    else:
        dsr = _norm_cdf((z_star - e_max_z) / np.sqrt(var_max_z))

    return DeflatedSharpeResult(dsr=dsr, n_trials_equivalent=n_trials, is_significant=dsr >= 0.95)
