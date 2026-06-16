# ZTB-2250 Frozen Contract: Strategy Evaluation with `--start`

## Root Cause

When `--start` is used, `load()` returns data sliced from that point. The strategy's warmup (e.g., `sma_cross` `warmup=20`) and the engine's signal shift (`shift(1, fill_value=0.0)`) combined with `shifted.iloc[:warmup] = 0.0` can zero ALL signals if the sliced data is shorter than `strategy.warmup + 1`. No error or warning is raised — 0 trades, 0 risk_decisions silently produced.

Affected paths:
- `run_backtest` — no backward extension for warmup
- `run_forwardtest` — no backward extension for warmup  
- `Executor._compute_target_position` — returns `0.0` without calling `generate_signals` when `len(data) <= strategy.warmup`

## Contract Invariants (must be validated by test)

1. **Backward extension**: BEFORE calling `strategy.generate_signals(data)`, the engine MUST extend `data` backwards by at least `strategy.warmup` bars when `--start` is the reason for the data's left edge. The executor already does this via `_ensure_warmup` (line 894–926 of executor.py). `run_backtest` (backtest.py) and `run_forwardtest` (forwardtest.py) MUST gain analogous extension.

2. **No look-ahead**: Extended data (before the user-specified `--start`) is used ONLY for indicator computation. Signals in the warmup region are zeroed by `shifted.iloc[:strategy.warmup] = 0.0` — no trade enters the evaluation window from before `--start`.

3. **Equity invariant**: `equity = initial_cash + realized_pnl + unrealized_pnl` — never notional. The fix must not change how PnL is computed (`engine/pnl.py`), only the data window passed to `generate_signals`.

4. **Fee + slippage invariant**: `commission` and `slippage` applied in `single_symbol_portfolio` / `PnLCalculator.apply_fill` must be unchanged.

5. **Risk decision invariant**: Every bar processed MUST produce a `RiskDecision` when `risk_enabled=True`. Zero-signal bars produce decisions too (action `none`); the number of risk_decisions must equal `len(data)` after extension.

6. **Warmup guards unchanged**: `signals.iloc[:strategy.warmup].abs().max() > 1e-10` must still detect warmup violations. Backward-extended data must not break this guard.

## Required pytest Cases

All tests use `sma_cross` (warmup=20, slow=20) as the reference strategy:

1. `test_backtest_with_start_has_trades` — `run_backtest(sma_cross, data[start:], cfg)` where `len(data[start:]) == 44`. Assert `num_trades >= 1`, `len(risk_decisions) == len(data[start:])`. (Baseline.)

2. `test_backtest_with_start_too_short_raises_or_warns` — `run_backtest(sma_cross, data[start:], cfg)` where `len(data[start:]) == 13` (< warmup). The engine MUST raise `ValueError` or log a warning; no silent 0-trade.

3. `test_backtest_with_start_and_risk_enabled` — Same as test 1 with `risk_enabled=True`. Assert `risk_decisions` list has length == number of bars *after backward extension* that are evaluated (NOT the raw input data length).

4. `test_forwardtest_with_start_has_trades` — `run_forwardtest(sma_cross, data[start:], ForwardtestConfig(...))` where `len(data[start:]) == 44`. Assert `metrics.num_trades >= 1`, `len(risk_decisions) == len(data[start:])`.

5. `test_forwardtest_with_start_warmup_halved_when_too_large` — `run_forwardtest(sma_cross, data[start:], cfg)` with very short data (e.g., 20 bars). Assert `warmup_bars == len(data) // 2` and no crash.

6. `test_executor_compute_target_with_start_data` — Executor `_compute_target_position` on data sliced by `--start`. Assert the strategy's `generate_signals` IS called (not silently skipped). Assert returned signal is 1.0 when `fast > slow`.

7. `test_executor_with_start_dry_run_has_orders` — Full `Executor.run()` in dry-run mode with `--start` data. Assert `bars_processed > 0`, `current_position > 0` (signal was acted on), and `status == "completed"`.

8. `test_executor_with_start_risk_decisions_produced` — Same as test 7 but with `risk_enabled=True`. Assert risk decisions recorded in `exec_run_state.errors` (or accessible side channel).

9. **Equity no-inflation**: The fix must not regress on the equity = cash + rPnL + uPnL invariant (test in `test_executor_equity_no_inflation`, `test_executor_equity_short_position_no_inflation`).

10. **No CI regression**: All existing tests pass (`pytest tests/` — at minimum `test_backtest.py`, `test_forwardtest.py`, `test_execution_executor.py`, `test_risk_backtest.py`, `test_risk_forwardtest.py`).
