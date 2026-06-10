# Changelog

## v0.7.0 (2026-06-10)

- M6 Execution Module (DEMO): `ztb/execution/` (models, bybit_client, idempotency, reconcile, executor)
- BybitClient: signed REST v5 client, demo URL hard-pinned (`api-demo.bybit.com`), `--mode=live` blocked via `LiveModeBlockedError`
- Idempotency: `orderLinkId` from stable tuple `(strategy, symbol, bar_ts, intent_hash)` — NOT `run_id`; SQLite dedupe ledger prevents double-fill on restart
- Reconciler: `reconcile_account()` detects position drift between expected and actual exchange state
- Executor pipeline: closed-bar → signal → risk gate (M5) → diff → round → idempotent place → persist
- Store migration v4: `exec_runs`, `exec_orders`, `exec_fills`, `exec_positions_snapshots`, `exec_pnl_ledger`, `exec_errors` tables
- CLI: `ztb run <strategy> <symbol> [--mode demo] [--dry-run] [--once]`, `ztb reconcile [--exec-run-id]`
- Docs: `docs/m6_execution.md` (architecture, idempotency design, CLI reference)
- **Tests:** 517/517 pass, 91.72% coverage, ruff/mypy clean, secret scan clean, hermetic (mocked transport), signing golden vector, demo URL pin, `mode=LIVE` raises, idempotency replay safety, risk gate enforced, reconcile drift detection, executor happy path
- **Documentation:** `docs/m6_execution.md`
- **PR:** [#9](https://github.com/StaithValanthis/ztb/pull/9)
- **Merge commit:** `286c3ea` — two-key merge (CI green + V&R PASS on SHA `fb10d0c`)
- **Tag:** v0.7.0

## v0.6.0 (2026-06-10)

- M5 Risk Module: `ztb/risk/` (models, dd_budget, vol_sizing, heat, killswitch, manager)
- RiskManager.evaluate() pipeline: KillSwitch → Leverage → Position Size → Heat → DD Budget Scalar
- KillSwitch with HWM tracking, trip condition, cooldown, reset, serialization
- Vol-target position sizing with annualized vol estimation
- Correlation heat model with covariance-based portfolio std
- Store: schema migration v3 (risk_decisions table, runs risk columns)
- Scorecard: risk block (risk_aware, max_portfolio_dd_realized, kill_count, mean_gross_leverage)
- Backtest: risk integration via `--risk-enabled` flag (default OFF to preserve baselines)
- Forwardtest: risk integration enabled by default; `--no-risk` for A/B comparison
- **Tests:** 436/436 pass, 93% coverage, ruff/mypy clean, risk module tests, store migration tests, backtest/forwardtest integration, adversarial gap-down kill-switch proven
- **Documentation:** `docs/risk-module.md` (math spec + architecture)
- **Measured evidence (sma_cross, BTCUSDT, 60m, A/B via `ztb backtest --risk-enabled --persist` vs `--no-risk`):**
  No-risk baseline: Full Return -1.2612, Sharpe -0.394, MaxDD -1.1845, Trades 3,588
  Risk-aware:      Full Return +0.0673, Sharpe +0.190, MaxDD -0.2500, Trades 29,928
  **MaxDD reduction: 78.9%** (from -118% to -25%, capped at configured 25% DD budget)
- **PR:** [#8](https://github.com/StaithValanthis/ztb/pull/8)
- **Merge commit:** `149dd38` — two-key merge (CI green + V&R PASS on SHA `bf10ea1`)
- **Tag:** v0.6.0

## v0.5.0 (2026-06-10)

- M4 forward-test runner core: `engine/forwardtest.py` (ForwardtestConfig, ForwardtestResult, run_forwardtest)
- Decay formula: `engine/ft_decay.py` (DecayConfig, compute_decay_score, check_decay_alarm)
- Store: schema migration v2 (adds `run_type` column), `save_forward_run`, `list_forward_runs` accessors
- CLI: `ztb forwardtest <strategy> <symbol> [--cash] [--commission] [--slippage] [--warmup] [--persist] [--baseline-run-id]`
- Report command shows `run_type` column in listing
- Dashboard: run-type filter (All / Backtest / Forward), shows `run_type` in run info
- Reporting: `format_forwardtest_result` for forward-test output formatting
- **Tests:** 322/322 pass, 95% coverage, ruff/mypy clean, forwardtest/backtest parity proven, decay integration proven, dashboard forward-run display proven
- **Measured evidence (sma_cross, BTCUSDT, 60m, via `ztb forwardtest --persist`):** 3580 forward trades, Return -1.2617, Sharpe -0.394, MaxDD -1.1845, WinRate 17.7%, ProfitFactor 0.832
- **PR:** [#7](https://github.com/StaithValanthis/ztb/pull/7)
- **Merge commit:** `aad2e3e` — two-key merge (CI green + V&R PASS on SHA `5256049`)
- **Tag:** v0.5.0

## v0.4.0 (2026-06-10)

- M3 result store: `store/schema.sql` (additive, versioned), `store/results.py` (connect, save_run, accessors)
- M3 reporting: `reporting/scorecard.py` (score + grade A–D, 9 checks), `reporting/thresholds.py`, `reporting/format.py`
- M3 dashboard: `dashboard/app.py` (Streamlit, read-only, 127.0.0.1:8501), `dashboard/data_access.py`, `dashboard/components.py`
- CLI: `ztb backtest --persist` saves to store, `ztb report --run-id <id>`, `ztb report --scorecard`, `ztb dashboard`
- Dependency: `streamlit>=1.28` (optional `[dashboard]` extra)
- **Tests:** 265/265 pass, 95% coverage, determinism proven, credibility guard, cost-exactness round-trip, dashboard fail-soft
- **Measured evidence (sma_cross, 5000 bars, synthetic, via `ztb backtest --persist`):** 3588 trades, full return -1.2612 / Sharpe -0.394, IS return -0.3018 / Sharpe -0.354, OOS return -1.3741 / Sharpe -0.718, MaxDD -1.1845, WinRate 17.7%, ProfitFactor 0.831
- **PR:** [#6](https://github.com/StaithValanthis/ztb/pull/6)
- **Merge commit:** `5791d95` — two-key merge (CI green + V&R PASS on SHA `36683a7`)
- **Tag:** v0.4.0

## v0.3.0 (2026-06-10)

- M2 engine core: `features/indicators.py` (SMA, EMA, RSI, ATR, crossover)
- Plugin framework: `strategies/base.py` (Strategy ABC), `strategies/registry.py` (auto-discovery)
- Reference strategy: `strategies/sma_cross.py` (long-or-flat SMA crossover)
- Engine: `engine/backtest.py` (cost model, IS/OOS split, credible-sample guard)
- Metrics: `engine/metrics.py` (net Sharpe/Sortino/maxDD/trades/PF/winrate/turnover)
- Portfolio: `engine/portfolio.py` (minimal single-symbol passthrough)
- CLI: `ztb list`, `ztb backtest <strategy> <symbol>`
- **Tests:** 213/213 pass, 94% coverage, no-lookahead proven (T-B2), cost exactness (T-B1/T-B3), short flips proven
- **Documentation:** `docs/engine.md` (cost model, signal-timing, metric formulas)
- **Measured evidence (sma_cross, 5000 bars, synthetic):** 316 trades, full return 0.0004 / Sharpe 0.950, IS return 0.0006 / Sharpe 2.041, OOS return -0.0002 / Sharpe -1.578, MaxDD -0.0007, WinRate 18.0%, ProfitFactor 1.152
- **PR:** [#4](https://github.com/StaithValanthis/ztb/pull/4)
- **Merge commit:** `be3b888` — two-key merge (CI green + V&R PASS on SHA `f2b9d60`)
- **Tag:** v0.3.0

## v0.2.0 (2026-06-09)

- M1 data layer: ztb/data/ module (errors, schema, timeframes, rate_limit, bybit_rest, pagination, fetch, cache, integrity, loader)
- CLI: ztb data fetch|show|verify|instruments
- Dependencies: httpx, pandas, pyarrow
- **Tests:** all green, ≥90% coverage, cold==warm determinism proven, delta-fetch spy-proven
- **Merge commit:** 651d284 — two-key merge (CI green + V&R PASS on SHA 1a8250b)
- **Tag:** v0.2.0

## v0.1.1 (2026-06-09)

- CI fix: exclude `@pytest.mark.network` from default test run (unblocks M1 data layer testing)
- **PR:** [#3](https://github.com/StaithValanthis/ztb/pull/3)
- **Merge commit:** `02035ac` — admin-merge (MD-authorized, V&R PASS on SHA `e51f8b9`)

## v0.1.0 (2026-06-09)

- M0 scaffold: typed package skeleton, frozen Config, CLI dispatcher, pyproject.toml + pre-commit + CI
- **Tests:** 20/20 pass, 98% coverage
- **Merge commit:** 9cd35d5 — two-key merge (CI green + V&R PASS on SHA a709d6c)
