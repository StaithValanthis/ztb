# ztb — Product Specification

> Source of truth: `docs/playbook/01-MASTER-PLAN.md` (the definitive build playbook) and `docs/playbook/00-README.md`. This PRODUCT.md is the distilled product spec; where it and the master-plan disagree, the master-plan wins. Two reconciliations from `00-README.md` are applied throughout: the deployment target is Linux `~/zero-alpha` (not the Windows build-host path), and the API model is `deepseek-v4-flash`.

## 1. What ztb is

`ztb` is **Zero Alpha's single, reusable, deterministic trading-bot PLATFORM for Bybit only** — one engine, with strategies as plugins. It is **never** a collection of per-strategy scripts; legacy per-strategy scripts are the anti-pattern ztb replaces and are out of scope.

The platform is three parts on top of one engine:

- **Engine** — a deterministic, cost-realistic Python backtest/forward-test/execution core.
- **Streamlit dashboard** — a read-only operator view (localhost `127.0.0.1:8501`).
- **Strategy plugins** — alpha candidates authored against a stable `Strategy` ABC contract.

It is **fully Python**. There is **no MCP and no TradingView** in the product — no external signal services, no per-strategy glue. Everything (data, indicators, backtest, metrics, store, reporting, risk, execution) lives inside the `ztb` package and runs through the `ztb` CLI.

**Scope: Bybit only** — spot, USDT/USDC/inverse perps, USDC options, leveraged tokens, spot margin, Earn. Never equities or any other venue. (The build narrows further per milestone; execution in M6 is **linear USDT perps + spot only**, with the other Bybit venues deferred as backlog lessons.)

**Demo-only until armed.** The platform runs in `demo` mode by default and stays demo until the human Board explicitly arms live money. No agent ever flips that flag.

### Doctrine (the soul)
Build a proven, durable, cheap, mostly self-sufficient machine. **Survival first.** Evidence is the gate. **Cost realism is mandatory; never fabricate numbers.** Engine-first (M0–M3 build and prove the machine, dogfooded by a trivial reference strategy) before hunting alpha. ≥100%/12mo is great; ≥20%/12mo is the floor (a doctrine aspiration, **not** an arming precondition).

## 2. Package layout

The `ztb/` package (PEP 621 `pyproject.toml`, entry point `ztb = ztb.cli:main`, single-sourced `__version__`):

```
ztb/
  __init__.py        # single-source __version__
  config.py          # frozen Config; mode defaults "demo"; secrets env-only, never in repr/serialization
  cli.py             # dispatcher: data | backtest | forwardtest | validate | run | report | dashboard | list
  data/              # M1 — Bybit public REST v5, rate-limit, pagination, schema, cache, integrity, loader
  features/          # M2 — pure vectorized indicator library
  strategies/        # M2 — Strategy ABC (base.py), registry.py, plugins (e.g. sma_cross.py)
  engine/            # M2+ — backtest.py, metrics.py, portfolio.py, forwardtest.py, ft_state.py, ft_decay.py
  risk/              # M5 — types, config, limits, heat, sizing, killswitch, manager
  execution/         # M6/M7 — models, bybit_client (demo-pinned), idempotency, reconcile, executor, live_guard, killswitch
  reporting/         # M3+ — format, scorecard, notify, health
  store/             # M3+ — schema.sql, results.py (SQLite), additive ft/risk/exec IO
  dashboard/         # M3+ — Streamlit app.py (read-only), data_access, components
```

Repo conventions: deployed at Linux `~/zero-alpha`; private GitHub remote `zero-alpha/ztb`; SemVer tags on `main`; branches `feat/*`, `fix/*`, `strat/*`; secrets gitignored and env-only. `ztb run` executes a **pinned tag**; rollback = `git checkout <prev tag>`.

## 3. The M0 → M7 milestone ladder

Each milestone ends in a **tagged, CI-green, V&R-PASSED** release on `main`. The merge gate is two-key: **CI-green on the PR head commit AND a recorded V&R PASS on the identical SHA.** Every DoD also requires: lockfile current, secret-scan clean, docs shipped, CHANGELOG + `__version__` bumped to the tag.

| Milestone | Tag | Theme | What it delivers |
|---|---|---|---|
| **M0** | `v0.1.0` | **Scaffold + CI** | Typed empty `ztb/` package skeleton; `config.py` (frozen `Config`, `mode="demo"`, env-only secrets); `cli.py` dispatcher (8-command stub surface, real `--version`/`--help`); `pyproject.toml` + **lockfile**; pre-commit (ruff + mypy + fast-unit + **secret-scan**); CI (3.11+3.13 matrix: lint, types, pytest `--cov-fail-under=90`, secret-scan, version-consistency); CHANGELOG/README/LICENSE. |
| **M1** | `v0.2.0` | **Data layer** | `ztb/data/` — Bybit public REST v5 (kline, funding, instruments, server time), token-bucket rate-limit + backoff, pagination (1000-bar window walk + dedupe), canonical OHLCV schema (UTC index, float64), parquet cache (atomic `os.replace`, incremental latest-wins), integrity (gap/dupe/monotonicity/**freshness**), `loader.load()` contract with **cold==warm determinism**. CLI `ztb data fetch|show|verify|instruments`. |
| **M2** | `v0.3.0` | **Backtest engine + plugin framework + metrics + indicators + reference strategy** | `strategies/base.py` (the `Strategy` ABC), `strategies/registry.py` (auto-discovery), `features/indicators.py` (pure vectorized), `engine/backtest.py` (`run_backtest`, cost model, IS/OOS split, credible-sample guard, `BacktestResult`), `engine/metrics.py` (net metrics), `engine/portfolio.py` (minimal single-symbol passthrough; real aggregation in M5), `strategies/sma_cross.py` (trivial reference). CLI `ztb list`, `ztb backtest`. |
| **M3** | `v0.4.0` | **Reporting + result store (SQLite) + scorecard + Streamlit dashboard** | `ztb/store/` — `schema.sql` (additive, `schema_meta`), `results.py` (`connect` WAL+FK, atomic `save_run`, accessors incl. named `get_oos_metric(run_id, name)`); tables `runs`/`metrics(scope∈{is,oos,full})`/`trades`/`equity_curve`. `ztb/reporting/` — single-source thresholds, pure `scorecard`, fail-soft `notify` (never leaks a secret). `ztb/dashboard/` — Streamlit `app.py`, **read-only** (`mode=ro`), `127.0.0.1:8501`, under a Board-owned `ztb-dashboard.service`. CLI `backtest --persist`, `report`, `dashboard`. |
| **M4** | `v0.5.0` | **Forward-test runner — ENGINE-VALIDATION ONLY** | `engine/forwardtest.py` (`ForwardTester` + `run_tick`), `engine/ft_state.py` (resumable, atomic JSON, integrity hash), `engine/ft_decay.py` (pure decay). Shared cost/metric primitive (no re-implementation). Additive `schema_ft.sql` + `ft_io.py`; SQLite is source of truth. CLI `forwardtest start|tick|status|stop|list`. Systemd `oneshot` + timer (`Persistent=true`, single-flight lock). Alert catalog lands here (process-down, data-staleness→kill path, decay breach, reconcile-freshness → each auto-creates a task). |
| **M5** | `v0.6.0` | **Risk module** | `ztb/risk/` — `types`, frozen `RiskConfig` (`max_portfolio_dd=0.25`, `account_killswitch_dd=0.25`, vol target, leverage/position/heat/corr caps), `limits` (Bybit tick/step/min-notional/leverage), `heat` (vol, rolling corr, heat `√(wᵀΣw)`), `sizing` (vol-target + `dd_budget_scalar` + heat cap), `killswitch` (HWM, 25% trip, cooldown, flatten), `manager.evaluate(...) -> RiskDecision` (single pure seam). `engine/portfolio.py` grows into real multi-symbol aggregation. Both engines route every order through `evaluate()` (default risk-ON; `--no-risk` for A/B baselines only). |
| **M6** | `v0.7.0` | **Execution (DEMO)** | `execution/` — typed `models`, `bybit_client` (signed REST; **demo URL hard-pinned `api-demo.bybit.com`; `mode=LIVE` raises `LiveModeBlockedError`**; HMAC-SHA256, idempotent retries on network/5xx only), `idempotency` (`orderLinkId` from stable `(strategy, symbol, bar_ts, intent_hash)`, **never `run_id`**), `reconcile` (drift/orphan/missing-fill detect+repair; irreconcilable→kill), `executor` (data→signal→reconcile→**risk gate**→diff→round→idempotent place→re-reconcile→persist→notify). Append-only `exec_io`. CLI `ztb run --mode demo [--dry-run] [--once]`, `ztb reconcile`; refuses non-demo. Scope: linear USDT perps + spot. |
| **M7** | `v1.0.0` | **Live-ready (Board-armable, DISARMED by default)** | HARDEN client/executor/reconcile; NEW `execution/live_guard.py` (arming gate; reads Board `ZTB_LIVE_ARMED` + signed `live_arm.json`; **default disarmed**; live path asserts `is_armed()` or `LiveDisarmedError`; no auto-arm; refuses to arm unless preflight all-PASS); NEW unified `execution/killswitch.py` (account-DD 25%, portfolio-DD 25%, reconcile-drift, **data-staleness**, heartbeat-stale, manual → cancel-all + flatten + halt + notify + persist). `ztb run` pins/verifies the released tag; `ztb rollback <tag>`; `ops/preflight.py`; `reporting/health.py`; read-only Live dashboard page (no trade/arm control, **unreachable off-host**). Runbooks `go-live.md`, `incident-rollback.md`. **Live money remains DISARMED pending a separate explicit Board action.** |

**Dependency spine:** `M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7`. Build the ruler before measuring; calibrate on the trivial reference strategy whose answer you already know; only then measure unknown alpha.

**Critical sequencing truth (§0.3):** **M4's forward-test runs are ENGINE-VALIDATION ONLY** (identity `sizing_fn` seam, no risk overlay) — they prove the runner is deterministic/resumable, and are **not** go-live evidence. The **go-live-qualifying forward-test is re-run after M5** with risk + kill-switch ACTIVE. A pre-risk forward-test can never be presented as go-live proof.

## 4. The Strategy ABC plugin contract

Every plugin subclasses the `Strategy` ABC in `strategies/base.py`. The contract (V&R-reviewed before any plugin code):

- **Attributes:** `name`, `symbols`, `timeframe`, `params`, `warmup`.
- **`generate_signals(df) -> pd.Series`** returns a **target position** in **[-1, 1]** indexed to the input bars: `-1` = fully short, `0` = flat, `+1` = fully long.
- **Warmup-flat:** the strategy must emit `0` (flat) across its warmup window; non-zero signals inside warmup are rejected.
- **No-NaN:** the returned series must contain no NaNs.
- **The engine owns the 1-bar shift.** A target computed from bar *t*'s close executes at bar *t+1*. **Strategies never shift** — shifting in a plugin is forbidden, because the engine already applies the shift. This is the single guarantee that makes look-ahead structurally impossible.
- **Plugins are plugins only** — no engine edits. They are authored on `strat/<name>` branches and discovered by the registry (`get` / `all` / `list_names`; duplicate names raise; ABC violations are rejected).

The trivial **reference strategy** `sma_cross` (long-or-flat) exists to dogfood and calibrate the engine — not as alpha.

## 5. Engine truths

These are the engine's non-negotiable invariants — they are what make a ztb result count as evidence:

- **Cost realism (net of commission + slippage).** Cost at bar *t* = `(commission + slippage) · |posₜ − posₜ₋₁|` (turnover-based; charged on open, flip, and close). **All reported metrics are net.** Short flips (`+1 → −1`) are charged on the full turnover and PnL-signed correctly. PnL in execution includes real demo commission + observed slippage — **never fabricated**.
- **No look-ahead.** The engine — not the strategy — applies the 1-bar shift; perfect-foresight signals are provably defeated; truncate-at-k invariance holds for indicators.
- **Determinism.** Identical inputs produce byte-identical outputs. Cached data is **cold == warm** (`assert_frame_equal`). The forward-tester matches the backtester on the same bars to ≤1e-9 (equity / #trades / fees / return), using a **single shared cost+metric primitive** (no duplicate Sharpe/fee code).
- **Credible-sample guard.** Below configured `min_bars` / `min_trades` (~**≥30 trades** for a credible sample, on OOS) the result is marked `credible=False` with a reason. The engine returns the **real** numbers, never fabricated ones; zero-trade cases return `None` + `credible=False`.
- **IS/OOS split.** A chronological in-sample / out-of-sample split (fraction ~0.7) is reported for **full / IS / OOS**, so leaderboards and decay logic agree via the frozen named accessor `get_oos_metric(run_id, name)`.
- **Risk floor (M5).** The 25% account kill-switch is the **hard floor** (proven, including an adversarial gap-down case the `dd_budget_scalar` can't cover). `dd_budget_scalar` is a best-effort target — proven to reduce DD vs `--no-risk`, but not guaranteed `<25%` under gap risk.
- **Honesty.** Every Board-facing number is reproducible via `ztb report` from the SQLite store. If it can't be regenerated, it doesn't exist. The store is the track record.

## 6. Demo-only until armed

The platform is **demo-safe by construction**:

- `Config.mode` defaults to `"demo"`; secrets are env-only and confined to `execution/`, gitignored, never read before M7 arming.
- M6's client hard-pins the demo URL `api-demo.bybit.com` and raises `LiveModeBlockedError` on any live attempt.
- M7 adds `live_guard.py`: **disarmed by default**, no automatic arm path, refuses to arm unless the full preflight passes, and every live code path asserts `is_armed()` or raises `LiveDisarmedError`.
- The **human Board is the only party that can arm live money**, per-strategy and per-size, against a single pinned tag, after `v1.0.0`. First-live size is tiny by policy. `v1.0.0` ships **DISARMED**.

## 7. Build & runtime context

- **Deployment target:** Linux `~/zero-alpha`; private remote `zero-alpha/ztb`.
- **Cost discipline:** the firm runs on the `deepseek-v4-flash` API model (thinking on/off; the older `deepseek-chat` / `deepseek-reasoner` are deprecating aliases to repoint before 2026-07-24) under a ≤ $50 AUD/month cap (~$1–5 AUD/mo expected). "Reasoner vs chat" remains only a quality distinction (thinking vs non-thinking).
- **Process discipline (§0.8):** the only long-lived processes are `ztb run` and Board-owned systemd services (dashboard, cost-guard, notifier). No agent spawns a daemon; tick-style work runs as `Type=oneshot` units on systemd timers that tick-and-exit.

---

**The through-line:** one reusable engine; strategies are plugins; evidence at every gate; cost-realistic and demo-safe; survival first — **capital earned, never assumed.**
