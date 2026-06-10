# M6 Execution Module (DEMO)

## Architecture

The execution module bridges the gap between paper backtesting and live trading.
It runs a deterministic tick pipeline against the Bybit demo exchange:

```
Data (closed bar) → Signal → Reconcile → Risk Gate (M5) → Diff → Round →
Idempotent Place/Amend/Cancel → Re-Reconcile → Persist → Notify
```

### Module structure

| File | Purpose |
|------|---------|
| `models.py` | Typed dataclasses: `Order`, `Fill`, `Position`, `AccountState`, `ExecRunState`, `ExecRunConfig`, `Mode` |
| `errors.py` | Typed errors: `LiveModeBlockedError`, `RiskRejectedError`, `ClientError`, `ClientAuthError` |
| `bybit_client.py` | Signed REST v5 client (HMAC-SHA256); demo URL hard-pinned |
| `idempotency.py` | `orderLinkId` from stable tuple; SQLite dedupe ledger |
| `reconcile.py` | `ReconcileReport`, `compute_account_state`, `reconcile_account` |
| `executor.py` | `Executor` class: `step()` and `run()` pipeline |

## Idempotency design

Execution-order idempotency keys derive from the **stable tuple**
`(strategy, symbol, bar_ts, intent_hash)` — **NEVER** the ephemeral `run_id`.

- `intent_hash = sha256("sig={signal:.8f}:pos={current_position:.8f}")[:16]`
- `orderLinkId = sha256("strategy:symbol:bar_ts:intent_hash")[:40]`

A restart, rollback, or re-issue produces the identical key, so crash-recovery
never double-fills. The SQLite `idempotency` table enforces uniqueness at the
DB level.

## Demo lock

In M6, `--mode=live` raises `LiveModeBlockedError`. The demo URL is
hard-pinned to `api-demo.bybit.com`. This is a compile-time safety — no code
path reaches mainnet.

## Risk gate integration

Every execution tick routes the target signal through M5's `RiskManager.evaluate()`:

1. Kill-switch check (account DD ≥25% → halt + flatten)
2. Leverage cap
3. Position size cap
4. Heat/correlation check
5. DD budget scalar

A risk `halt` or `reduce` is honored before order placement. If the risk
manager rejects the order, `RiskRejectedError` is raised — no order is placed.

## CLI reference

```
ztb run <strategy> <symbol> [--mode demo] [--timeframe 60] [--category linear]
        [--start DATE] [--end DATE] [--cash 100000] [--dry-run] [--once]
        [--no-risk] [--db PATH]

ztb reconcile [--exec-run-id ID] [--db PATH]
```

The `run` command processes closed bars one by one, generating signals, checking
risk, and placing market orders on the Bybit demo exchange. Use `--dry-run` to
simulate without placing real orders. Use `--once` to process only the most
recent bar.

The `reconcile` command fetches current account state from the exchange and
optionally compares it against a previous execution run.

## Store schema (migration v4)

New tables added to the SQLite store:

- `exec_runs` — execution run metadata (strategy, symbol, mode, status)
- `exec_orders` — placed orders (orderId, orderLinkId, status, fills)
- `exec_fills` — fill events (execId, price, qty, commission, PnL)
- `exec_positions_snapshots` — position snapshots per bar
- `exec_pnl_ledger` — running PnL ledger
- `exec_errors` — execution error log
