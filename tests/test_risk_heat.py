from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ztb.risk.heat import (
    compute_heat,
    correlation_check,
    heat_cap_check,
    rolling_correlation,
)


def test_single_position_heat_equals_vol() -> None:
    weights = np.array([1.0])
    cov = np.array([[0.04]])
    heat = compute_heat(weights, cov)
    assert math.isclose(heat, 0.2, rel_tol=1e-9)


def test_two_assets_perfect_corr() -> None:
    weights = np.array([0.5, 0.5])
    cov = np.array([[0.04, 0.04], [0.04, 0.04]])
    heat = compute_heat(weights, cov)
    assert math.isclose(heat, 0.2, rel_tol=1e-9)


def test_two_assets_zero_corr() -> None:
    weights = np.array([0.5, 0.5])
    cov = np.array([[0.04, 0.0], [0.0, 0.04]])
    heat = compute_heat(weights, cov)
    expected = math.sqrt(0.5**2 * 0.04 + 0.5**2 * 0.04)
    assert math.isclose(heat, expected, rel_tol=1e-9)


def test_three_assets_unequal_weights() -> None:
    weights = np.array([0.5, 0.3, 0.2])
    cov = np.diag([0.04, 0.09, 0.16])
    heat = compute_heat(weights, cov)
    expected = math.sqrt(0.5**2 * 0.04 + 0.3**2 * 0.09 + 0.2**2 * 0.16)
    assert math.isclose(heat, expected, rel_tol=1e-9)


def test_heat_cap_check_pass() -> None:
    passed, msg = heat_cap_check(0.5, max_heat=1.0)
    assert passed is True
    assert msg == ""


def test_heat_cap_check_fail() -> None:
    passed, msg = heat_cap_check(1.5, max_heat=1.0)
    assert passed is False
    assert "exceeds" in msg


def test_heat_cap_check_boundary() -> None:
    passed, _ = heat_cap_check(1.0, max_heat=1.0)
    assert passed is True


def test_rolling_correlation_basic() -> None:
    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=50, freq="h")
    df = pd.DataFrame(
        {"A": np.random.normal(0, 1, 50), "B": np.random.normal(0, 1, 50)},
        index=dates,
    )
    corr = rolling_correlation(df, window=21)
    assert ("A", "A") in corr
    assert ("A", "B") in corr
    assert ("B", "A") in corr
    assert math.isclose(corr[("A", "A")], 1.0, rel_tol=1e-9)


def test_rolling_correlation_perfect() -> None:
    dates = pd.date_range("2020-01-01", periods=50, freq="h")
    df = pd.DataFrame(
        {"A": range(50), "B": [x * 2 for x in range(50)]},
        index=dates,
    )
    corr = rolling_correlation(df, window=21)
    assert math.isclose(corr[("A", "B")], 1.0, rel_tol=1e-3)


def test_rolling_correlation_negative() -> None:
    dates = pd.date_range("2020-01-01", periods=50, freq="h")
    df = pd.DataFrame(
        {"A": list(range(50)), "B": [-x for x in range(50)]},
        index=dates,
    )
    corr = rolling_correlation(df, window=21)
    assert corr[("A", "B")] < -0.99


def test_rolling_correlation_padding_zero() -> None:
    dates = pd.date_range("2020-01-01", periods=5, freq="h")
    df = pd.DataFrame(
        {"A": [1.0, 2.0, 3.0, 4.0, 5.0], "B": [5.0, 4.0, 3.0, 2.0, 1.0]},
        index=dates,
    )
    corr = rolling_correlation(df, window=21)
    assert isinstance(corr[("A", "B")], float)


def test_correlation_check_pass() -> None:
    weights = {"A": 0.5, "B": 0.5}
    corr_matrix = {("A", "B"): 0.3, ("B", "A"): 0.3}
    passed, msg = correlation_check(weights, corr_matrix, max_corr=0.80)
    assert passed is True


def test_correlation_check_fail() -> None:
    weights = {"A": 0.5, "B": 0.5}
    corr_matrix = {("A", "B"): 0.90, ("B", "A"): 0.90}
    passed, msg = correlation_check(weights, corr_matrix, max_corr=0.80)
    assert passed is False
    assert "correlation" in msg


def test_correlation_check_zero_weight() -> None:
    weights = {"A": 0.0, "B": 0.0}
    corr_matrix = {("A", "B"): 0.90, ("B", "A"): 0.90}
    passed, _ = correlation_check(weights, corr_matrix)
    assert passed is True


def test_correlation_check_single_asset() -> None:
    weights = {"A": 1.0}
    passed, _ = correlation_check(weights, {})
    assert passed is True
