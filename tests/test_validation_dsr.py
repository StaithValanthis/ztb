from __future__ import annotations

import math

from ztb.validation.deflated_sharpe import (
    DeflatedSharpeResult,
    compute_deflated_sharpe,
)


def test_dsr_zero_sharpe_one_trial() -> None:
    result = compute_deflated_sharpe(sharpe=0.0, n_observations=100, n_trials=1)
    assert abs(result.dsr - 0.5) < 0.01
    assert result.is_significant is False


def test_dsr_zero_sharpe_many_trials() -> None:
    result = compute_deflated_sharpe(sharpe=0.0, n_observations=100, n_trials=100)
    assert result.dsr < 0.5
    assert result.is_significant is False


def test_dsr_monotonic_decreasing() -> None:
    dsr_vals = []
    for n in [1, 2, 5, 10, 50, 100]:
        r = compute_deflated_sharpe(sharpe=1.5, n_observations=200, n_trials=n)
        dsr_vals.append(r.dsr)
    for i in range(len(dsr_vals) - 1):
        assert dsr_vals[i + 1] <= dsr_vals[i] + 1e-10


def test_dsr_approx_normal_cdf() -> None:
    n_obs = 500
    for sharpe in [0.0, 0.5, 1.0, 1.5, 2.0]:
        r = compute_deflated_sharpe(sharpe=sharpe, n_observations=n_obs, n_trials=1)
        expected = 0.5 * (1.0 + math.erf(sharpe * math.sqrt(n_obs) / math.sqrt(2.0)))
        assert abs(r.dsr - expected) < 0.01


def test_dsr_negative_sharpe() -> None:
    result = compute_deflated_sharpe(sharpe=-0.5, n_observations=100, n_trials=1)
    assert result.dsr < 0.5


def test_dsr_clamps_negative_trials() -> None:
    r1 = compute_deflated_sharpe(sharpe=0.5, n_observations=100, n_trials=0)
    r2 = compute_deflated_sharpe(sharpe=0.5, n_observations=100, n_trials=-5)
    assert abs(r1.dsr - r2.dsr) < 1e-10


def test_dsr_significant_threshold() -> None:
    r = compute_deflated_sharpe(sharpe=3.0, n_observations=1000, n_trials=1)
    assert r.is_significant is True
    assert r.dsr >= 0.95


def test_dsr_non_normal_returns() -> None:
    skew = 1.0
    kurt = 5.0
    r_normal = compute_deflated_sharpe(sharpe=0.6, n_observations=100, n_trials=1)
    r_skewed = compute_deflated_sharpe(
        sharpe=0.6, n_observations=100, n_trials=1, skew=skew, kurtosis=kurt
    )
    assert r_normal.dsr != r_skewed.dsr


def test_dsr_result_type() -> None:
    r = compute_deflated_sharpe(sharpe=1.0, n_observations=100)
    assert isinstance(r, DeflatedSharpeResult)
    assert isinstance(r.dsr, float)
    assert isinstance(r.n_trials_equivalent, int)
    assert isinstance(r.is_significant, bool)


def test_dsr_range() -> None:
    for sharpe in [0.0, 0.5, 1.0, 2.0, -1.0]:
        for n in [10, 100, 500]:
            r = compute_deflated_sharpe(sharpe=sharpe, n_observations=n, n_trials=5)
            assert 0.0 <= r.dsr <= 1.0
