from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import Series

from ztb.validation.dsr import compute_dsr, _norm_cdf, _norm_ppf


def test_norm_cdf_bounds() -> None:
    assert abs(_norm_cdf(0.0) - 0.5) < 1e-10
    assert _norm_cdf(-10.0) < 1e-10
    assert abs(_norm_cdf(10.0) - 1.0) < 1e-10


def test_norm_ppf_roundtrip() -> None:
    for p in [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]:
        z = _norm_ppf(p)
        p2 = _norm_cdf(z)
        assert abs(p - p2) < 1e-6


def test_norm_ppf_extremes() -> None:
    assert _norm_ppf(0.0) == -10.0
    assert _norm_ppf(1.0) == 10.0


def test_dsr_none_sharpe() -> None:
    returns = Series(np.random.randn(100))
    assert compute_dsr(None, returns) == 0.0


def test_dsr_negative_sharpe() -> None:
    returns = Series(-np.abs(np.random.randn(100)))
    # negative returns will give negative sharpe
    sr = -0.5
    assert compute_dsr(sr, returns) == 0.0


def test_dsr_zero_sharpe() -> None:
    returns = Series(np.random.randn(100))
    assert compute_dsr(0.0, returns) == 0.0


def test_dsr_short_returns() -> None:
    returns = Series([0.01, -0.02])
    assert compute_dsr(2.0, returns) == 0.0


def test_dsr_high_sharpe_returns_high_dsr() -> None:
    np.random.seed(42)
    returns = Series(np.random.randn(500) * 0.01 + 0.0005)
    sr = 1.5
    dsr = compute_dsr(sr, returns, num_trials=1)
    assert 0.0 <= dsr <= 1.0
    assert dsr > 0.5


def test_dsr_low_sharpe_returns_low_dsr() -> None:
    np.random.seed(42)
    returns = Series(np.random.randn(500) * 0.02)
    sr = 0.3
    dsr = compute_dsr(sr, returns, num_trials=100)
    assert 0.0 <= dsr <= 1.0
    assert dsr < 0.5


def test_dsr_many_trials_reduces_dsr() -> None:
    np.random.seed(42)
    returns = Series(np.random.randn(500) * 0.01 + 0.0005)
    sr = 1.5
    dsr_1 = compute_dsr(sr, returns, num_trials=1)
    dsr_100 = compute_dsr(sr, returns, num_trials=100)
    assert dsr_100 <= dsr_1 + 1e-10


def test_dsr_consistent_range() -> None:
    np.random.seed(42)
    returns = Series(np.random.randn(1000) * 0.01 + 0.001)
    sr = 2.0
    dsr = compute_dsr(sr, returns, num_trials=1)
    assert 0.0 <= dsr <= 1.0


def test_dsr_deterministic() -> None:
    np.random.seed(123)
    returns = Series(np.random.randn(200) * 0.01 + 0.0005)
    sr = 1.2
    dsr1 = compute_dsr(sr, returns, num_trials=5)
    dsr2 = compute_dsr(sr, returns, num_trials=5)
    assert dsr1 == dsr2


def test_dsr_skewed_returns() -> None:
    np.random.seed(42)
    positive = np.abs(np.random.randn(400)) * 0.01 + 0.001
    negative = -np.abs(np.random.randn(100)) * 0.02 - 0.002
    returns = Series(np.concatenate([positive, negative]))
    sr = 1.0
    dsr = compute_dsr(sr, returns, num_trials=1)
    assert 0.0 <= dsr <= 1.0
