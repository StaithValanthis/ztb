# Risk Module — Math & Architecture

## Overview

The risk layer enforces hard limits and soft scaling for every proposed trade.
It is the seatbelt before execution: all trades route through `RiskManager.evaluate()`
before the engine enters them into the portfolio cost model.

## Pipeline order (evaluate)

`KillSwitch` (hard floor) → `Leverage` (cap) → `Position Size` (cap) → `Heat` (multi-asset cap) → `DD Budget Scalar` (soft scaling)

1. **KillSwitch** — If current drawdown ≥ `account_killswitch_dd` (25%), return `(halt, 0, 0, 0)` immediately.
2. **Leverage** — If gross notional / equity > `max_leverage` (3.0), scale all positions down uniformly.
3. **Position Size** — If any single position > `max_position_pct` (50%) of equity, clip to the cap.
4. **Heat** — For multi-asset portfolios with covariance set: if portfolio heat √(wᵀΣw) > `max_heat` (1.0), reduce.
5. **DD Budget Scalar** — Scale max_notional by `1 − (current_dd / max_portfolio_dd)^power` where `power` = 3.0. This is a soft, continuous reduction — it does not halt.

## Components

### RiskConfig (`ztb/risk/models.py`)

| Field | Default | Description |
|-------|---------|-------------|
| `max_portfolio_dd` | 0.25 | DD threshold for scalar to reach 0 |
| `account_killswitch_dd` | 0.25 | DD threshold that triggers halt |
| `vol_target` | 0.20 | Annualised vol target |
| `max_leverage` | 3.0 | Gross notional / equity cap |
| `max_position_pct` | 0.50 | Single position as fraction of equity |
| `max_heat` | 1.0 | Portfolio heat cap |
| `max_correlation` | 0.80 | Weighted-average correlation cap |
| `dd_budget_scalar_power` | 3.0 | Exponent for DD budget formula |
| `cooldown_bars` | 100 | KillSwitch cooldown duration |
| `min_notional` | 5.0 | Min notional per order |
| `vol_lookback` | 21 | Volatility estimation window |
| `corr_lookback` | 21 | Correlation estimation window |
| `vol_floor` | 0.05 | Minimum annualised vol |
| `default_slippage` | 0.0005 | Slippage rate per trade |
| `default_commission` | 0.0005 | Commission rate per trade |

### KillSwitch (`ztb/risk/killswitch.py`)

- Tracks HWM (high-water mark) of equity.
- `check_trip(current_equity)` — trip if `(hwm − equity) / hwm ≥ account_killswitch_dd`.
  On trip: set `tripped=True`, start `cooldown_remaining = cooldown_bars`.
- `cooldown_tick()` — decrements `cooldown_remaining`; when it hits 0, calls `reset()`.
- `reset(equity)` — clear trip state, set HWM to equity.
- `flatten_signal(pos) → 0.0` — always returns 0 (halt = flatten-to-zero).
- Round-trip via `to_dict()` / `from_dict()`.

### DD Budget Scalar (`ztb/risk/dd_budget.py`)

```
dd_budget_scalar(current_dd, max_dd=0.25, scalar=3.0) → float
```

- `current_dd ≤ 0` → `1.0`
- `current_dd ≥ max_dd` → `0.0`
- Otherwise: `1.0 − (current_dd / max_dd)^scalar`

Properties:
- Monotonically decreasing
- At 12.5% DD / scalar=3: ~0.875
- Convex when scalar > 1 (gentler at small DD)

### Heat Model (`ztb/risk/heat.py`)

Portfolio heat = `√(wᵀ Σ w)`, where:
- `w` = portfolio weights (absolute notional proportions)
- `Σ` = covariance matrix of asset returns

- `rolling_correlation(returns, window=21)` — returns symmetric dict of pairwise correlations.
- `heat_cap_check(heat, max_heat)` — returns `(pass, msg)`.
- `correlation_check(weights, corr_matrix, max_corr)` — weighted-average pairwise correlation.

### Vol-Target Sizing (`ztb/risk/vol_sizing.py`)

```
vol_target_position(equity, price, annualized_vol, vol_target=0.20, max_leverage=3.0) → units
```

Risk budget $ = equity × vol_target / annualized_vol
Capped notional = min(risk_budget, equity × max_leverage)
Units = capped_notional / price

```
estimate_volatility(returns, window=21, periods_per_year=8760, vol_target=0.20, vol_floor=0.05) → float
```

Uses rolling std × √(periods_per_year) with minimum floor.

### Portfolio (`ztb/risk/portfolio.py`)

- `risk_adjusted_signals(signals, close, risk_manager, ...)` — runs signal series through RiskManager, adjusting each bar. Returns adjusted Series, decisions list, and equity values.
- `multi_symbol_portfolio(signals, closes, ...)` — multi-symbol portfolio simulation with per-bar P&L and cost accounting.

## Store Schema

Migration v3 adds:
- `risk_decisions` table: decision_id, run_id (FK), timestamp, symbol, action (proceed/reduce/halt), reason, max_pos_size, max_leverage, max_notional, current_dd, current_heat, hwm
- `runs` columns: risk_aware, max_portfolio_dd_realized, kill_count, mean_gross_leverage

## Scorecard Risk Block

Scorecard includes a `risk` block with:
- `risk_aware` — whether risk was enabled
- `max_portfolio_dd_realized` — peak-to-trough DD during run
- `kill_count` — number of kill-switch halts
- `mean_gross_leverage` — average gross leverage
