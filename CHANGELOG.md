# Changelog

## v1.1.41 (2026-06-16)

- **Fix(executor):** Restore real demo fills — `get_executions` signature regression + 3 compounding bugs in the fill pipeline (ZTB-2658). Signed request fix; DEMO skip removal; `get_open_orders` response parsing. Real fill flow verified end-to-end.
- **Test(regression):** Source-regression locks for the real-fill root cause — test locks `get_executions` signature order to prevent recurrence (ZTB-2685, PR #159).
- **PR:** [#157](https://github.com/StaithValanthis/ztb/pull/157), [#159](https://github.com/StaithValanthis/ztb/pull/159)
- **Merge commit:** `4a9613e` — two-key merged
- **Tag:** v1.1.41

## v1.1.40 (2026-06-16)

- **Fix(data):** Add `no_cache` param to `load()` so the polling loop skips stale cached data (ZTB-2599). `_fetch_new_bars()` now passes `no_cache=True` to bypass cache reads — cache writes still happen so subsequent cold loads benefit. Existing cache short-circuit for bounded queries unchanged.
- **Tests:** 2 new tests: `test_load_no_cache_skips_cache` (no_cache=True fetches fresh data beyond cache boundary), `test_fetch_new_bars_passes_no_cache` (verifies no_cache=True passed through). All existing loader/cache/executor tests pass.
- V&R contract co-sign: [ZTB-2608](/ZTB/issues/ZTB-2608) PASS
- V&R PASS on SHA `aeef78c` ([ZTB-2608](/ZTB/issues/ZTB-2608))
- **PR:** [#152](https://github.com/StaithValanthis/ztb/pull/152)
- **Merge commit:** `6f2db2a` — two-key merged (CI green on SHA `aeef78c` + V&R PASS on SHA `aeef78c` via GitHub PR)
- **Tag:** v1.1.40

## v1.1.39 (2026-06-16)

- **Fix(executor):** Add `_sigterm_stop` checks inside `_poll_fills()` retry loop — aborts fill polling early on SIGTERM so the process exits promptly (ZTB-2506).
- **Tests:** 1 new LIVE-mode test verifying `_poll_fills` breaks out of the retry loop when `_sigterm_stop` is set mid-polling.
- CI green on SHA `91b571b` (branch).

## v1.1.38 (2026-06-16)

- **Fix(executor):** `_poll_fills` early return in DEMO mode — skips live polling cost when not needed (ZTB-2434).
- **Fix(executor):** Killswitch gap after `sleep()` in `_run_polling_loop` — check killswitch before `_fetch_new_bars()` to stop faster (ZTB-2496).
- **Tests:** 2 new DEMO-mode tests verifying zero polling in demo; 1 new killswitch-gap test. 4 existing poll_fills tests moved to Mode.LIVE.
- CI green on SHA `d797575` (branch).

## v1.1.37 (2026-06-16)

- **Feat(executor):** Replay-on-restart cursor — persist `last_bar_ts` in `exec_runs` table and skip already-processed bars on restart (ZTB-2503). On restart, `_restore_last_bar_ts()` queries the most recent completed run's cursor for (strategy, symbol, timeframe). If found and at or past warmup, the historical loop starts at `cursor_pos + 1` instead of `warmup`. Maintains warmup guarantee — falls back to full replay when cursor is missing or before warmup.
- **Schema:** v11 — `ALTER TABLE exec_runs ADD COLUMN last_bar_ts TEXT NOT NULL DEFAULT ''`
- **6 new seams:** (1) `update_exec_run_status()` signature extended with `last_bar_ts` param; (2) `_restore_last_bar_ts()` new Executor method; (3) `get_last_bar_ts()` new store function; (4) cursor skip in `run()` historical loop; (5) `_flush_bars_processed()` persists `last_bar_ts`; (6) end-of-run `update_exec_run_status` persists `last_bar_ts`.
- **Tests:** 6 new contract-validating cases: skip processed bars, maintain warmup, no-prior-run backward compat, persist cursor, invalid cursor fallback, polling loop continuation. All 153/153 executor tests pass.
- V&R contract co-sign: [ZTB-2511](/ZTB/issues/ZTB-2511) PASS
- CI green on SHA `d5be5a7` (branch). Merged with conflict resolution (watchdog removal v1.1.36 vs replay cursor).
- **Board directive:** Single authorized deploy during freeze — prerequisite for any CONFIRM (ZTB-2501 resolution).
- **PR:** replay-on-restart cursor on `feat/ztb-2503-replay-cursor`
- **Merge commit:** `31f597a` — merge into main
- **Tag:** v1.1.37

## v1.1.36 (2026-06-16)

- **Fix(executor):** Remove broken data-load watchdog (ZTB-2358) — `ThreadPoolExecutor` watchdog threads caused the main data-load loop to stall, preventing bar processing entirely (ZTB-2521). Reverts `_fetch_and_load_data` to synchronous main-thread data load with direct `try/finally` cleanup. Removes `data_load_timeout_seconds` from `ExecRunConfig`, `ThreadPoolExecutor` usage, `BybitPublicREST.close()`, and 4 watchdog-specific test cases.
- **Fix(executor):** Restore main-thread data load — simplifies error handling, eliminates thread-join deadlock that blocked bars_processed > 0 on v1.1.35.
- **Tests:** 4 watchdog-specific tests removed; remaining 1033/1033 passing. Ruff/mypy clean.
- V&R contract co-sign: [ZTB-2525](/ZTB/issues/ZTB-2525) PASS
- V&R PASS on SHA `e3dcc163` ([ZTB-2527](/ZTB/issues/ZTB-2527))
- **PR:** [#146](https://github.com/StaithValanthis/ztb/pull/146) — `feat/ztb-2504-cherry-pick-watchdog-removal`
- **Merge commit:** `0f2e861` — two-key merged (CI green + V&R PASS on SHA `e3dcc163`)
- **Tag:** v1.1.36

## v1.1.35 (2026-06-16)

- **Feat(executor):** Configurable polling loop for `get_executions()` in `_step_impl` (ZTB-2447). New `_poll_fills()` method retries at `poll_fill_interval` (default 0.5s) up to `poll_fill_max_attempts` (default 5, total ~2.5s) before falling through to synthetic fill fallback. Real `execId` fills are recorded when they arrive during polling, enabling the `CONFIRM` gate for deploy (ZTB-2308). Added `poll_fill_max_attempts` and `poll_fill_interval` to `ExecRunConfig`.
- **Tests:** 4 new test cases: fills on first attempt, retry-then-synthetic, real fill captured during polling, warning on exhaustion. 3 existing tests updated with `poll_fill_max_attempts=1` to preserve synthetic-fallback coverage. Full suite: 1035/1037 passing (2 pre-existing env/version-skew failures).
- V&R contract co-sign: [ZTB-2486](/ZTB/issues/ZTB-2486) PASS
- V&R PASS on SHA `50be122` ([ZTB-2488](/ZTB/issues/ZTB-2488)); re-validated on `e1d0b94` (update-branch + bridge)
- **PR:** [#142](https://github.com/StaithValanthis/ztb/pull/142) — `feat/ztb-2447-exec-fill-polling`
- **Merge commit:** `4e336bc` — two-key merged (CI green + V&R PASS on SHA `50be122`, re-validated on `e1d0b94`)
- **Tag:** v1.1.35

## v1.1.34 (2026-06-16)

- **Feat(data):** Data-load watchdog + HTTP diagnostics (ZTB-2358). Configurable timeout (`data_load_timeout_seconds`, default 600s) using `ThreadPoolExecutor` + `fut.result(timeout=...)` — raises `ExecutionError` if data load exceeds deadline. DEBUG-level logging for every Bybit REST request/response with monotonic timing; WARNING on transport errors; retry `httpx.TimeoutException`/`httpx.HTTPError` up to 3 times. Connection cleanup: `BybitPublicREST.close()` + `loader.load()` try/finally.
- **Fix(executor):** `_ensure_warmup` returns extended data directly instead of concatenation (bug from earlier refactor).
- **Tests:** 7 new test cases: watchdog fires on timeout, no false positive, disabled; HTTP request logging, transport retry, transport retry exhausted, REST client close. Full suite: 1041/1041 passing.
- V&R contract co-sign: [ZTB-2357](/ZTB/issues/ZTB-2357) PASS
- V&R PASS on SHA `8827639` ([ZTB-2435](/ZTB/issues/ZTB-2435))
- **PR:** [#137](https://github.com/StaithValanthis/ztb/pull/137) — `feat/data-load-watchdog`
- **Merge commit:** `28e3f7b` — two-key merged (CI green + V&R PASS on SHA `8827639`)
- **Tag:** v1.1.34

## v1.1.33 (2026-06-16)

- **Fix(executor):** Process each intermediate bar individually in `_run_polling_loop` during polling catch-up. When `_fetch_new_bars` returns multiple bars (e.g. after network interruption), the loop iterates through each bar via `range(old_len, new_len)` and calls `step()` with the correctly growing data slice — each bar triggers signal generation, signal-change detection, and killswitch check.
- **Invariants:** (1) Each intermediate bar triggers signal on its own slice; (2) signal change detection works across bars; (3) idempotency via unique `orderLinkId` per `bar_ts`; (4) killswitch checked per bar, breaks early on trip; (5) `ClientError` on any bar logs and continues (does not skip remaining bars); (6) `consecutive_errors` reset after each batch.
- **Tests:** 5 new test cases: multi-bar catchup with correct chunk sizes (201, 202, 203); killswitch break on bar 2; ClientError continues on bar 2 (bars 1+3 processed); zero-new-bar normal poll; single-bar normal path. Full suite: 1034/1034 passing.
- V&R PASS on SHA `5634811` ([ZTB-2407](/ZTB/issues/ZTB-2407))
- **PR:** [#133](https://github.com/StaithValanthis/ztb/pull/133) — `feat/ztb-2342-fetch-new-bars-catchup`
- **Merge commit:** `e00a2ee` — two-key merged (CI green + V&R PASS on SHA `5634811`)
- **Tag:** v1.1.33

## v1.1.32 (2026-06-16)

- **Fix(executor):** Use account-level `totalAvailableBalance` instead of per-coin `availableBalance` in `_step_impl` sizing. Bybit UTA demo accounts omit coin-level `availableBalance`, causing the sizing path to treat it as `0.0` and never place orders. Replaced `available_balance` with `total_available_balance` in the sizing condition and notional calculation; removed unused `available_balance` variable.
- **Tests:** Updated existing test wallet fixtures to include `totalAvailableBalance` field. Added UTA regression test `test_executor_uta_no_coin_available_balance`. Full suite: 996/997 pass (1 pre-existing network test failure).
- **Root cause:** Bybit V5 wallet API for UTA accounts does not include coin-level `availableBalance` key. Code at `executor.py:449` treated missing key as `0.0`, defeating the primary balance-based order sizing.
- V&R PASS on SHA `897e478` ([ZTB-2248](/ZTB/issues/ZTB-2248))
- **PR:** [#138](https://github.com/StaithValanthis/ztb/pull/138) — `feat/ztb-2225-available-balance-sizing`
- **Merge commit:** `1bb1b93` — two-key merged (CI green + V&R PASS on SHA `897e478`; branch updated with main between validation and merge — fix code unchanged)
- **Tag:** v1.1.32

## v1.1.31 (2026-06-16)

- **Fix(executor):** Bound `_ensure_warmup` data fetch to `[extended_start, current_start]` (was `end=None` → unbounded epoch→now pagination). Merge extended data with original via `pd.concat` + index dedup (`keep="last"`) + `sort_index()`. Defensive `max(wait, 0.01)` in TokenBucket spin-wait loop to reduce CPU.
- **Root cause:** `_ensure_warmup` called `load_data(..., end=None)`, triggering `paginate_kline` from now back to extended_start — on cold cache, this paginated thousands of 1000-bar windows, producing 3+ minute stalls (rate-limited to ~10 req/s by TokenBucket). Second defect: `return extended` discarded original data, causing the second warmup check to re-fetch.
- **Tests:** 6 new test cases: end-bound validation, merge preserves original data, overlap dedup (original wins), no-cascade on re-check, TokenBucket no-busy-spin, executor dry-run completes in <5s (1.40s wall). Full regression: 992/992 tests passing (pre-existing env/version-skew exclusions).
- V&R contract co-sign: [ZTB-2321](/ZTB/issues/ZTB-2321) PASS
- V&R PASS on SHA `6944fea` ([ZTB-2361](/ZTB/issues/ZTB-2361)); re-validated on `722240a` (vr-pass CI check)
- **PR:** [#132](https://github.com/StaithValanthis/ztb/pull/132) — `fix/ztb-2276-warmup-rate-limit`
- **Merge commit:** `ea836a8` — two-key merged (CI green + V&R PASS on same SHA)
- **Tag:** v1.1.31

## v1.1.30 (2026-06-16)

- **Fix(executor):** Wrap `save_killswitch_state()` with `contextlib.suppress(sqlite3.OperationalError)` in `_check_killswitch()` and the per-bar heartbeat persist — when the DB is locked, the killswitch break signal (`return True`) now propagates even when the DB write fails. Previously, an `OperationalError` inside `_check_killswitch()` would silently lose the killswitch signal and crash via max_errors/PollingError instead of a graceful killswitch stop.
- **Tests:** 2 new test cases verifying OperationalError does not crash `_check_killswitch()` or the heartbeat persist path. All tests pass.
- V&R PASS on SHA `0aa0a85` (vr-pass CI check)
- **PR:** [#130](https://github.com/StaithValanthis/ztb/pull/130) — `feat/ztb-2319-suppress-killswitch`
- **Merge commit:** `6b2af83` — two-key merge (CI green + V&R PASS on SHA `0aa0a85`)
- **Tag:** v1.1.30

## v1.1.29 (2026-06-15)

- **Fix(executor):** Catch `sqlite3.OperationalError` in polling loop error path — the executor's `_run_polling_loop` now wraps the fill-poll query in a try/except for `OperationalError`. Before: a transient `database is locked` during polling crashed the entire loop. After: the error is logged and the loop retries on the next tick.
- **Tests:** 1 new test case covering `OperationalError` suppression in polling loop. 1018/1021 passing (3 pre-existing: `test_cli_smoke_test_network`, `test_cli_run_with_preflight`, `test_version_consistency` — env/version-skew only).
- V&R PASS on SHA `70b2a1a`
- **PR:** [#126](https://github.com/StaithValanthis/ztb/pull/126) — `feat/ztb-2255-fix-polling-loop-operational-error`
- **Merge commit:** `c152a91` — two-key merge (CI green + V&R PASS on SHA `70b2a1a`)
- **Tag:** v1.1.29

## v1.1.28 (2026-06-15)

- **Fix(engine):** `run_backtest` and `run_forwardtest` now extend data backwards before `strategy.generate_signals()` when the data window from `--start` is shorter than `strategy.warmup + 1`. Before: all signals silently zeroed → 0 trades, 0 risk_decisions. After: warmup bars fetched via optional `loader` parameter; if no loader is available, raises `ValueError` (no silent zero trades). Executor `_compute_target_position` now logs a warning when skipping strategy evaluation due to insufficient warmup data.
- **Tests:** 8 new test cases covering `--start` data slicing across backtest, forwardtest, and executor. 815/815 passing full suite.
- V&R PASS on SHA `508f588` ([ZTB-2253](/ZTB/issues/ZTB-2253))
- **PR:** [#127](https://github.com/StaithValanthis/ztb/pull/127) — `fix/ztb-2250-start-silent-skip`
- **Merge commit:** `8399e49` — two-key merge (CI green + V&R PASS on SHA `508f588`)
- **Tag:** v1.1.28

## v1.1.27 (2026-06-15)

- **Feat(store):** Add `retry_on_lock` decorator with exponential backoff (+jitter) to all store write functions — catches `sqlite3.OperationalError 'database is locked'` (`busy_timeout` raised from 5000 to 30000 ms). Applied to `exec_io.py` (14 write funcs), `results.py` (3 write funcs), `idempotency.py` (5 write funcs), and `validation/store.py` (`save_validation_run`).
- **Tests:** 16 new test cases in `test_store_retry.py` covering decorator unit tests, applied integration tests, and `busy_timeout` verification. 997/997 total tests passing (0 pre-existing).
- V&R PASS on SHA `16854e9` ([ZTB-2232](/ZTB/issues/ZTB-2232))
- **PR:** [#118](https://github.com/StaithValanthis/ztb/pull/118) — `feat/ztb-2155-database-locked-fix`
- **Merge commit:** `6f75469` — two-key merge (CI green + V&R PASS on SHA `16854e9`)
- **Tag:** v1.1.27

## v1.1.26 (2026-06-15)

- **Fix(executor):** Resolve duplicate `OrderLinkedID` on stale-pending retry — stale pending rows are resolved as `failed` (not DELETEd) and retried with a nonced `order_link_id`. `_reconcile_pending_order` now queries both `get_order_history` and `get_open_orders` (dual-endpoint). Defensive `ClientError` handler catches `"OrderLinkedID is duplicate"` around `place_order` — found orders are restored; not-found bars are skipped gracefully with full state advancement. `clear_pending()` added to startup cleanup.
- **Tests:** 6 new test cases (`test_stale_pending_resolve_failed_nonce`, `test_reconcile_pending_order_open_orders_match`, `test_reconcile_pending_order_both_endpoints`, `test_place_order_duplicate_reconcile_found`, `test_place_order_duplicate_skip_bar_advances_state`, `test_reconcile_query_failure_skip`). 120/120 executor tests passing (994/997 total — 3 pre-existing: version skew + network).
- V&R PASS on SHA `ceb9962` ([ZTB-2213](/ZTB/issues/ZTB-2213))
- **PR:** [#122](https://github.com/StaithValanthis/ztb/pull/122) — `feat/orderlinkid-duplicate-fix`
- **Merge commit:** `475cd86` — two-key merge (CI green + V&R PASS on SHA `ceb9962`)
- **Tag:** v1.1.26

## v1.1.25 (2026-06-15)

- **Fix(executor):** `_reconcile_pending_order` helper and stale-pending retry path — when `try_claim` fails and the existing row has no `order_id` (API response lost), reconcile via Bybit order history before resubmitting. If the order went through, resolve idempotency and restore; if not, delete stale pending row and retry.
- **Tests:** 5 new test cases covering all reconcile scenarios (`test_stale_pending_should_reconcile_via_order_history`, `test_reconcile_pending_order_found`, `test_reconcile_pending_order_not_found`, `test_reconcile_pending_order_api_failure`, `test_stale_pending_fallback_does_not_break_crash_recovery`). 114/114 executor tests passing.
- V&R PASS on SHA `7b552a3` ([ZTB-2146](/ZTB/issues/ZTB-2146))
- **PR:** [#116](https://github.com/StaithValanthis/ztb/pull/116) — `feat/ztb-2130-m1-reconcile`
- **Merge commit:** `d6ed298` — two-key merge (CI green + V&R PASS on SHA `7b552a3`)
- **Tag:** v1.1.25

## v1.1.24 (2026-06-15)

- **Fix(executor):** `clear_stale(ttl_hours=24)` instead of `clear_stale(ttl_hours=0)` — GC only idempotency entries older than 24h on startup instead of wiping all entries. `clear_pending()` removed — in-flight `pending` rows survive restarts, enabling crash-recovery without duplicate `order_link_id` errors.
- **Tests:** Existing executor startup tests pass (no new tests — behavioral change only, no new code paths).
- V&R PASS on SHA `5df25cd` ([ZTB-2128](/ZTB/issues/ZTB-2128))
- **PR:** [#115](https://github.com/StaithValanthis/ztb/pull/115) — `feat/ztb-2126-clear-stale-ttl-24`
- **Merge commit:** `99e4fc9` — two-key merge (CI green + V&R PASS on SHA `5df25cd`)
- **Tag:** v1.1.24

## v1.1.23 (2026-06-15)

- **Fix(executor):** Save `exec_fill` record on synthetic fill fallback path — when the exchange returns no fills (common for IOC market orders in demo), the synthetic fallback now persists an `exec_fill` row. Previously only `exec_order` was saved, leaving a gap where `exec_orders > 0` but `exec_fills = 0`.
- **Tests:** 4 new tests for synthetic fill persistence + order_link_id matching.
- V&R PASS on SHA `8b01415` ([ZTB-2087](/ZTB/issues/ZTB-2087))
- **PR:** [#113](https://github.com/StaithValanthis/ztb/pull/113) — `feat/ztb-2072-fix-exec-fills`
- **Merge commit:** `3ade544` — two-key merge (CI green + V&R PASS on SHA `8b01415`)
- **Tag:** v1.1.23

## v1.1.22 (2026-06-15)

- **Fix(executor):** `IdempotencyLedger.clear_pending()` — delete orphaned `pending` idempotency rows on startup. `clear_stale(ttl_hours=0)` only cleared `placed`/`filled` rows; `pending` rows from crashed runs (between `try_claim` and `resolve`) blocked the next retry with "OrderLinkedID is duplicate" (2,297×/60min).
- **Tests:** 4 new `clear_pending` tests + 4 new/updated `exec_fills` tests (column preservation, v10 migration data integrity). 61/61 tests passing.
- V&R PASS on SHA `0700a59` ([ZTB-2019](/ZTB/issues/ZTB-2019))
- **PR:** [#104](https://github.com/StaithValanthis/ztb/pull/104) — `feat/ztb-1935-fix-linkedid-schema`
- **Merge commit:** `a69727b` — two-key merge (CI green + V&R PASS on SHA `0700a59`)
- **Tag:** v1.1.22

## v1.1.21 (2026-06-15)

- **Fix(store):** Remove FK constraint from `exec_fills.order_link_id` → `exec_orders(order_link_id)` — stable-tuple `orderLinkId` values from the exchange (repeated across fills for the same logical order) no longer cause FK violations. Schema v10 migration recreates `exec_fills` without the FK. Removed implicit parent-order auto-creation in `save_exec_fill` (the FK workaround).
- **Tests:** `test_save_exec_fill_orphan` asserts fills are saved without auto-creating an order row. `test_exec_fills_no_order_link_id_fk` verifies FK is removed. `test_schema_meta_version_10` confirms migration ran. 58/58 execution store tests passing.
- V&R PASS on SHA `f6ba67f` ([ZTB-1931](/ZTB/issues/ZTB-1931))
- **PR:** [#107](https://github.com/StaithValanthis/ztb/pull/107) — `feat/ztb-1931-remove-fk-fills`
- **Merge commit:** `f6ad9bd` — two-key merge (CI green + V&R PASS on SHA `1124632`)
- **Tag:** v1.1.21

## v1.1.20 (2026-06-15)

- **Feat(cli):** `ztb smoke-test` — end-to-end demo order verification command. Places a real demo order via Bybit API, polls until filled, validates `exec_fills` row (real fee, correct price scale ~ tens of thousands, `code_version` stamped, no duplicate order_link_id churn). 467 lines of tests in `tests/test_cli_smoke_test.py`.
- **Tests:** Full smoke test suite — 549 lines total including end-to-end order lifecycle validation.
- V&R PASS on SHA `f3e7939f` ([ZTB-2016](/ZTB/issues/ZTB-2016))
- **PR:** [#103](https://github.com/StaithValanthis/ztb/pull/103) — `feat/smoke-test`
- **Merge commit:** `540cb41` — two-key merge (CI green + V&R PASS on SHA `f3e7939f`)
- **Tag:** v1.1.20

## v1.1.19 (2026-06-15)

- **Feat(execution):** `IdempotencyLedger.clear_stale(ttl_hours=24)` — deletes resolved entries older than a configurable TTL to prevent unbounded `idempotency` table growth. Adds `count()` method and `idx_idempotency_stale` index on `(status, created_at)` for efficient cleanup queries.
- **Fix(store):** `save_exec_fill` ensures parent `exec_orders` row exists before inserting into `exec_fills` — prevents silent FK violation data loss by auto-creating a minimal order entry when fills arrive without a pre-existing order row.
- **Tests:** New tests for `clear_stale()`, `count()`, and FK self-healing in `save_exec_fill`.

## v1.1.18 (2026-06-15)

- **Fix(execution):** `top_up_demo_account` reads `walletBalance` instead of `availableBalance` from Bybit wallet-balance response — `availableBalance` does not exist in the response, so `.get()` returned `0.0`, triggering false `credited=0.0` warnings.
- **Tests:** Test fixtures use distinct values for `walletBalance` vs `availableBalance` to catch regression
- V&R PASS on SHA `c548b6a` ([ZTB-1880](/ZTB/issues/ZTB-1880))
- **PR:** [#97](https://github.com/StaithValanthis/ztb/pull/97) — `feat/fix-top-up-demo-account`
- **Merge commit:** `cc91c63` — two-key merge (CI green + V&R PASS on SHA `c548b6a`)
- **Tag:** v1.1.18

## v1.1.17 (2026-06-15)

- **Fix(executor):** Reduce-only zero-position guard — when exchange position is zero (after warmup or manual cleanup), detect before placing reduce-only order, adopt zero position, and skip the order with proper accounting. Prevents Bybit rejection of zero-position reduce-only orders.
- **Tests:** 4 new tests covering zero-position long/short/flat/no-position scenarios — 105/105 executor tests passing on SHA `759439f` (rebased + amended)
- V&R PASS on SHA `992c14e` (conditional: message fix applied per condition); CI green + vr-pass SUCCESS on SHA `759439f`
- **PR:** [#93](https://github.com/StaithValanthis/ztb/pull/93) — `feat/reduce-only-zero-guard`
- **Merge commit:** `0bcb051` — two-key merge (CI green on `759439f` + V&R PASS on `992c14e` with condition satisfied)
- **Tag:** v1.1.17

## v1.1.16 (2026-06-15)

- **Fix(executor):** Detect position flips (abs(delta) > abs(current_position) with opposite signs) and set `reduce_only=False` so flip orders fill completely on Bybit. Balance cap accounts for existing position during flips — only the opening portion is subject to margin cap. Previously, flip orders were incorrectly `reduce_only=True`, which silently truncated fills to existing position size, causing persistent position drift.
- **Tests:** 3 new tests covering long→short flip, short→long flip, and balance-cap flip scenarios — 101/101 executor tests passing
- V&R PASS on SHA `b58ce3a` ([ZTB-1815](/ZTB/issues/ZTB-1815))
- **PR:** [#92](https://github.com/StaithValanthis/ztb/pull/92) — `fix/reduce-only-warmup`
- **Merge commit:** `cb8fee0` — two-key merge (CI green + V&R PASS on SHA `b58ce3a`)
- **Tag:** v1.1.16

## v1.1.15 (2026-06-15)

- **Fix(store):** Add `PRAGMA busy_timeout=5000` to SQLite `connect()` to prevent 'database is locked' crashes under concurrent access (demo loop, VE tests)
- **Chore(validation):** Thread `initial_cash`, `commission`, `slippage` from CLI through `WalkForwardConfig` to `BacktestConfig` for economic-parameter consistency in walk-forward validation
- **Tests:** `test_economic_params_thread_to_backtest` — verifies custom economic params propagate through walk-forward pipeline
- V&R PASS on SHA `0447328` ([ZTB-1784](/ZTB/issues/ZTB-1784)); MD authorization ([ZTB-1799](/ZTB/issues/ZTB-1799))
- **PR:** [#86](https://github.com/StaithValanthis/ztb/pull/86) — `feat/busy-timeout`
- **Merge commit:** `0805cca` — two-key merge (CI green + V&R PASS on SHA `0447328`)
- **Tag:** v1.1.15

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
