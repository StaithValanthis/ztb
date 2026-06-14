from __future__ import annotations

from math import erf, log, sqrt

from pandas import Series


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    if p <= 0.0:
        return -10.0
    if p >= 1.0:
        return 10.0

    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = sqrt(-2.0 * log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = sqrt(-2.0 * log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)

    return x


def compute_dsr(
    sharpe: float | None,
    returns: Series,
    num_trials: int = 1,
    periods_per_year: float = 365 * 24,
    significance: float = 0.05,
) -> float:
    if sharpe is None or len(returns) < 3:
        return 0.0
    if sharpe <= 0.0:
        return 0.0

    t = float(len(returns))
    r_skew = float(returns.skew())  # type: ignore[arg-type]
    r_kurt = float(returns.kurtosis())  # type: ignore[arg-type]

    sr_annualized = sharpe
    sr_non_ann = sr_annualized / sqrt(periods_per_year)
    gamma3 = r_skew
    gamma4 = r_kurt + 3.0

    v = (
        1.0
        + 0.5 * gamma4 * sr_non_ann
        - gamma3 * sr_non_ann
        + (gamma4 - 1.0) * sr_non_ann * sr_non_ann / 4.0
    ) / (t - 1.0)
    if v <= 0.0:
        v = 1e-10

    denom = sqrt(max(
        1.0 - gamma3 * sr_non_ann + (gamma4 - 1.0) * sr_non_ann * sr_non_ann / 4.0,
        1e-10,
    ))

    max_sr_quantile = _norm_ppf(1.0 - significance / max(num_trials, 1))
    e_max_sr = max_sr_quantile * sqrt(v)

    numerator = sr_non_ann * sqrt(t - 1.0) - e_max_sr
    dsr_z = numerator / denom

    dsr = _norm_cdf(dsr_z)
    return min(max(dsr, 0.0), 1.0)
