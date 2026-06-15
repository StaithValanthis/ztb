# Changelog

## v1.1.14 (2026-06-15)

- **Fix(validation):** DEFECT 1-3 — thread actual `cash`, `commission`, `slippage` params through walk-forward harness (were hardcoded to `0.0`/`0`/`0.0`). Fix ruff-format trailing blank lines in `walk_forward.py`.
- **Tests:** New test for threaded params in walk-forward — 21 lines added to `test_validation_walkforward.py`. CI + vr-pass SUCCESS on SHA `0b75e34`.
- **PR:** [#85](https://github.com/StaithValanthis/ztb/pull/85) — `feat/validation-package`
- **Merge commit:** `24d5da3` — two-key merge (CI green + vr-pass SUCCESS on SHA `0b75e34`)
- **Tag:** v1.1.14

## v1.1.12 (2026-06-15)

- **Fix(exec):** Size against actual wallet balance, verify top-up with `TopUpResult`/wallet read-back, backoff on `'ab not enough'` (ClientError) — skip bar, no retry. Wallet fetch failure skips bar (no fallback to PnLCalculator). Uses per-coin `available_balance * max_leverage` for order sizing instead of `equity` alone. DEMO equity cap preserved outside the wallet-fetch try/except.
- **Tests:** 7 new tests (`test_top_up_demo_account_verifies_balance`, `test_top_up_demo_account_faucet_cap`, `test_top_up_demo_account_fails_gracefully`, `test_executor_wallet_fetch_failure_skips_bar`, `test_executor_sizes_against_available_balance`, `test_executor_ab_not_enough_backoff`, `test_executor_instrument_bounds_enforced`) plus update `test_demo_mode_equity_cap_when_wallet_fetch_fails` — 144/144 pass, ruff/mypy clean
- Merge authorization: [ZTB-1735](/ZTB/issues/ZTB-1735) (MD authorized)
- **PR:** [#83](https://github.com/StaithValanthis/ztb/pull/83) — `feat/ab-not-enough-fix`
- **Merge commits:** `7571325` (conflict resolution), `5c6a247` (two-key merge via PR #87)
- **Tag:** v1.1.12

## v1.1.11 (2026-06-15)

- **Fix(exec):** DEMO mode equity cap — cap wallet equity at `initial_cash` to prevent accumulated demo top-ups from inflating position sizing. Also uses account-level `totalAvailableBalance` instead of per-coin `availableBalance` for order qty cap. Changed `ExecRunConfig.slippage` default from `0.0` to `0.0005`.
- **Bugfix:** Move DEMO equity cap outside try/except block — when `get_wallet_balance()` raised, the cap was silently bypassed, leaving equity uncapped.
- **Tests:** 2 new tests (`test_demo_mode_equity_cap_when_wallet_exceeds_initial_cash`, `test_demo_mode_equity_cap_when_wallet_fetch_fails`) — 892/892 pass both 3.11/3.13, 93% coverage, ruff/mypy clean
- V&R PASS on SHA `d0d9092` ([ZTB-1689](/ZTB/issues/ZTB-1689), [ZTB-1691](/ZTB/issues/ZTB-1691))
- Merge authorization: [ZTB-1701](/ZTB/issues/ZTB-1701) (MD approved)
- **PR:** [#71](https://github.com/StaithValanthis/ztb/pull/71) — `fix/ztb-1545-demo-mode-equity-cap`
- **Merge commit:** `c257a20` — two-key merge (CI green + V&R PASS on SHA `d0d9092`)
- **Tag:** v1.1.11

## v1.1.10 (2026-06-15)

- **[Board][CRITICAL][C3/C4]** Build real OOS validation infra: walk-forward harness with enforced train/test split (forward window after dev window), Deflated Sharpe/PSR (Bailey & Lopez de Prado, n_trials/skew/kurtosis, Lo 2002 EVT max dist for n>1), look-ahead tripwire (Mode 1 frame check — corrupts last-bar OHLCV on detected leakage), 8-criteria binary scoring (accept/reject), `ztb validate <strategy> <symbol>` canonical CLI gate with exit codes 0/1/2. Store schema v10: `run_id` PK, validation results table. Replaces all prior stubs.
- **Tests:** 9 new validation test modules (DSR, look-ahead, scoring, store, walk-forward, CLI) — 941 tests pass both 3.11/3.13, ≥90% validation coverage, ruff/mypy clean
- V&R PASS on SHA `1bb003a` ([ZTB-1643](/ZTB/issues/ZTB-1643)); vr-pass CI on final SHA `0dfc43e` also PASS
- Merge authorization: [ZTB-1660](/ZTB/issues/ZTB-1660) (MD approved)
- **PR:** [#76](https://github.com/StaithValanthis/ztb/pull/76) — `feat/validation-package`
- **Merge commit:** `d8caf2a` — two-key merge (CI green + V&R PASS)
- **Tag:** v1.1.10

## v1.1.9 (2026-06-14)

- **Fix(strat):** D3 fix — `bearish_resumption` 1h-native redesign: timeframe `240`→`60`, warmup `300`→`1200`, remove synthetic `df.resample("1h").ffill()` block, compute 4h indicators via genuine `df.resample("4h")` on 1h data, remove dead loader mocks from tests, update test fixtures to 1h frequency (warmup=1200)
- **Tests:** 10 required bearish_resumption tests + all existing tests pass both 3.11/3.13, ruff/mypy clean
- V&R PASS on SHA `3ceb797` ([ZTB-1408](/ZTB/issues/ZTB-1408), [ZTB-1410](/ZTB/issues/ZTB-1410))
- Merge authorization: [ZTB-1411](/ZTB/issues/ZTB-1411) (MD approved)
- **PR:** [#61](https://github.com/StaithValanthis/ztb/pull/61) — `strat/bearish_resumption`
- **Merge commit:** `e313547` — two-key merge (CI green + V&R PASS on SHA `3ceb797`)
- **Tag:** v1.1.9

## v1.1.8 (2026-06-14)

- **[Board][CRITICAL][C1] Fix(exec):** Replace synthetic fills with real exchange executions — `_step_impl()` now calls `get_executions()` after `place_order()` to fetch real fill data, persists to `exec_fills` table, derives PnL from real fill prices (slippage=0 with real fills), records assumed-vs-actual reconciliation metric (`price_divergence`, `qty_divergence`). Schema v9: rename `credible` → `sufficient_sample` across all exec + results tables + reporting/CLI. Fallback to synthetic on API error with `_save_error()`.
- **Tests:** 15 new fill-pipeline tests + updated credible→sufficient_sample tests — 895/895 pass both 3.11/3.13, 93% coverage, ruff/mypy clean
- V&R PASS on SHA `0f5b18d` ([ZTB-1568](/ZTB/issues/ZTB-1568), [ZTB-1577](/ZTB/issues/ZTB-1577))
- **PR:** [#72](https://github.com/StaithValanthis/ztb/pull/72) — `feat/real-fill-pipeline`
- **Merge commit:** `45c37ec` — two-key merge (CI green + V&R PASS on SHA `0f5b18d`)
- **Tag:** v1.1.8

## v1.1.7 (2026-06-14)

- **Fix(exec):** Add `PollingError(ExecutionError)` exception class — raise in DEMO polling loop after 3 consecutive step failures, catch gracefully in `run()`
- **Tests:** 3 new tests (class_exists, raises_on_max_errors, sigterm_no_polling_error) + 1 updated (test_polling_loop_error_retry_then_stop) — 873/873 pass both 3.11/3.13, 92.49% coverage, ruff/mypy clean
- V&R PASS on SHA `067c1c1` ([ZTB-1442](/ZTB/issues/ZTB-1442))
- **PR:** [#65](https://github.com/StaithValanthis/ztb/pull/65) — `fix/polling-error-class`
- **Merge commit:** `f5d1971` — two-key merge (CI green + V&R PASS on SHA `067c1c1`)
- **Tag:** v1.1.7

## v1.1.6 (2026-06-14)

- **Fix(arm):** Remove CLI-level `LiveGuard.is_armed()` check from `ztb run` — arm enforcement moved to `BybitClient` (execution layer) per M7 design, aligning with disarmed-by-default invariant
- **Test:** `test_run_accepts_live_mode` updated — no `LiveGuard.arm()`/`disarm()`, uses `--db=:memory:` for isolation
- Conflict resolution: rebased over main commit `7349bd7` (which added `_setup_arm`/`_cleanup_arm` helpers) — Platform Engineer's approach wins (LiveGuard belongs in execution layer, not CLI)
- **Tests:** 213/213 pass, ruff/mypy clean
- V&R PASS on SHA `989d0b4` ([ZTB-1450](/ZTB/issues/ZTB-1450), [ZTB-1454](/ZTB/issues/ZTB-1454))
- **PR:** [#64](https://github.com/StaithValanthis/ztb/pull/64) — `feat/ztb-1266-arm-security-fix`
- **Merge commit:** `db8c689` — two-key merge (CI green + V&R PASS on SHA `989d0b4`)
- **Tag:** v1.1.6

## v1.1.5 (2026-06-14)

- **Feat(exec):** Demo account auto top-up — `BybitClient.top_up_demo_account()` calls POST `/v5/account/demo-apply-money` on every DEMO run start, resetting USDT balance to `initial_cash` (default 100,000) to prevent "ab not enough for new order" exhaustion
- **Feat(exec):** `reduce_only` flag on positional reduces — executor sets `reduce_only=True` when `delta < 0 && position > 0` (sell to reduce long) or `delta > 0 && position < 0` (buy to reduce short), avoiding margin on opposite-side opens
- **Fix(exec):** Top-up failure is non-fatal — logs `DemoAccountTopUpError` to `exec_errors` and continues run; dry-run and LIVE modes skip top-up entirely
- **Tests:** 10 new pytest cases (3 `top_up_demo_account` API + guards + failure; 4 executor run-mode guards + failure; 3 `reduce_only` logic) — 127/127 execution tests pass; 836/836 full suite pass
- Coverage: executor 86%, bybit_client 47% (new method), total 92%
- V&R PASS on SHA `b3bdc9b` ([ZTB-1421](/ZTB/issues/ZTB-1421), [ZTB-1417](/ZTB/issues/ZTB-1417))
- **PR:** [#63](https://github.com/StaithValanthis/ztb/pull/63) — `feat/ztb-1417-demo-exec-loop-fix`
- **Merge commit:** `d9f07e7` — two-key merge (CI green + V&R PASS on SHA `b3bdc9b`)
- **Tag:** v1.1.5

## v1.1.4 (2026-06-14)

- **Fix(exec):** Reconcile adoption no longer overwrites configured `initial_cash` with wallet balance — `initial_cash` stays at the `--cash` config value, equity remains `initial_cash(configured) + realized_pnl + unrealized_pnl`
- **Tests:** 3 new executor tests (reconcile adoption does not overwrite initial_cash, preserves configured cash, still adopts position) + 1 updated — 78/78 executor tests pass; 836/836 full suite pass
- Coverage: executor 86%, pnl.py 95%, reconcile.py 78% (92% total)
- V&R PASS on SHA `f22440c` ([ZTB-1382](/ZTB/issues/ZTB-1382), [ZTB-1386](/ZTB/issues/ZTB-1386), [ZTB-1383](/ZTB/issues/ZTB-1383))
- **PR:** [#58](https://github.com/StaithValanthis/ztb/pull/58) — `fix/reconcile-cash`
- **Merge commit:** `3e193b6` — two-key merge (CI green + V&R PASS on SHA `f22440c`)
- **Tag:** v1.1.4

## v1.1.3 (2026-06-13)

- **Fix(exec):** Use actual Bybit wallet balance for equity calculation — each run now fetches real `wallet_balance`/`total_equity` instead of fresh PnLCalculator($100), eliminating "ab not enough for new order" rejections on demo account with prior PnL
- **Fix(exec):** Graceful `ClientError` handling in `step()` — returns skipped result instead of crashing, enabling `--mode demo --loop` to survive transient API errors (40 such errors in 6h outage resolved)
- **Fix(exec):** Warmup reconciliation adopts actual wallet balance — `initial_cash` calibrated to `actual_equity - unrealized_pnl` so subsequent `equity()` calls reflect real account state
- **Fix(exec):** `--loop` mode continuity — state tracked correctly on skipped/killswitch early returns; signal init moved before order placement
- **Fix(engine):** `PnLCalculator.set_initial_cash()` — new method to update starting equity in place for warmup sync
- **Fix(reconcile):** `ReconcileReport.actual_wallet_balance` / `actual_equity` — carry Bybit account state through reconciliation for warmup adoption
- **Tests:** 11 new executor tests (wallet balance adoption, ClientError→skipped, polling loop resilience, results.db path) — 75/75 executor tests pass; 833/833 full suite pass
- Coverage: executor 86%, pnl.py 95%, reconcile.py 78% (92% total)
- V&R PASS on SHA `5a57c8d` ([ZTB-1286](/ZTB/issues/ZTB-1286), [ZTB-1348](/ZTB/issues/ZTB-1348))
- **PR:** [#56](https://github.com/StaithValanthis/ztb/pull/56) — `feat/fix-executor-wallet`
- **Merge commit:** `2ef3d92` — two-key merge (CI green + V&R PASS on SHA `5a57c8d`)
- **Tag:** v1.1.3

## v1.1.2 (2026-06-13)

- **Fix(exec):** Trade only on signal change — executor skips fill when position/signal/edge unchanged, reducing unnecessary churn
- **Fix(exec):** Startup reconciliation — `ReconcileEngine.load_state` restores active position + accrued costs on warm start, enabling continuity across `ztb run` restarts
- **Feat(pnl):** `PnLCalculator.adopt_state` — restore PnL state from persisted data (position, avg price, realized PnL, open costs) for startup reconciliation
- **Tests:** 112 executor+PnL tests pass (trade-on-signal-change: skipped fill paths, flip from flat, flip from opposing; startup reconciliation: warm start restores position, cold start begins flat, open-cost carry-over, cross-session equity identity)
- Coverage: 92% total (822 tests)
- V&R PASS on SHA `359ae17` ([ZTB-1285](/ZTB/issues/ZTB-1285))
- **PR:** [#52](https://github.com/StaithValanthis/ztb/pull/52) — `feat/ztb-1285-demo-over-trade-fix`
- **Merge commit:** `01a5d06` — two-key merge (CI green + V&R PASS on SHA `359ae17`)
- **Tag:** v1.1.2

## v1.1.0 (2026-06-13)

- **Feat(demo-exec):** Continuous polling loop with SIGTERM handling, 3-retry, killswitch integration — `ztb run --loop` / `--poll-interval` / `--lookback-bars`
- **Feat(bybit-client):** `get_instrument_info`, `round_to_step`, `minOrderQty`/`maxOrderQty` validation
- **Fix(DEFECT-1):** `_step_impl` skipped-order `UnboundLocalError` — early return on skip, no cost on skipped order
- **Fix(DEFECT-2):** Competing SIGTERM handlers consolidated
- **Fix(CI):** vr-pass runs on PR events as required status check
- **Tests:** 59 executor tests pass (3.11/3.13 matrix); skipped-order path coverage; 179 new bybit_client tests, 119 revised CLI tests
- Coverage: 92% total (executor 86%, bybit_client 93%, CLI 86%)
- V&R PASS on SHA `807e306` ([ZTB-1212](/ZTB/issues/ZTB-1212))
- **PR:** [#39](https://github.com/StaithValanthis/ztb/pull/39) — `feat/demo-execution-loop`
- **Merge commit:** `2eda279` — two-key merge (CI green + V&R PASS on SHA `807e306`)
- **Tag:** v1.1.0

## v1.0.9 (2026-06-13)

- **Fix(pnl-calculator):** Resolve 3 V&R-defects on `feat/pnl-calculator` — signed cash formula (no `abs(position)`), costs on bar 0, costs in dry_run path
- **Fix(executor):** dry_run path passes commission+slippage to `PnLCalculator.apply_fill()` (DEFECT-3)
- **Fix(engine/portfolio):** `single_symbol_portfolio` cash uses signed `position` (DEFECT-1); first-bar trades incur costs (DEFECT-2)
- **Fix(risk/portfolio):** `risk_adjusted_signals` and `multi_symbol_portfolio` apply costs on bar 0
- **Refactor(engine):** Extract `PnLCalculator` from inline avg-price/UPnP logic in executor, engine portfolio, risk portfolio — single shared PnL primitive with fees+slippage (E5 shared accounting)
- **Refactor(executor):** Remove `_update_avg_entry_price`, `_compute_unrealized_pnl`, delegating to `PnLCalculator` via `apply_fill()` + `_sync_pnl_state()`
- **Tests:** 3 new V&R gap-detection tests (`test_short_open_position_cash_identity`, `test_first_bar_signals_skip_costs`, `test_executor_dry_run_no_costs`); 783 total tests pass, 0 fail, 93% coverage; PnLCalculator 100% coverage
- V&R PASS on SHA `da5fb44` ([ZTB-1037](/ZTB/issues/ZTB-1037))
- **PR:** [#36](https://github.com/StaithValanthis/ztb/pull/36) — `feat/pnl-calculator`
- **Merge commit:** `bea8d26` — two-key merge (CI green + V&R PASS on SHA `da5fb44`)
- **Tag:** v1.0.9

## v1.0.8 (2026-06-13)

- **Tests(vr-pass-bridge):** Add comprehensive T1–T12 test suite + notify-mode tests for `scripts/ztb-vr-pass-bridge.py`
- **Tests:** Covers PASS/FAIL outcomes vs CI states (green/red/pending), gh CLI error handling (not found, API error, non-JSON, timeout), git remote URL parsing (HTTPS, SSH), self-filter (ztb/vr-pass excluded from CI conclusion), and notify mode
- **Tests:** 17 bridge-specific tests; 723 total tests collected
- V&R PASS on SHA `70ba5e8` ([ZTB-1008](/ZTB/issues/ZTB-1008))
- **PR:** [#19](https://github.com/StaithValanthis/ztb/pull/19) — `feat/vr-pass-bridge`
- **Merge commit:** `9330cc4` — two-key merge (CI green + V&R PASS on SHA `70ba5e8`)
- **Tag:** v1.0.8

## v1.0.7 (2026-06-13)

- **Feat(sizing):** Unify backtest-executor position sizing to fraction-of-equity convention (`target_qty = target_frac * equity / price`) — signals in both environments now produce identical position quantities
- **Feat(portfolio):** `single_symbol_portfolio` and `multi_symbol_portfolio` compute pre-trade equity, convert fraction to target qty, apply costs on delta basis
- **Feat(executor):** `_apply_risk` computes `target_qty = target_signal * equity / price`; reduce path uses fraction-of-equity scale
- **Feat(risk):** `risk_adjusted_signals` converts internally to qty for risk evaluation, outputs fractions
- **Feat(backtest/forwardtest):** Leverage calculation uses `abs(sig)` (fraction) instead of `abs(sig) * price / eq`
- **Tests:** 7 new fraction-of-equity tests (`test_fraction_of_equity_trade_size`, `test_fraction_of_equity_equity_consistency`, `test_fraction_multi_symbol`, `test_fraction_multi_symbol_exact_sizing`, `test_fraction_multi_symbol_flip`, `test_fraction_zero_signal_no_trade`, `test_fraction_full_leverage`); portfolio.py coverage 53% → 93%
- 711 total tests passed, 92.74% coverage
- V&R PASS on SHA `6cb6c7f` ([ZTB-878](/ZTB/issues/ZTB-878))
- **PR:** [#33](https://github.com/StaithValanthis/ztb/pull/33) — `feat/sizing-unification`
- **Merge commit:** `f827eb9` — two-key merge (CI green + V&R PASS on SHA `6cb6c7f`, rebased same diff)
- **Tag:** v1.0.7

## v1.0.6 (2026-06-13)

- **Feat(vr-pass-bridge):** Add `--mode notify` for CI-on-push path (posts pending status, no auto-PASS)
- **Feat(vr-pass-bridge):** `--outcome` is optional (only required with `--mode outcome`); default is `--mode outcome` for backward compat
- **Ci:** `vr-pass` job uses `--mode notify` instead of `--outcome PASS` — no commit reaches main with auto-PASS
- **Tests:** Conftest-based bridge tests; 5 tests covering notify mode, outcome PASS/FAIL, and graceful gh absence
- **Docs:** Updated `vr-pass-bridge.md` with notify mode usage
- V&R PASS on SHA `8379f29836ab` ([ZTB-883](/ZTB/issues/ZTB-883))
- **PR:** [#32](https://github.com/StaithValanthis/ztb/pull/32) — `feat/vr-pass-fix`
- **Merge commit:** `1f59beb` — two-key merge (CI green + V&R PASS on SHA `8379f29836ab`)
- **Tag:** v1.0.6

## v1.0.6 (2026-06-13)

- **Feat(security):** HMAC-SHA256 board token verification via `arm_auth.py` — `load_arm_hash`, `compute_arm_hash`, `verify_board_token`
- **Feat(security):** `LiveGuard.BOARD_TOKEN_VAR` (`ZTB_BOARD_TOKEN`) — token verification on `arm()`, refuses arm on hash mismatch
- **Feat(security):** `LiveArmFailedError` for token verification failures
- **Feat(security):** Tamper-evident `audit_log` table (schema v8) with SHA-256 hash chain — `ensure_audit_table`, `log_audit_event`, `get_audit_log`, `verify_audit_chain`
- **Feat(security):** `BybitClient` live mode writes audit log row on successful API calls
- **Tests:** 18 new arm_auth/LiveGuard token tests; 6 new audit log chain tests; 724 total passed, 91% coverage
- Version bumped to 1.0.6
- **Branch:** `feat/ztb-852-arm-security`

## v1.0.5 (2026-06-13)

- **Feat(killswitch):** Persist LiveKillSwitch state (HWM equity, tripped flag, last heartbeat) so process restart preserves safety invariant
- **Feat(killswitch):** `_hwm_equity` on restore = max(persisted HWM, current equity) — never resets to zero on restart
- **Feat(executor):** Persist killswitch state on every heartbeat and every trip; restore on LIVE start
- **Feat(live_guard):** `arm(conn=...)` fail-closed — refuses to arm if unresolved kill_event exists in store
- **Feat(preflight):** `_check_killswitch_durability()` verifies no unresolved trips before run
- **Feat(store):** `killswitch_state` table (schema v7), `save_killswitch_state`, `load_killswitch_state`, `get_latest_unresolved_kill_event`
- **Feat(errors):** `LiveDisarmedError` accepts custom message for fail-closed arm
- **Tests:** 5 new killswitch durability tests; 704 total passed, 97% coverage
- V&R PASS on SHA `7d1325a` ([ZTB-788](/ZTB/issues/ZTB-788), [ZTB-791](/ZTB/issues/ZTB-791))
- **PR:** [#29](https://github.com/StaithValanthis/ztb/pull/29) — `feat/m7-killswitch-durability`
- **Merge commit:** `df5115e` — two-key merge (CI green + V&R PASS on SHA `7d1325a`)
- **Tag:** v1.0.5

## v1.0.4 (2026-06-13)

- **Fix:** Replace hardcoded `"1.0.0"`/`"0.7.0"` with `ztb.__version__` in `executor.py` and `results.py` so `code_version` auto-updates on version bumps
- **Tests:** 702 passed, 91.88% coverage — no regressions
- V&R PASS on SHA `91e513c` ([ZTB-835](/ZTB/issues/ZTB-835))
- **PR:** [#30](https://github.com/StaithValanthis/ztb/pull/30) — `feat/fix-code-version`
- **Merge commit:** `ce44972` — two-key merge (CI green + V&R PASS on SHA `91e513c`)
- **Tag:** v1.0.4

## v1.0.3 (2026-06-12)

- **Feat(data):** OHLC value validation — `validate_ohlc_values()` checks `Hi>=Lo`, `Hi>=Op`, `Hi>=Cl`, `Lo<=Op`, `Lo<=Cl` with multi-violation `SchemaError`
- **Feat(data):** NaN/Inf killswitch fail-safe — `check_nan_inf()` standalone pre-pipeline gate; integrated into `killswitch.py` and `risk/manager.py`
- **Feat(schema):** Schema import `validate_ohlc_values` and `check_nan_inf` in `ztb/data/__init__.py` and `ztb/data/schema.py`
- **Tests:** 30 new OHLC validator tests; existing test suite adapted (test_cache, test_cli_data, test_risk_killswitch, test_risk_manager, test_schema)
- V&R PASS on SHA `b633d47` ([ZTB-769](/ZTB/issues/ZTB-769), [ZTB-779](/ZTB/issues/ZTB-779))
- **PR:** [#26](https://github.com/StaithValanthis/ztb/pull/26) — `feat/ohlc-validation`
- **Merge commit:** `8160109` — two-key merge (CI green + V&R PASS on SHA `b633d47`)
- **Tag:** v1.0.3

## v1.0.2 (2026-06-12)

- **docs/release-process.md:** Fix CI table to match actual workflow (`-m "not network"`, `--cov-report=term-missing`); move version bump before validation (no post-merge bumps); tag validated SHA directly (see ZTB-512)
- V&R PASS on SHA `f18f012` ([ZTB-590](/ZTB/issues/ZTB-590))
- **Tests:** existing — docs only, no code change
- **PR:** [#18](https://github.com/StaithValanthis/ztb/pull/18) — `feat/release-process-fix`
- **Merge commit:** `8b9c466` — two-key merge (CI green + V&R PASS on SHA `f18f012`)
- **Tag:** v1.0.2

## v1.0.1 (2026-06-12)

- Fix(store): Add `credible INTEGER NOT NULL DEFAULT 1` and `code_version TEXT DEFAULT NULL` columns to exec_orders, exec_fills, exec_positions_snapshots, exec_pnl_ledger via guarded additive migration
- Quarantine 117 corrupt v0.7.0 exec_pnl_ledger rows (`credible=0`, `code_version=0.7.0`) — equity diverged from `initial_cash + realized_pnl + unrealized_pnl`
- New accessor `get_credible_pnl_ledger(exec_run_id)` filters to credible=1 only, safe for aggregations
- Executor integration: all new writes auto-populate credible=1 + code_version from `ztb.__version__`
- V&R PASS on SHA `5719676` ([ZTB-600](/ZTB/issues/ZTB-600))
- **Tests:** all existing pass, 223 new test lines in test_execution_store.py verify schema, save, accessor, quarantine
- **PR:** [#20](https://github.com/StaithValanthis/ztb/pull/20) — `feat/quarantine-corrupt-ledger`
- **Merge commit:** `2a5745d` — two-key merge (CI green + V&R PASS on SHA `5719676`)
- **Tag:** v1.0.1

## v1.0.0 (2026-06-11)

- **M7 Live-ready (Board-armable, DISARMED by default):** `ztb/execution/live_guard.py` (LiveGuard arming gate)
- LiveGuard: `is_armed()`, `assert_live_allowed()` (raises `LiveDisarmedError` when disarmed); default DISARMED
- New `ztb/execution/killswitch.py` — unified `LiveKillSwitch`: account-DD (25%), reconcile-drift, data-staleness, heartbeat, manual trip → persist to `kill_events` table
- `ztb/execution/bybit_client.py` — M7 hardening: LiveGuard integration, `mode=LIVE` goes through `assert_live_allowed()`
- `ztb/execution/executor.py` — SIGTERM handler flattens positions on shutdown; killswitch checks on every step; kill-event persistence; `_check_killswitch()` early exit
- `ztb/execution/reconcile.py` — `reconcile_and_adopt()` with drift threshold; `heal_drift()` accessor; `irreconcilable` flag
- `ztb/ops/preflight.py` — Preflight checks: git tag pinning, version consistency, LiveGuard status, risk config, strategy readiness, secrets
- `ztb/reporting/health.py` — `HealthReport` + `check_health()` with store connectivity, tag, killswitch status
- `ztb/reporting/notify.py` — `send_live_alert()` for live-event Discord webhook notifications
- CLI: `ztb run --preflight [--expected-tag] [--expected-version]` — preflight checks before execution
- CLI: `ztb rollback <tag> [--dry-run]` — roll back to a previously released tag
- Dashboard: New Live Status tab (read-only, localhost-only, no trade/arm controls) with health check
- Store migration v5: `kill_events` table for killswitch event persistence
- Runbooks: `docs/runbooks/go-live.md`, `docs/runbooks/incident-rollback.md`
- **Tests:** 639/639 pass, 92% coverage, ruff/mypy clean, full M7 integration: live_guard, killswitch, preflight, health, CLI hardening, executor killswitch integration, reconcile drift detection, rollback, dashboard live page, notify alert, integration tests (store consistency, strategy compatibility), CLI dogfood (preflight, risk-enable, run→pipeline, expected-version)
- **Documentation:** `docs/runbooks/go-live.md`, `docs/runbooks/incident-rollback.md`
- **Tag:** v1.0.0

## v0.7.2 (2026-06-11)

- Fix(executor): `_reconcile` equity formula now uses `expected_position` instead of `_compute_unrealized_pnl()` (which used `current_position`) — expected equity = initial_cash + realized_pnl + expected_position × (close_price − avg_entry_price). Prevents equity inflation when expected position differs from current position at reconcile time.
- V&R PASS on SHA `bad7a26` ([ZTB-413](/ZTB/issues/ZTB-413))
- **Tests:** 560/560 pass, 93% coverage, ruff/mypy clean
- **PR:** [#15](https://github.com/StaithValanthis/ztb/pull/15) — `feat/fix-reconcile-equity`
- **Merge commit:** `d6ffef3` — two-key merge (CI green + V&R PASS on SHA `bad7a26`)
- **Tag:** v0.7.2
## v0.7.1 (2026-06-11)

- Fix(executor): correct equity formula in `_reconcile` to use `_compute_unrealized_pnl()` helper (unrealized P&L = position × (current price − avg entry price)) instead of `expected_position * (close_price - avg_entry_price)` — consistent with `step()` which already used the helper
- 4 new tests verify equity is not inflated for long and short positions (3 from c0de969 + 1 strengthened in 3cdbb6a)
- V&R PASS on SHA `3cdbb6a` (ZTB-367)
- **Tests:** 560/560 pass, 93% coverage, ruff/mypy clean
- **PR:** [#12](https://github.com/StaithValanthis/ztb/pull/12) — `feat/fix-equity-formula`
- **Merge commit:** `bea0580` — two-key merge (CI green + V&R PASS on SHA `3cdbb6a`)
- **Tag:** v0.7.1


## v0.7.0 (2026-06-10)

- M6 Execution Module (DEMO): `ztb/execution/` (models, bybit_client, idempotency, reconcile, executor)
- BybitClient: signed REST v5 client, demo URL hard-pinned (`api-demo.bybit.com`), `--mode=live` blocked via `LiveModeBlockedError`
- Idempotency: `orderLinkId` from stable tuple `(strategy, symbol, bar_ts, intent_hash)` — NOT `run_id`; SQLite dedupe ledger prevents double-fill on restart
- Reconciler: `reconcile_account()` detects position drift between expected and actual exchange state
- Executor pipeline: closed-bar → signal → risk gate (M5) → diff → round → idempotent place → persist
- Store migration v4: `exec_runs`, `exec_orders`, `exec_fills`, `exec_positions_snapshots`, `exec_pnl_ledger`, `exec_errors` tables
- Executor: `_save_error` logging for structured error capture on placement failures
- CLI: `ztb run <strategy> <symbol> [--mode demo] [--dry-run] [--once]`, `ztb reconcile [--exec-run-id]`
- Docs: `docs/m6_execution.md` (architecture, idempotency design, CLI reference)
- **Tests:** 560/560 pass, 93% coverage (execution/ 95-100%), ruff/mypy clean, secret scan clean, hermetic (mocked transport), signing golden vector, demo URL pin, `mode=LIVE` raises, idempotency replay safety, risk gate enforced, reconcile drift detection, executor happy path, error logging coverage
- **Documentation:** `docs/m6_execution.md`
- **PR:** [#10](https://github.com/StaithValanthis/ztb/pull/10)
- **Two-key merge:** CI green + V&R PASS on SHA `6825d08` (ZTB-302)
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
