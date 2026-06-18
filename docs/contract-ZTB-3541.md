# ZTB-3541 Frozen Contract: Enable per-trade SL/TP with sensible defaults + close remaining gaps

## Scope

Close 4 remaining gaps after PR #176 (SL/TP infrastructure): rebase close-gaps fixes, fix `_clear_sl_tp` idempotency bug, set non-zero defaults, implement per-strategy SL/TP precedence.

## Existing Code (not new — referenced by contract)

All refer to `origin/main` (v1.1.53, SHA `da0e3d9`):

| Symbol | Location | Purpose |
|--------|----------|---------|
| `Executor._apply_sl_tp()` | `executor.py:160` | Calls `client.set_trading_stop()` with SL/TP prices |
| `Executor._clear_sl_tp()` | `executor.py:230` | Calls `client.set_trading_stop(sl=0, tp=0)`, removes from `_active_sl_tp` |
| `Executor._active_sl_tp` | `executor.py:77` | `dict[str, dict]` — tracks active SL/TP per symbol |
| `ExecRunConfig.sl_pct` | `models.py:111` | Default `0.0` (disabled) |
| `ExecRunConfig.tp_pct` | `models.py:112` | Default `0.0` (disabled) |
| `make_sl_tp_order_link_id()` | `idempotency.py:25` | Creates hex digest (36 chars) for SL/TP idempotency |
| `set_trading_stop()` | `bybit_client.py:226` | Bybit POST /v5/position/trading-stop |
| `SCHEMA_VERSION` | does NOT exist | To be added to `store/__init__.py` |
| `_cleanup_orphan_sl_tp()` | does NOT exist | To be added to `Executor` |
| CLI `run`/`backtest`/`forwardtest` | `cli.py` | No `--sl-pct`/`--tp-pct` today |

## Changes to Build

### Change 1: Rebase and merge `feat/ztb-sl-tp-close-gaps` OR content

Commit `ed0c883` (fix 3 SL/TP gaps):
1. Add `_cleanup_orphan_sl_tp()` — queries `client.get_active_trading_stops()`, clears untracked SL/TP orders on startup
2. Wire `_clear_sl_tp` into SIGTERM handler — clears tracked SL/TP on shutdown
3. Add `SCHEMA_VERSION = 12` to `ztb/store/__init__.py`, add assertion `MAX(version) == SCHEMA_VERSION` in `_run_migrations`
4. Replace startup inline SL/TP query block with `_cleanup_orphan_sl_tp()`
5. Tests: `test_cleanup_orphan_sl_tp_clears_active_sl`, `test_clear_sl_tp_logs_warning_on_failure`, `test_clear_sl_tp_wired_to_killswitch`, `test_schema_version_equals_max_schema_meta`

### Change 2: Fix `_clear_sl_tp` idempotency bug

**Bug:** `_clear_sl_tp` deletes from idempotency table with `LIKE '%:{symbol}:%'`. But `order_link_id` values are SHA256 hex digests (36 chars for SL/TP) — no colon-delimited substring exists, so the pattern **never matches**. The DELETE is a silent no-op, causing stale SL/TP entries to accumulate in the idempotency table.

**Fix:** Store SL/TP order_link_ids in `_active_sl_tp` alongside `sl_price`/`tp_price`. In `_clear_sl_tp`, delete by exact `order_link_id` instead of `LIKE` pattern:

```python
_active_sl_tp[symbol] = {
    "sl_price": sl_price,
    "tp_price": tp_price,
    "sl_link_id": sl_link_id,   # NEW
    "tp_link_id": tp_link_id,   # NEW (0 if tp not set)
}
```

Delete in `_clear_sl_tp`:
```python
entry = self._active_sl_tp.get(symbol, {})
for lid in [entry.get("sl_link_id"), entry.get("tp_link_id")]:
    if lid:
        self._idempotency.conn.execute(
            "DELETE FROM idempotency WHERE order_link_id = ?", (lid,)
        )
```

### Change 3: Set sensible default SL/TP values

Change `ExecRunConfig` defaults to enable SL/TP on every trade:

| Parameter | Current | Proposed | Rationale |
|-----------|---------|----------|-----------|
| `sl_pct` | `0.0` | `0.02` (2%) | Limits loss per trade; within V&R-threshold [0.001, 0.50] |
| `tp_pct` | `0.0` | `0.03` (3%) | 1.5:1 risk-reward; within [0.001, 10.0] |

Per-strategy defaults for `sma_cross` (already co-signed via ZTB-3455):
```python
params = {"fast": 5, "slow": 20, "sl_pct": 0.05, "tp_pct": 0.10}
```

**Precedence rule:** CLI `--sl-pct`/`--tp-pct` > strategy `params` > `ExecRunConfig` defaults.

Concrete: `executor.py` `_apply_sl_tp` call in `step()`:
- Default: `sl_pct=self.config.sl_pct, tp_pct=self.config.tp_pct`
- WITH per-strategy override: `sl_pct=strategy.params.get("sl_pct", self.config.sl_pct)`

### Change 4: Fix `feat/sltp-executor-precedence` (C2 gap)

Rebase `feat/sltp-executor-precedence` (commit `dd7d2b9`) onto current `main` preserving ALL PR #196 content (demo top-up cooldown + single-attempt).

Additions (already verified by ZTB-3455 co-sign):
1. Strategy params SL/TP override in `executor.py` `step()`:
   ```python
   sl_pct = self.strategy.params.get("sl_pct", self.config.sl_pct)
   tp_pct = self.strategy.params.get("tp_pct", self.config.tp_pct)
   ```
2. CLI `--sl-pct`/`--tp-pct` on `run`, `backtest`, `forwardtest` commands
3. Precedence: CLI > params > config

## Invariants

| # | Invariant | Verification |
|---|-----------|-------------|
| 1 | **Equity formula**: `equity = initial_cash + realized_pnl + unrealized_pnl` (never notional) | All existing equity tests pass; no PnLCalculator changes |
| 2 | **No look-ahead**: SL/TP prices computed from `avg_entry * (1 ± pct)` at fill time; no future data used | `_apply_sl_tp` called after fill with current `avg_entry` |
| 3 | **Fees + slippage**: SL/TP exit costs via synthetic fill with `commission`/`slippage` params | Same as current synthetic fill path |
| 4 | **Shared accounting**: Executor uses `PnLCalculator` — no parallel formula | No `PnLCalculator` changes in scope |
| 5 | **Default parity**: `sl_pct=0, tp_pct=0` → byte-identical output to current code | Parity test required |
| 6 | **Strategy independence**: `generate_signals` unchanged; SL/TP is executor-layer only | No strategy ABC changes |
| 7 | **Killswitch clearing**: Killswitch flattens → `_clear_sl_tp` called per symbol | Existing test `test_executor_killswitch_step_clears_all_sl_tp` |
| 8 | **Exchange SL/TP = external close**: Exchange-triggered SL/TP → `adopt_state(0, 0)` via reconcile — PnL from external fill not preserved locally | Existing reconcile path, no change |
| 9 | **SCHEMA_VERSION invariant**: `SCHEMA_VERSION` must equal `MAX(version) FROM schema_meta` | Assertion in `_run_migrations` |

## Required pytest Cases

| ID | Test | Owner | Status |
|----|------|-------|--------|
| FT-T1 | `test_sl_tp_placed_on_every_trade_with_defaults` — trade with default `sl_pct=0.02, tp_pct=0.03` → `client.set_trading_stop` called for every fill | Platform Engineer | New |
| FT-T2 | `test_sl_tp_cleared_on_position_close` — position closed (delta to 0) → `_clear_sl_tp` called | Platform Engineer | New |
| FT-T3 | `test_orphan_sl_tp_cleanup_on_startup` — exchange has SL/TP not in `_active_sl_tp` → orphan cleared | Already in close-gaps | Existing |
| FT-T4 | `test_clear_sl_tp_idempotency_delete` — after `_clear_sl_tp`, idempotency table has no SL/TP entries for that symbol | Platform Engineer | New |
| G-1 | `test_cleanup_orphan_sl_tp_clears_active_sl` | Already in close-gaps | Existing |
| G-2 | `test_clear_sl_tp_logs_warning_on_failure` | Already in close-gaps | Existing |
| G-3 | `test_clear_sl_tp_wired_to_killswitch` | Already in close-gaps | Existing |
| G-4 | `test_schema_version_equals_max_schema_meta` | Already in close-gaps | Existing |
| P-1 | `test_sltp_precedence_cli_overrides_strategy` — CLI `--sl-pct 0.01` > strategy params `0.05` > config `0.02` | Platform Engineer | New |
| P-2 | `test_sltp_zero_defaults_parity` — `sl_pct=0, tp_pct=0` produces identical results to current code | Platform Engineer | New |
| P-3 | `test_sltp_params_not_required_in_strategy` — strategy without `sl_pct`/`tp_pct` in params falls back to config default | Platform Engineer | New |

## Risk Thresholds (inherited from ZTB-3007 / ZTB-3455)

| Parameter | Min | Max | sma_cross default |
|-----------|-----|-----|-------------------|
| `sl_pct` | 0.001 | 0.50 | 0.05 |
| `tp_pct` | 0.001 | 10.0 | 0.10 |
| Config `sl_pct` default | — | — | 0.02 (proposed, V&R to confirm) |
| Config `tp_pct` default | — | — | 0.03 (proposed, V&R to confirm) |
| Price validation | SL must be below entry (long) / above entry (short); TP opposite | — | — |

## Build Order

1. V&R co-sign this contract (co-sign issue `ZTB-3541-co-sign`)
2. Platform Engineer builds on isolated worktree `~/ztb-wt/feat/sltp-enable`:
   - Rebase close-gaps content onto main
   - Fix `_clear_sl_tp` idempotency bug
   - Set default `sl_pct=0.02, tp_pct=0.03` in `ExecRunConfig`
   - Rebase + merge sltp-executor-precedence content onto main
   - Set sma_cross `sl_pct=0.05, tp_pct=0.10`
   - Write all 11 tests
   - Run full pytest suite — CI green
   - Builder self-audit checklist against this contract
3. Platform Engineer hands up to HoE
4. HoE reviews against contract + self-audit
5. Route to V&R via standing direct lane (CI-green + same SHA)
6. V&R PASS + CI green → ATOMIC MERGE via `ztb-atomic-merge.sh`
7. Version bump to v1.1.54 + tag + CHANGELOG

## WIP=1 Compliance

The `executor.py` / `bybit_client.py` changes are consolidated into ONE branch/PR (`feat/sltp-enable`). No competing PR touches these files simultaneously. All 4 changes (close-gaps, idempotency, defaults, precedence) ship together.
