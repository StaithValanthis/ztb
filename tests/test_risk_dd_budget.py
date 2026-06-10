from __future__ import annotations

import math

from ztb.risk.dd_budget import dd_budget_scalar


def test_at_peak_returns_one() -> None:
    assert dd_budget_scalar(0.0) == 1.0


def test_negative_dd_returns_one() -> None:
    assert dd_budget_scalar(-0.05) == 1.0


def test_at_max_dd_returns_zero() -> None:
    assert dd_budget_scalar(0.25) == 0.0


def test_above_max_dd_returns_zero() -> None:
    assert dd_budget_scalar(0.30) == 0.0


def test_exact_asserted_values_scalar_3() -> None:
    assert math.isclose(dd_budget_scalar(0.125, scalar=3.0), 0.875, rel_tol=1e-3)
    assert math.isclose(dd_budget_scalar(0.25, scalar=3.0), 0.0, rel_tol=1e-3)


def test_exact_asserted_values_scalar_2() -> None:
    assert math.isclose(dd_budget_scalar(0.125, scalar=2.0), 0.75, rel_tol=1e-3)
    assert math.isclose(dd_budget_scalar(0.25, scalar=2.0), 0.0, rel_tol=1e-3)


def test_monotonically_decreasing() -> None:
    vals = [0.0, 0.05, 0.1, 0.15, 0.2, 0.24]
    results = [dd_budget_scalar(d) for d in vals]
    for i in range(len(results) - 1):
        assert results[i] >= results[i + 1], f"not monotonic at {i}"


def test_convex_when_scalar_gt_1() -> None:
    s3_05 = dd_budget_scalar(0.05, scalar=3.0)
    s3_20 = dd_budget_scalar(0.20, scalar=3.0)
    s2_05 = dd_budget_scalar(0.05, scalar=2.0)
    s2_20 = dd_budget_scalar(0.20, scalar=2.0)
    assert s3_05 > s2_05, "scalar=3 should be gentler at small DD"
    assert s3_20 > s2_20, "higher scalar stays closer to 1.0 at all DDs below max"


def test_between_zero_and_one() -> None:
    for i in range(1, 25):
        s = dd_budget_scalar(i / 100.0)
        assert 0.0 <= s <= 1.0


def test_custom_max_dd() -> None:
    assert dd_budget_scalar(0.0, max_dd=0.5) == 1.0
    assert dd_budget_scalar(0.5, max_dd=0.5) == 0.0
    assert dd_budget_scalar(0.25, max_dd=0.5) > 0.0


def test_custom_scalar_one() -> None:
    assert math.isclose(dd_budget_scalar(0.125, scalar=1.0), 0.5, rel_tol=1e-3)


def test_very_small_dd() -> None:
    assert dd_budget_scalar(1e-10) == 1.0


def test_dd_just_below_max() -> None:
    val = dd_budget_scalar(0.2499, max_dd=0.25)
    assert 0.0 < val < 1.0
