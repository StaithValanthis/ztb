from __future__ import annotations

import math

import numpy as np
import pandas as pd

from ztb.risk.vol_sizing import estimate_volatility, vol_target_position


def test_vol_target_position_basic() -> None:
    units = vol_target_position(
        equity=100_000.0,
        price=50000.0,
        annualized_vol=0.40,
        vol_target=0.20,
        max_leverage=3.0,
    )
    risk_budget = 100_000.0 * 0.20 / 0.40
    expected = risk_budget / 50000.0
    assert math.isclose(units, expected, rel_tol=1e-9)


def test_vol_target_respects_max_leverage() -> None:
    units = vol_target_position(
        equity=100_000.0,
        price=50000.0,
        annualized_vol=0.05,
        vol_target=0.20,
        max_leverage=3.0,
    )
    capped_notional = 100_000.0 * 3.0
    expected = capped_notional / 50000.0
    assert math.isclose(units, expected, rel_tol=1e-9)


def test_vol_target_higher_vol_smaller_position() -> None:
    pos_low_vol = vol_target_position(100_000.0, 50000.0, 0.20)
    pos_high_vol = vol_target_position(100_000.0, 50000.0, 0.80)
    assert pos_low_vol > pos_high_vol


def test_vol_target_zero_equity() -> None:
    units = vol_target_position(0.0, 50000.0, 0.40)
    assert units == 0.0


def test_estimate_volatility_basic() -> None:
    np.random.seed(42)
    returns = pd.Series(np.random.normal(0.0, 0.01, 100))
    vol = estimate_volatility(returns, window=21, periods_per_year=8760.0)
    assert 0.05 <= vol <= 5.0


def test_estimate_volatility_floor() -> None:
    returns = pd.Series([0.0] * 100)
    vol = estimate_volatility(returns, window=21, periods_per_year=8760.0)
    assert vol >= 0.05


def test_estimate_volatility_short_history() -> None:
    returns = pd.Series([0.01])
    vol = estimate_volatility(returns, window=21, periods_per_year=8760.0)
    assert vol == 0.20


def test_estimate_volatility_empty() -> None:
    returns = pd.Series([], dtype=float)
    vol = estimate_volatility(returns, window=21, periods_per_year=8760.0)
    assert vol == 0.20


def test_estimate_volatility_two_points() -> None:
    returns = pd.Series([0.01, -0.01])
    vol = estimate_volatility(returns, window=21, periods_per_year=8760.0)
    assert 0.05 <= vol < 10.0


def test_vol_target_position_high_leverage_allows_larger() -> None:
    low = vol_target_position(100_000.0, 50000.0, 0.40, max_leverage=1.0)
    high = vol_target_position(100_000.0, 50000.0, 0.40, max_leverage=5.0)
    assert high >= low


def test_estimate_volatility_custom_periods() -> None:
    returns = pd.Series(np.random.normal(0.0, 0.01, 100))
    vol_daily = estimate_volatility(returns, window=21, periods_per_year=365.0)
    vol_hourly = estimate_volatility(returns, window=21, periods_per_year=8760.0)
    assert vol_hourly > vol_daily


def test_estimate_volatility_custom_vol_floor() -> None:
    returns = pd.Series([0.0] * 100)
    vol = estimate_volatility(returns, window=21, periods_per_year=8760.0, vol_floor=0.10)
    assert vol == 0.10


def test_estimate_volatility_window_too_small() -> None:
    returns = pd.Series([0.01, -0.01, 0.02, -0.02, 0.01])
    vol = estimate_volatility(returns, window=1, periods_per_year=8760.0)
    assert vol == 0.20


def test_estimate_volatility_returns_float() -> None:
    returns = pd.Series(np.random.normal(0.0, 0.01, 50))
    vol = estimate_volatility(returns)
    assert isinstance(vol, float)
