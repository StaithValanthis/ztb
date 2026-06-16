# Frozen Contract: Inert Demo Bot — 4 Root-Cause Forward Fixes

**Issue:** ZTB-2628 — FORWARD FIX: inert demo bot — 4 root-cause investigations (v1.1.38+)
**Owner:** Head of Engineering
**Date:** 2026-06-16
**Status:** DRAFT (awaiting V&R co-sign — ZTB-2634)

---

## Overview

The demo bot has produced 0 `exec_fills` for v1.1.38+ and 0 `exec_orders` for v1.1.35+. Four distinct root-cause areas have been identified. Each is a code bug or logging gap in the engine/executor layer. All changes are in `ztb/execution/` and `ztb/risk/`.

**Branch name:** `feat/ztb-2628-inert-demo-fix`
**Delegated to:** Platform Engineer

---

## Area 1: DEBUG logging in BybitClient._request and place_order

### Finding
BybitClient._request() (`bybit_client.py:75-134`) handles HTTP responses but has NO debug logging of raw response bodies. It parses `resp.json()`, checks `retCode`, and either returns result or raises `ClientError`. There is no logger.debug() call that dumps the response. Similarly, `place_order()` (`bybit_client.py:136-165`) logs nothing about the order params or the response.

### Contract

#### Interface/Seam
1. In `_request()`, add `logger.debug()` before return/raise — log `method`, `path`, `retCode`, `retMsg`, and a truncated summary of `result`.
2. In `place_order()`, add `logger.info()` at INFO level in DEMO mode — log `symbol`, `side`, `qty`, `order_link_id`, and the response `orderId` (or skip reason).

#### Cost/Timing Convention
- Additive logging only. No cost, no timing change to order placement path.
- Logging is at DEBUG level for production; INFO for DEMO mode order placements.

#### Schema Seam
- No schema changes. Audit table logging (`_log_audit`) already exists and is unchanged.

#### Required Tests
- `test_request_logs_response_body_debug` — mock `_request` response, verify `logger.debug` called with retCode.
- `test_place_order_logs_params_demo` — DEMO mode, verify `logger.info` called with order params.
- `test_place_order_logs_skip_demo` — DEMO mode, qty skips validation, verify skip log.
- No change to existing test behavior (logging is additive).

#### Invariants

| Invariant | Status |
|-----------|--------|
| **Equity = initial_cash + realized_pnl + unrealized_pnl** | Unchanged — no PnL/equity code touched |
| **No look-ahead (signal t→t+1)** | Unchanged — no signal code touched |
| **Fees + slippage applied** | Unchanged — no fill code touched |
| **Executor uses shared accounting** | Unchanged |

---

## Area 2: Persist skip reasons to exec_errors via _save_error()

### Finding
Three skip paths in `_step_impl` (executor.py) only append to in-memory `self.state.errors` list — they NEVER call `_save_error()` to persist to DB `exec_errors` table:
- **(A)** Reduce-only skip when exchange position is zero (~line 744)
- **(B)** Qty capped to zero by balance limit (~line 777)
- **(C)** Validation skip from client `place_order` returns `skipped=True` (~line 849)

Only `ClientError` in `step()` (~line 462) writes to `exec_errors` via direct `save_exec_error()` call.

### Contract

#### Interface/Seam
In each of the 3 skip paths above, add a call to `self._save_error("OrderSkipped", skip_reason)` BEFORE the `return result` statement. This persists the skip to the `exec_errors` table with `error_type="OrderSkipped"`.

#### Cost/Timing Convention
- Adds a DB `INSERT INTO exec_errors` per skipped bar. This is the same pattern as the existing `ClientError` path (line 462) and `FillFetchError` (line 872).
- Timing impact: negligible (single SQLite INSERT).

#### Schema Seam
- No schema changes. Uses existing `exec_errors` table.

#### Required Tests
- `test_reduce_only_skip_saves_exec_error` — set up reduce-only skip (exchange position=0), verify `exec_errors` row with `error_type='OrderSkipped'` in the DB.
- `test_balance_cap_skip_saves_exec_error` — set up balance-cap skip (capped qty=0), verify exec_errors row.
- `test_validation_skip_saves_exec_error` — mock `place_order` to return `{"skipped": True, "reason": "..."}`, verify exec_errors row.
- Existing tests (`test_reduce_only_skipped_when_no_exchange_position_long`, `test_balance_cap_skips_when_capped_qty_zero`, `test_executor_skipped_order_early_return`) still pass.

#### Query Scope (contract-review mandatory)
- No new exchange queries. `_save_error` writes ONLY to local SQLite `exec_errors` table.
- The skip reason message is exactly what was previously in-memory — no new data fetched.

#### Orphan Row Cleanup
- No new rows created that could orphan. Each `exec_errors` row is a self-contained log record.

#### State Machine Advancement
- All 3 skip paths already advance `bars_processed`, `last_bar_ts`, save position snapshot, and save PnL. The _save_error() call is added BEFORE the return, so it executes on every skip. No change to state machine logic.

#### API Failure Fallback
- `_save_error` writes to local SQLite only. If the DB write fails (OperationalError), the error propagates up to `step()` which catches `Exception` (line 476) and issues its own `save_exec_error`.

#### Invariants

| Invariant | Status |
|-----------|--------|
| **Equity = initial_cash + realized_pnl + unrealized_pnl** | Unchanged |
| **No look-ahead (signal t→t+1)** | Unchanged |
| **Fees + slippage applied** | Unchanged |
| **Executor uses shared accounting** | Unchanged |

---

## Area 3: _validate_qty floor-rounding warning when qty rounds to 0.0

### Finding
`round_to_step()` uses floor rounding (`int(qty / qty_step) * qty_step`). With `--cash 100` + `max_position_pct=0.50` at BTC ~60000:
- `target_qty = 0.50 * 100 / 60000 = 0.00083333`
- `round_to_step(0.00083333, 0.001)` = 0.0 (floor)
- `_validate_qty` returns `{"skipped": True, "reason": "Qty 0.0 below minOrderQty 0.001"}`

This is expected behavior — the configured cash is too small for BTC. The bot correctly skips. But there is no warning at the validation step that the qty was floored to 0.

### Contract

#### Interface/Seam
In `_validate_qty()` (`bybit_client.py:276-292`), after `qty = self.round_to_step(qty, qty_step)` and before the min_qty check, add a `logger.warning()` when qty rounds to 0.0 from a positive input.

#### Cost/Timing Convention
- Additive logging only. No timing change.

#### Schema Seam
- No schema changes.

#### Required Tests
- `test_validate_qty_floored_to_zero_warns` — pass qty=0.0005 with qty_step=0.001, verify `logger.warning` called with "floored to 0" message.
- `test_validate_qty_normal_no_warning` — pass qty=0.002 with qty_step=0.001, verify no warning.
- Existing `test_validate_qty_below_min_skips` still passes.

#### Invariants

| Invariant | Status |
|-----------|--------|
| **Equity = initial_cash + realized_pnl + unrealized_pnl** | Unchanged |
| **No look-ahead (signal t→t+1)** | Unchanged |
| **Fees + slippage applied** | Unchanged |
| **Executor uses shared accounting** | Unchanged |

---

## Area 4: Fix _apply_risk position % cap scaling

### Finding
In `RiskManager.evaluate()` (`manager.py:115-139`), when `pos_pct > max_position_pct`, the method clips `proposed_positions[sym]` locally but returns a `RiskDecision` with `max_notional=equity * max_leverage` (line 95 / line 131) — NOT `max_position_pct * equity`.

Then `_apply_risk` (`executor.py:289-292`) computes:
```python
scale = decision.max_notional / sig_val  # max_notional = equity * max_leverage
return target_signal * min(scale, 1.0)   # scale >= 1.0 when target_signal <= max_leverage
```

Result: when `target_signal=1.0`, `max_leverage=3.0`, `max_position_pct=0.50`:
- `max_notional = 100 * 3.0 = 300`
- `sig_val = 1.0 * 100 = 100`
- `scale = 300/100 = 3.0`, `min(3.0, 1.0) = 1.0`
- Signal returned UNCHANGED at 1.0 — the 50% position cap is completely bypassed.

### Contract

#### Interface/Seam

**Fix 1 (root cause):** In `RiskManager.evaluate()` at the position % cap case (manager.py:~131), change `max_notional` to reflect the position % constraint:
```python
max_notional = self.config.max_position_pct * equity
```

**Fix 2 (fallback — defense-in-depth):** In `_apply_risk()` (executor.py:~289-292), when `decision.max_pos_size > 0`, compute scale from `max_pos_size * price` instead of `max_notional`:
```python
if decision.max_pos_size > 0:
    pos_notional = decision.max_pos_size * price
    scale = pos_notional / sig_val if sig_val > 0 else 0.0
else:
    scale = decision.max_notional / sig_val if sig_val > 0 else 0.0
```

**Both fixes required for defense-in-depth.**

#### Cost/Timing Convention
- Changes signal scaling for position-% capped signals. Previously unscaled (returned unchanged), now correctly capped to `max_position_pct`.
- No additional API calls. No timing change.

#### Schema Seam
- No schema changes.

#### Required Tests
- `test_evaluate_position_pct_sets_correct_max_notional` — verify when position % cap triggers, `decision.max_notional == max_position_pct * equity` (not `max_leverage * equity`).
- `test_executor_apply_risk_position_pct_capped` — set up `max_leverage=10.0, max_position_pct=0.50, target_signal=1.0`, verify returned signal is 0.50 (capped by position %), not 1.0 (bypassed).
- `test_executor_apply_risk_leverage_still_works` — set up `max_leverage=2.0, max_position_pct=0.95, target_signal=5.0`, verify returned signal is 2.0 (capped by leverage, not position %). This must still pass — leverage cap is unchanged.
- Existing tests `test_evaluate_position_pct_exceeded`, `test_executor_apply_risk_reduce` still pass.

#### Query Scope (contract-review mandatory)
- No new exchange queries. All changes are to in-memory computation.

#### Orphan Row Cleanup
- No rows affected. Risk decisions are in-memory only.

#### State Machine Advancement
- No change to state machine advancement. The signal scaling happens BEFORE any order placement or state update.

#### API Failure Fallback
- No API calls in this path. `_apply_risk` is pure computation.

#### Invariants

| Invariant | Status |
|-----------|--------|
| **Equity = initial_cash + realized_pnl + unrealized_pnl** | Unchanged |
| **No look-ahead (signal t→t+1)** | Unchanged |
| **Fees + slippage applied** | Unchanged |
| **Executor uses shared accounting** | Unchanged |
| **Position % cap is now correctly enforced** | **FIXED** — previously bypassed |

---

## Build Requirements

### Branch
- `feat/ztb-2628-inert-demo-fix` — created from `main` at current HEAD (v1.1.40)

### Worktree
- `~/ztb-wt/ztb-2628-inert-demo-fix` — isolated worktree

### Files in scope
- `ztb/execution/bybit_client.py` (Areas 1, 3)
- `ztb/execution/executor.py` (Areas 2, 4)
- `ztb/risk/manager.py` (Area 4)
- `tests/test_execution_bybit_client.py` (Areas 1, 3)
- `tests/test_execution_executor.py` (Areas 2, 4)
- `tests/test_risk_manager.py` (Area 4)

### Self-Audit Checklist (required before hand-up)
Per `/home/ubuntu/ztb-firm/memory/skills/builder-self-audit-handoff.md`:
- [ ] Branch rebased on current `main`
- [ ] Only in-scope files changed
- [ ] CI green: pytest, ruff check, ruff format --check, mypy
- [ ] Equity invariant checked
- [ ] No look-ahead verified
- [ ] Fees + slippage applied (unchanged)
- [ ] Executor uses shared accounting
- [ ] Conventional commits with issue reference

### Tag
- `v1.1.41` (post-merge version bump)
