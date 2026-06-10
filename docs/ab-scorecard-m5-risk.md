# M5 Risk Module — A/B Scorecard

## Strategy: sma_cross (BTCUSDT 60m, fast=5, slow=20)

### No-Risk Baseline
- Run ID: `sma_cross_BTCUSDT_20260610T073940`
- Risk: OFF

| Scope | Return | Sharpe | MaxDD | Trades | Win% | PF |
|-------|--------|--------|-------|--------|------|----|
| FULL  | -1.2612 | -0.394 | -1.1845 | 3588 | 0.177 | 0.831 |
| IS    | -0.3018 | -0.354 | -0.5583 | 2524 | 0.177 | 0.923 |
| OOS   | -1.3741 | -0.718 | -1.3024 | 1064 | 0.179 | 0.731 |

### Risk-Aware
- Run ID: `sma_cross_BTCUSDT_20260610T074001`
- Risk: ON (default RiskConfig: max_portfolio_dd=0.25, account_killswitch_dd=0.25, vol_target=0.20)

| Scope | Return | Sharpe | MaxDD | Trades | Win% | PF |
|-------|--------|--------|-------|--------|------|----|
| FULL  | 0.0673 | 0.190 | -0.2500 | 29928 | 0.276 | 1.053 |
| IS    | 0.0674 | 0.228 | -0.2499 | 21088 | 0.279 | 1.053 |
| OOS   | -0.0001 | -0.589 | -0.0002 | 8840 | 0.269 | 0.804 |

### A/B Comparison

| Metric | No-Risk | Risk-Aware | Delta |
|--------|---------|------------|-------|
| Full Return | -1.2612 | +0.0673 | +1.3285 |
| Full Sharpe | -0.394 | +0.190 | +0.584 |
| Full MaxDD | -1.1845 | -0.2500 | **-78.9%** |
| IS MaxDD | -0.5583 | -0.2499 | **-55.2%** |
| OOS MaxDD | -1.3024 | -0.0002 | **-99.98%** |
| Full Trades | 3,588 | 29,928 | +734% |

### Conclusion
Risk module caps drawdown at the configured 25% budget (dd_budget_scalar + kill-switch). On this losing sma_cross strategy, risk-aware mode:
- Reduced FULL MaxDD by **78.9%** (from -118% to -25%)
- Capped OOS MaxDD at essentially 0% (kill-switch kept flattening)
- Generated more trades due to scaling in/out as DD budget fluctuated
- Both runs credible (≥30 trades on all segments)

The kill-switch flattened on gap-down risk and dd_budget_scalar scaled position size proportionally to remaining DD budget.
