from __future__ import annotations

import numpy as np
from pandas import Series


def vol_target_position(
    equity: float,
    price: float,
    annualized_vol: float,
    vol_target: float = 0.20,
    max_leverage: float = 3.0,
) -> float:
    risk_budget_dollars = equity * vol_target / annualized_vol
    capped_notional = min(risk_budget_dollars, equity * max_leverage)
    return capped_notional / price


def estimate_volatility(
    returns: Series,
    window: int = 21,
    periods_per_year: float = 8760.0,
    vol_target: float = 0.20,
    vol_floor: float = 0.05,
) -> float:
    if len(returns) < 2:
        return vol_target
    effective_window = min(window, len(returns))
    if effective_window < 2:
        return vol_target
    std = float(returns.tail(effective_window).std())
    annualized = std * np.sqrt(periods_per_year)
    return float(max(annualized, vol_floor))
