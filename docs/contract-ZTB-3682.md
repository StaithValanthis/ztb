# ZTB-3682 Frozen Contract: Fill-pipeline test-coverage gaps

## Scope

**File:** `tests/test_execution_executor.py` ONLY — NO changes to `ztb/execution/executor.py`, `bybit_client.py`, `data/loader.py`, or any engine code.

**Mode:** All tests unit-level with `@patch` + `MagicMock` — no network, no real exchange.

## Pre-existing coverage (DO NOT re-test)

These tests already exist and pass. Do not duplicate:

| Test | Line | What it covers |
|------|------|---------------|
| `test_real_fills_saved_when_exchange_returns_fills` | 4747 | fills saved to exec_fills |
| `test_both_order_and_fill_persisted_together` | 4795 | both tables get rows |
| `test_synthetic_fill_saved_when_no_exchange_fills` | 4666 | synthetic fallback |
| `test_synthetic_fill_commission_matches_order` | 4705 | commission matches config |
| `test_poll_fills_returns_fills_on_first_attempt` | 4840 | fast path |
| `test_poll_fills_retries_and_finds_fills_on_second_attempt` | 4883 | retry |
| `test_poll_fills_exhausts_attempts_and_falls_back_to_synthetic` | 4934 | exhaustion |
| `test_poll_fills_handles_api_error_and_retries` | 4975 | exception retry |
| `test_poll_fills_aborts_early_on_sigterm` | 5041 | SIGTERM |
| `test_poll_fills_runs_in_demo_mode` | 5086 | demo mode |

## 4 gaps to close

### Gap A: FillFetchError saved on exhaustion

**Location:** After the existing exhaustion test or as a new test at end of file.

When `_poll_fills` returns empty for a MARKET order (all attempts exhausted):
- `step()` must produce `real_fills` empty or absent in result
- The `exec_errors` table must contain a row with error_type = `"FillFetchError"` for this exec_run_id
- `exec_fills` table must have a synthetic fill (existing behavior — add paired assertion)

**Store query pattern:**
```python
from ztb.store.exec_io import get_exec_fills
from ztb.store.exec_io import get_exec_run
errors = exe._store_conn.execute(
    "SELECT * FROM exec_errors WHERE exec_run_id = ? AND error_type = 'FillFetchError'",
    (exe._exec_run_id,),
).fetchall()
assert len(errors) >= 1
```

### Gap B: Limit lifecycle dual-path

**Location:** New section at end of file, after existing fill tests.

Test `Executor._execute_limit_lifecycle()` through the end-to-end `step()` with `use_limit=True`:

**B1 — Limit fully fills, no market fallback:**
- `config.auto_use_limit = True` (or set `order_type=Limit` strategy override)
- `get_executions` returns 2 fills on first call, empty on second (pre/post cancel)
- After `step()`: `exec_orders` row has `order_type="Limit"`, `cum_exec_qty` = sum of fills, `cum_exec_fee` = sum of commissions
- `exec_fills` has 2 rows, both with `order_link_id` matching the exec_order
- `place_order` called once (limit), `cancel_order` called, `poll_fills` called twice (pre + post), `get_executions` called 2×
- No `Limit+Market` or second `place_order` call

**B2 — Limit partially fills, market fallback fills remainder:**
- `get_executions` returns 1 fill for 0.5 qty pre-cancel
- `limit_fallback_market = True`
- After `step()`: `exec_orders` has `order_type="Limit+Market"` or `"Market"`, two `place_order` calls
- `exec_fills` rows cover both limit fill and market fill
- `cum_exec_qty` = sum of all fill qtys

**B3 — Limit fully unfilled with fallback disabled:**
- `get_executions` returns empty (no fills)
- `limit_fallback_market = False` (default)
- After `step()`: `result["order_unfilled"]` is True, NO synthetic fill, `exec_fills` table empty
- `cancel_order` still called

### Gap C: _poll_fills all-attempts exception

**Location:** Near existing `test_poll_fills_handles_api_error_and_retries`.

`get_executions` raises on EVERY attempt (not just first):
- `poll_fill_max_attempts = 3`, `side_effect = [Exception("API err"), Exception("API err"), Exception("API err")]`
- After `step()`: `real_fills` absent/empty, `get_executions.call_count == 3`
- Synthetic fill still created (market path fallback)
- `exec_errors` table has error row

### Gap D: Quantitative exec_orders/exec_fills reconciliation

**Location:** Near existing `test_both_order_and_fill_persisted_together` or as standalone.

When `get_executions` returns 2 fills for the same order:
- Fills: `[{"execId":"f1","qty":"0.001","execFee":"0.05","execPrice":"50001"}, {"execId":"f2","qty":"0.002","execFee":"0.10","execPrice":"50002"}]`
- Verify `get_exec_orders(conn, run_id)` returns 1 row
- Verify `get_exec_fills(conn, run_id)` returns 2 rows with matching order_link_id
- Verify `orders[0]["cum_exec_qty"]` == sum(f.qty for f in fills) ≈ 0.003
- Verify `orders[0]["cum_exec_fee"]` == sum(f.commission for f in fills) ≈ 0.15
- Verify `orders[0]["cum_exec_value"]` == sum(f.price * f.qty for f in fills)
- Verify `orders[0]["status"]` == "Filled"

## Pattern reference

Every test follows this skeleton:

```python
@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_my_new_test(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = [...]
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.LIVE, dry_run=False, risk_enabled=False, ...)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    # assertions

    from ztb.store.exec_io import get_exec_orders, get_exec_fills
    orders = get_exec_orders(exe._store_conn, exe._exec_run_id)
    fills = get_exec_fills(exe._store_conn, exe._exec_run_id)
    # store assertions
```

## Self-audit checklist (BEFORE hand-up)

- [ ] NO changes to `ztb/execution/executor.py`, `bybit_client.py`, `data/loader.py`
- [ ] All tests use mocks — no network calls
- [ ] Tests follow existing pattern (conftest fixtures, sample_data, mock_bybit_cls)
- [ ] `ruff format .` run on test file
- [ ] `ruff check --fix .` passes
- [ ] `mypy --strict ztb/` passes
- [ ] `python -m pytest tests/test_execution_executor.py -k "test_my_new_test" -v` passes for each new test
- [ ] `python -m pytest tests/test_execution_executor.py -v` — no regressions
- [ ] All work committed + pushed to a branch
- [ ] PR created against main with this contract linked
