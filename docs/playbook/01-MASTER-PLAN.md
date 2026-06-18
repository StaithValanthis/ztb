# ztb — Master Implementation Plan (Definitive Build Playbook)

**Product:** `ztb` — Zero Alpha's single, reusable, deterministic Python trading engine for **Bybit only** (spot, USDT/USDC/inverse perps, USDC options, leveraged tokens, spot margin, Earn — never equities or other venues). One engine; strategies are plugins. Never per-strategy scripts.

**Doctrine (the soul):** build a proven, durable, cheap, mostly self-sufficient machine. Survival first. Evidence is the gate. Cost realism is mandatory. Never fabricate numbers. Engine-first (M0–M3 build and prove the machine, dogfooded by a trivial reference strategy) before hunting alpha. Demo until the human Board arms live money. ≥100%/12mo is great, ≥20%/12mo is the floor.

---

## 0. Canonical Decisions (fixed once, referenced everywhere — applies critique fixes #1, #4, #12)

These resolve the cross-draft contradictions the audit found. Frozen before M0 closes; every milestone references them.

### 0.1 Canonical repo root and remote (fix #12)
- **Repo root (build host):** `C:\Users\User\Self-Improving Trading Agent`
- **GitHub remote:** `zero-alpha/ztb` (private). Ops creates it in M0 and confirms Actions + branch protection.
- Legacy per-strategy scripts on the host are the **anti-pattern ztb replaces** — out of scope; never extended.

### 0.2 Canonical milestone → release-tag map (fix #1)
Single source of truth for versioning. SemVer; each milestone is a tagged, V&R-PASSED release on `main`. `ztb run` executes a **pinned tag**; rollback = `git checkout <prev tag>`.

| Milestone | Tag | Theme |
|---|---|---|
| M0 | `v0.1.0` | Scaffold + CI |
| M1 | `v0.2.0` | Data layer |
| M2 | `v0.3.0` | Backtest engine + plugin framework + metrics + indicators + reference strategy |
| M3 | `v0.4.0` | Reporting + result store + scorecard + Streamlit |
| M4 | `v0.5.0` | Forward-test runner |
| M5 | `v0.6.0` | Risk module |
| M6 | `v0.7.0` | Execution (DEMO) |
| M7 | `v1.0.0` | Live-ready (Board-armable, disarmed by default) |

Any plan citing a different tag is stale and yields to this table.

### 0.3 Sequencing correction — risk-aware proof (fix #2)
Spine: `M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7`. M4 builds the forward-test *machine* before the risk module exists, so:
- **M4's forward-test runs are ENGINE-VALIDATION ONLY** (identity `sizing_fn` seam, no risk overlay). They prove the runner is deterministic/resumable. They are **not** go-live evidence.
- **The go-live-qualifying forward-test is re-run after M5** with risk + kill-switch ACTIVE. Only a risk-active forward-test counts as track-record evidence to the Board. A pre-risk forward-test can never be presented as a go-live proof.

### 0.4 The merge gate is CI-green AND V&R-PASS on the same SHA (fix #3)
Every PR, every milestone:
1. CI green on the **PR head commit** (lint + types + full pytest + secret-scan + version-consistency). A red CI never reaches V&R.
2. **V&R runs `ztb smoke-test --timeout 60` as a manual precondition** before recording a PASS. The smoke-test exercises the full execution pipeline against the Bybit DEMO exchange (places a real MARKET BUY, retrieves fills, validates commission + price scaling + store persistence + FK consistency). CI cannot run the smoke-test due to CloudFront geographic restrictions on GitHub Actions runners.
3. Head of V&R PASS recorded **against that same SHA**.
4. Head of Eng's merge requires **both** (CI-green + V&R PASS), verified against the identical commit. Branch protection on `main` enforces require-PR-+-green-CI.

### 0.5 Secrets & supply-chain owners from day one (fixes #4, #6)
- **Secrets:** Head of V&R owns policy ("no secret in diff / logs / scorecard / Discord payload / dashboard frame" on code-review + go-live checklists). Ops Engineer owns mechanics (pre-commit secret-scan + CI secret-scan from M0; demo/live keys confined to `execution/`, env-only, gitignored). Live keys never read outside `execution/` and never before M7 arming.
- **Dependencies:** Platform Engineer adds a **lockfile** (reproducible runtime + dev closure) to M0's DoD. Ops runs a $0 systemd-timer CVE/dep-drift check that **creates a task** on a finding.

### 0.6 Schema is versioned-and-additive, never "frozen" (fixes #15, #16)
The SQLite store (M3) ships with `schema_meta(schema_version)` and is **additively extensible** (`CREATE TABLE IF NOT EXISTS`). M4/M5/M6 add tables/columns via guarded additive migrations, never destructive rewrites. The OOS-metric accessor is frozen as a **named function** (`get_oos_metric(run_id, name)` / `get_oos_sharpe(run_id)`), not a column name, so M4 decay and M3 leaderboards agree. "Frozen" → "stable + additively-versioned."

### 0.7 Restart-safe idempotency (fix #21)
Execution order idempotency keys derive from a **stable tuple** `(strategy, symbol, bar_ts, intent_hash)` — **never** the ephemeral `run_id`. A restart/rollback must not change the key, or crash-recovery double-fills. M6's restart test asserts this.

### 0.8 Long-lived processes are sanctioned only (fix #19, rails)
The ONLY long-lived processes are `ztb run` and Board-owned systemd services (Paperclip server, Streamlit dashboard, cost-guard, notifier). **No agent ever spawns a daemon/routine/OS task.** Tick-style work (forward-test, dep-check, network smoke) runs as `Type=oneshot` units on systemd timers that tick-and-exit. The M6/M7 sustained demo "loop" IS `ztb run` in demo mode under a Board-owned unit — not an agent babysitting a loop.

---

## 1. Org & Ownership — does the 10-agent firm cover every lifecycle function?

**Verdict:** Yes, with the audit's clarifications. No new headcount — the firm stays at 10. Every gap closes by (a) making implicit ownership explicit, (b) folding a discipline into an existing agent's definition-of-done, or (c) assigning the event-detector the doctrine already assumes. The two safety-critical gaps — **secrets (G2)** and **the CI gate (G1)** — close in M0, before any live trajectory.

### 1.1 The 10 agents
- **Managing Director** [reasoner] — hub; routes work to Heads; Board interface; incident commander; does no R&D himself.
- **Head of Research** [reasoner] → **Market Analyst** [chat] — Analyst scans Bybit + regime-checks + surfaces edges; Research writes plugin SPECs, owns registry + lessons ledger, enforces the 3-candidate cap.
- **Head of Engineering** [reasoner] — owns ztb architecture, roadmap, versioning/releases; merges to `main` only on CI-green + V&R PASS; cuts tagged releases + CHANGELOG → **Platform Engineer** [chat] (builds ztb core + the engine pytest suite) + **Strategy Engineer** [chat] (writes plugins, runs `ztb backtest`).
- **Head of Validation & Risk** [reasoner; INDEPENDENT of Engineering] — owns the evidence gate, code review, risk framework, go-live checklist, track-record judgment; her PASS is the merge gate → **Validation Engineer** [chat] (OOS/robustness re-runs, code review, engine-test-suite audit).
- **Head of Operations** [chat] — runtime/systemd, git-repo + CI, cost-watch, live-incident triage → **Ops Engineer** [chat] (hands-on infra/health/cost/secret-mechanics fixes).

### 1.2 Owner table (with audit clarifications applied)

| Lifecycle function | Primary owner | Backstop / gate | Audit clarification |
|---|---|---|---|
| Edge discovery, regime scan | Market Analyst | Head of Research | — |
| Strategy specs, registry, lessons ledger, 3-candidate cap | Head of Research | MD | — |
| ztb architecture, roadmap, versioning | Head of Engineering | Head of V&R | — |
| Data engineering (REST kline+funding, cache, loader) | Platform Engineer | Validation Engineer | **+ data integrity/freshness gate (G7)** |
| Engine core (backtest, metrics, portfolio, indicators) | Platform Engineer | Head of Engineering | — |
| Strategy plugin authoring + backtests | Strategy Engineer | Head of Research (spec) | — |
| Engine test suite (pytest = foundation) | Platform Engineer (writes) | Validation Engineer (audits) | — |
| Independent validation (OOS, robustness, review) | Validation Engineer | Head of V&R | — |
| Evidence gate / merge approval | Head of V&R | — (independent) | — |
| Release management (merge, tag, CHANGELOG, SemVer) | Head of Engineering | Head of V&R | — |
| **CI/CD pipeline (build, tests-on-PR, branch protection)** | **Ops Engineer (builds)** | **Head of Engineering (gatekeeper)** | **G1: CI-green on PR head = precondition to V&R review** |
| DevOps / runtime (systemd, git, health) | Head of Operations | Ops Engineer | — |
| Cost watch / circuit-breaker | Head of Operations | Ops Engineer | — |
| Risk framework + sizing/kill-switch | Head of V&R | Platform Engineer (impl) | — |
| Execution (DEMO client, executor, reconcile) | **Platform Engineer (core) + Strategy Engineer (signal→order)** | Head of V&R (go-live) | **G6: named builders firm-wide** |
| Reporting, scorecard, dashboard | Platform Engineer | Head of Research | — |
| Result store / track record (SQLite) | Platform Engineer | Head of V&R | — |
| **Track-record / live-decay analysis** | **Market Analyst (watch)** | **Head of V&R (adjudicate)** | **G8: live-decay watcher owned** |
| **Security / secrets** | **Head of V&R (policy) + Ops Engineer (mechanics)** | Head of Ops | **G2: owned from M0** |
| **Dependency / supply-chain** | **Platform Engineer (lockfile) + Ops Engineer (CVE timer)** | Head of Eng | **G3: lockfile in M0 DoD** |
| **Monitoring / alerting catalog** | **Head of Operations (defines) + Ops Engineer (implements)** | MD | **G4: alert→auto-task mapping** |
| **Documentation (engine/plugin/CLI/runbooks)** | **Head of Engineering** (docs ship with the tag) | Head of Research (lessons ledger) | **G5: docs in milestone DoD** |
| Incident command | MD (commander) + Head of Ops (triage) | Head of V&R | — |
| Continuous-improvement / anti-drift | MD (2-day review) | Head of Research (ledger catch-all) | **written close-out each cycle** |
| Routing / Board interface | Managing Director | — | — |

### 1.3 Responsibilities the audit added/clarified
G1 CI gate (CI-green on PR head precedes V&R; two-key merge on the same SHA); G2 secrets owned from M0; G3 lockfile + CVE timer; G4 alert catalog (process-down, data-staleness, decay breach, reconcile mismatch, heartbeat loss → each auto-creates a task; lands by M4); G5 "docs updated" in every milestone DoD; G6 named execution builders; G7 data integrity/freshness in M1 loader, staleness alarm → kill path in M4/M6/M7; G8 Analyst decay watch → V&R task; anti-drift: 2-day review yields a written close-out (tag / ledger-id / PR-link), else flagged.

---

## 2. Step-by-Step Build, M0 → M7

Each milestone ends in a tagged, CI-green, V&R-PASSED release. Every DoD also includes: lockfile current (§0.5), secret-scan clean, docs shipped (G5), CHANGELOG + `__version__` bumped to the §0.2 tag.

### M0 — Scaffold + CI → `v0.1.0`
**Dependencies:** none (root). External only: Python ≥3.11 (3.13 present), git, the `zero-alpha/ztb` remote (Ops).

**Deliverables:** `ztb/` package with empty-but-typed module dirs (`config`, `data/`, `features/`, `strategies/`, `engine/`, `risk/`, `execution/`, `reporting/`, `store/`); `ztb/__init__.py` (`__version__="0.1.0"`, single source, dynamic into `pyproject`); `ztb/config.py` (frozen `Config`, `mode` defaults `"demo"`, secrets env-only + excluded from repr/serialization, `load_config()` precedence defaults<TOML<env); `ztb/cli.py` (dispatcher; full stub surface `data|backtest|forwardtest|validate|run|report|dashboard|list`; real `--version`/`--help`); `pyproject.toml` (PEP 621, pinned dev tools, entry point `ztb=ztb.cli:main`); **lockfile**; `.gitignore` (secret-first); `.pre-commit-config.yaml` (ruff + mypy + fast-unit subset + **secret-scan** — full pytest CI-only, fix #17); `.github/workflows/ci.yml` (3.11+3.13 matrix: ruff, ruff-format, mypy, pytest --cov-fail-under=90, **secret-scan**, **version-consistency**); `CHANGELOG.md`; `README.md`; `LICENSE`; `ztb.config.example.toml`.

**Key tasks (ordered):** `.gitignore` FIRST → skeleton → `pyproject`+lockfile+verify `pip install -e .[dev]` → `config.py` → `cli.py` → test harness → ruff/mypy clean → pre-commit (incl. secret-scan) → CI (Ops creates remote + branch protection in parallel) → CHANGELOG/README (incl. release/rollback) → `feat/m0-scaffold` PR → CI green on head → V&R PASS → merge + tag `v0.1.0`.

**Required tests:** `test_version` (SemVer == `importlib.metadata.version`); `test_package_imports` (all submodules import, no side effects, `py.typed`); `test_config` (defaults; `mode=="demo"`; TOML override; env precedence; **secret hygiene** — never in repr/str/asdict, absent when unset; purity/no-network; invalid mode→`ValueError`); `test_cli` (`--version`→0; dispatch completeness over the 8 commands; stubs return documented not-implemented code; `main`→int no `SystemExit`); console-script subprocess smoke. Coverage ≥90%.

**DoD:** clean-venv install; `ztb --version`→`0.1.0`; 8 subcommands registered; pytest green ≥90%; ruff/mypy clean; pre-commit reproduces CI incl. secret-scan; CI green both Pythons on PR head; `.gitignore` blocks secrets/data/caches, `git log -p` no credential; version single-sourced; lockfile committed; docs present; **tag `v0.1.0` with CI-green + recorded V&R PASS IS done.**

**Who:** Head of Eng (layout/CI design, merge+tag). Platform Eng (skeleton, config, cli, pyproject, lockfile, CI, **whole pytest suite**). Strategy Eng (CLI-contract sanity as first user). Validation Eng (review + clean-checkout re-run). Head of V&R (gate). Ops (remote, Actions, branch protection, secret-scan). MD (routes, records closure).

---

### M1 — Data Layer → `v0.2.0`
**Dependencies:** M0 (`v0.1.0`) tagged.

**Deliverables:** `ztb/data/` — `bybit_rest.py` (public REST v5: kline, funding/history, instruments-info, server time), `rate_limit.py` (token bucket + backoff honoring 429/`retCode`/`Retry-After`), `pagination.py` (1000-bar window walk + descending→ascending + boundary dedupe; funding cursor), `fetch.py`, `schema.py` (canonical OHLCV: UTC `open_time` index, `open/high/low/close/volume/turnover` float64; off-grid rejection), `timeframes.py`, `cache.py` (parquet `cache/kline/{category}/{symbol}/{tf}.parquet`, atomic tmp→`os.replace`, `merge_incremental` latest-wins), `integrity.py` (**gap/dupe/monotonicity/freshness** + `launch_time` floor — G7), `loader.py::load(...)` (the contract; cold==warm determinism), `errors.py`. CLI `ztb data fetch|show|verify|instruments`. `docs/data_layer.md`.

**Key tasks:** errors → schema/timeframes → rate_limit → bybit_rest → pagination → fetch → cache → integrity(+freshness) → loader(delta-fetch, parity) → CLI → docs.

**Required tests (offline, recorded fixtures, frozen clock):** rate-limit (bucket via injected clock; 429 backoff; timeout→`FetchError`); pagination (2-page stitch + boundary dedupe; reverse; empty→schema-valid; funding terminates); schema/timeframes (round-trips; UTC alignment; off-grid→`SchemaError`); cache (byte-identical round-trip; incremental union; overlap latest-wins; atomic write survives crash); integrity (gap/dupe naming offenders; non-monotonic→error; pre-`launch_time` not flagged; **staleness**); **loader determinism (headline): cold==warm `assert_frame_equal`**; delta-fetch spy (0 calls when cached); `with_funding` perp vs spot; typed errors. Live smoke `@pytest.mark.network` (opt-in; **weekly Ops $0 timer that creates a task on API drift — fix #18**). Coverage ≥90% (`loader`/`integrity`/`pagination` ≥95%).

**DoD:** modules import; `load()` exact schema/rowcount, ascending, unique; **cold==warm proven**; incrementality spy-proven; `ztb data verify` exits 0 for BTC/ETH 1h linear 1y (dogfood); freshness live; tests green + coverage; no secrets/private/daemons; docs + CHANGELOG + `__version__=0.2.0`; CI-green + V&R PASS → tag `v0.2.0`.

**Who:** Head of Eng (freeze schema, branch, merge+tag). Platform Eng (all `data/*` + tests). Strategy Eng (dogfood). Validation Eng (re-runs, review, runs live smoke). Head of V&R (gate). Ops (network-smoke timer). MD (routes).

---

### M2 — Backtest Engine + Plugin Framework + Metrics + Indicators + Reference Strategy → `v0.3.0`
**Dependencies:** M0, M1 tagged; M1 loader contract frozen.

**Deliverables:** `strategies/base.py` (`Strategy` ABC: `name, symbols, timeframe, params, warmup`, `generate_signals(df)->pd.Series` target in **[-1,1]**, warmup-flat, no-NaN, engine-owns-shift); `strategies/registry.py` (auto-discovery, dup-name error, `get/all/list_names`); `features/indicators.py` (pure vectorized lib); `engine/backtest.py` (`run_backtest`, cost model, IS/OOS chronological split, credible-sample guard, `BacktestResult`); `engine/metrics.py` (net Sharpe/Sortino/maxDD+duration/#trades/PF/winrate/turnover/exposure, edge-cases); **`engine/portfolio.py` minimal single-symbol passthrough** (fix #23 — real aggregation in M5); `strategies/sma_cross.py` (trivial reference, long-or-flat); CLI `ztb list`, `ztb backtest`; `docs/engine.md` (cost model, **signal-timing/no-lookahead convention**, split, guard, every metric formula).

**Contracts (V&R-reviewed before code):** target from bar *t* close executes at *t+1* (engine shifts; strategies never shift). Cost bar *t* = `(commission+slippage)·|posₜ−posₜ₋₁|` (turnover; charged on open/flip/close); all metrics net. IS/OOS chronological fraction (0.7) reported for full/IS/OOS. Credible guard: `min_bars`/`min_trades`(OOS) → `credible=False`+reason; engine returns real numbers, never fabricates.

**Required tests (deterministic, synthetic):** indicators (hand-computed SMA/EMA/RSI/ATR; **no-lookahead invariance** truncate-at-k; crossover exactness; index preservation). registry (discovery; dup error; ABC enforcement; sorted names/unknown error). metrics (closed-form Sharpe; hand-computed maxDD+duration; PF/winrate; edges — zero-var→0.0, zero-trades→`None`+`credible=False`; `periods_per_year`). backtest (T-B1 **cost exactness** flip-every-bar; T-B2 **no-lookahead/timing** perfect-foresight defeated; T-B3 zero-cost==buy-and-hold; flat→0 trades `credible=False`; IS/OOS boundary; warmup clamp + reject non-zero-in-warmup; guard fires; contract enforcement→typed error; **determinism** byte-identical; index integrity). **Short-side test (fix #14): +1→−1 flip charged + PnL-signed correctly.** reference/dogfood (registry→engine trending #trades>0; flat fixture→`credible=False`; CLI 3-segment table). Coverage ≥90%.

**DoD:** imports; suite green ≥90%; **no-lookahead proven (T-B2, T-I4)**; cost realism (T-B1/T-B3); IS/OOS+guard; **short flips proven**; registry auto-discovers + rejects violations; `ztb list`/`ztb backtest sma_cross …` run against M1 loader, print net full/IS/OOS + credibility (transcript); determinism; lint/types clean; `docs/engine.md` matches code; V&R re-run + robustness pass; CI-green + V&R PASS → tag `v0.3.0`.

**Who:** Head of Eng (contracts, branch, merge+tag). Platform Eng (engine/indicators/registry/metrics/portfolio + tests). Strategy Eng (reference strategy + dogfood + CLI). Validation Eng (review + re-run + robustness + test audit). Head of V&R (gate). MD (routes).

---

### M3 — Reporting + Result Store + Scorecard + Streamlit → `v0.4.0`
**Dependencies:** M0–M2 tagged; `BacktestResult` stable.

**Deliverables:** `ztb/store/` — `schema.sql` (additive, `schema_meta`, §0.6), `results.py` (`connect` WAL+FK-on, `init_db`, **atomic** `save_run`, `get_run/list_runs/latest_run/best_runs/get_equity_curve/get_trades`, **`get_oos_metric(run_id,name)` named accessor — fix #16**); tables `runs`/`metrics(scope∈{is,oos,full})`/`trades`/`equity_curve`/`schema_meta` + indexes. `ztb/reporting/` — `format.py` (single-source thresholds: OOS-Sharpe floor, maxDD≤25%; `pass_fail`), `scorecard.py` (pure `build_scorecard` rendering `created_at` from record not `now()`), `notify.py` (`format_discord_payload` pure; `send_discord` fail-soft never aborts a run; **never emits a secret/webhook — fix #5**). `ztb/dashboard/` — `app.py` (Overview+Strategies, **read-only `mode=ro`**, `127.0.0.1:8501`), `data_access.py`, `components.py`. CLI `backtest --persist`, `report`, `dashboard`. Ops: `ztb-dashboard.service` (Board-owned, pinned tag, localhost, `Restart=on-failure`). `docs/store_schema.md`.

**Required tests:** store (idempotency; round-trip ≤1e-9; **atomicity/rollback — no orphan rows on injected mid-write failure**; FK; exactly 3 scopes mapped — IS/OOS-swap guard; leaderboard order; determinism). reporting (**scorecard golden file** byte-equal no drifting timestamps; threshold boundaries; payload shape+length; **fail-soft** no-webhook/500/timeout→False no-raise; **dry-run zero HTTP**; **no `ZTB_*` secret in scorecard/payload/dashboard — fix #5**). dashboard (write→`OperationalError`; component invariants `drawdown≤0`; empty-state no crash). integration (`test_run_to_store`: reference → `--persist` → 1 run/3 metrics/N trades/M equity; scorecard has OOS Sharpe; **stored == engine metrics**). Coverage (store+reporting) ≥90%, headless.

**DoD:** `--persist` writes one well-formed run, schema-idempotent; `report --run latest` regenerates from store alone, byte-matches golden, shows IS/OOS+costs+`code_version`; Discord delivered/cleanly-skipped, never fails a run, never leaks a secret; dashboard read-only localhost via Board-owned systemd pinned `v0.4.0`; suite green ≥90% no-network; **stored==engine proven**; secrets via env/EnvironmentFile; docs + CHANGELOG + `__version__=0.4.0`; CI-green + V&R PASS → tag `v0.4.0`. Rollback = `git checkout v0.3.0` + restart service.

**Who:** Head of Eng (schema sign-off w/ V&R, merge+tag). Platform Eng (store + format + notify + CLI + tests). Strategy Eng (scorecard + dashboard + reference run + smoke). Validation Eng (atomicity/scope/read-only/fail-soft/secret-leak audit, stored==engine). Head of V&R (gate). Head of Ops + Ops Eng (dashboard service). Research (registry_io boundary). MD (routes).

---

### M4 — Forward-Test Runner → `v0.5.0` (ENGINE-VALIDATION ONLY; §0.3)
**Dependencies:** M0–M3 tagged. Risk (M5) a **soft** seam (identity `sizing_fn`). **These runs are not go-live evidence.**

**Deliverables:** `engine/forwardtest.py` (`ForwardTester`+`run_tick`), `engine/ft_state.py` (resumable state, atomic JSON write, integrity hash), `engine/ft_decay.py` (pure decay). **Shared cost/metric primitive reused, not re-implemented** (extract `engine/_fills.py` if needed; backtester re-points; re-run M2 suite — keystone anti-dup). Store additive `schema_ft.sql` + `ft_io.py` (`forwardtest_runs/bars/fills/metrics`; idempotent bar PK `(run_id,symbol,bar_ts)`; baseline via `get_oos_metric` — fix #16). State artifacts (`state.json`+`equity.parquet`, **SQLite is source of truth**, `--rebuild-artifacts`). CLI `forwardtest start|tick|status|stop|list`. Systemd `.service`(`Type=oneshot`)+`.timer`(`Persistent=true`, timeframe-aligned, ~30s past close; lockfile single-flight). Dashboard Forward-Test page (read-only). `ft_report.py` (decay-alarm Discord). **Alert catalog lands here (G4):** process-down, data-staleness(→kill path G7), decay breach, reconcile freshness → each auto-creates a task.

**Decay score:** `clip(0.5·rel_gap(sharpe)+0.3·rel_gap(return)+0.2·rel_gap(pf),0,1)`; alarm = `n_bars≥min_sample AND (live_sharpe<sharpe_floor_frac·baseline_sharpe OR live_maxdd>maxdd_mult·baseline_maxdd)`. **Thresholds in config owned by Head of V&R; Strategy Eng owns only the formula (fix #24).** Defaults: `min_sample`≈3wk-bars, `sharpe_floor_frac=0.5`, `maxdd_mult=1.5`.

**Required tests (FakeDataSource/replay, no live network):** **A parity keystone** — forward-tester on exact backtest bars == backtester equity/#trades/fees/return ≤1e-9. **B no-lookahead** — unclosed bar never processed (`confirm=true`); warmup respected. **C idempotency/resume** — resume==uninterrupted bit-for-bit; double-fire→no dup; crash-mid-write→valid resumable; DB-is-truth `--rebuild-artifacts`. **D decay (pure)** — zero when ==baseline; positive+monotonic; alarm at exact threshold; min-sample suppression; live==`metrics.py`. **E store** — additive preserves M3; idempotent appends; baseline FK at `start`. **F CLI** — start/tick-all/status/stop; lockfile single-flight; non-zero on data failure. **G UTC.** **H dashboard+payload.** Coverage ≥90%.

**DoD:** parity ≤1e-9 (single shared cost+metric — grep-verified no dup Sharpe/fee); no-lookahead; resume/idempotent/crash-safe; survives restart + powered-off window (`Persistent=true` backfill); decay per tick + alarm + min-sample; CLI works; systemd oneshot ticks-and-exits, Board-owned; dashboard read-only; alert catalog wired; dogfood reference over simulated ≥3wk + clean resume-after-kill (PR evidence); ≥90% coverage; docs + CHANGELOG + `__version__=0.5.0`; CI-green + V&R PASS → tag `v0.5.0`. **Recorded: engine-validation runs, not go-live track record.**

**Who:** Head of Eng (design note, shared-primitive decision, merge+tag). Platform Eng (store/IO/state/runner/CLI/dashboard + tests). Strategy Eng (decay formula, runner co-build, dogfood). Validation Eng (no-regression, parity/resume/no-lookahead audit, decay re-run). Head of V&R (owns thresholds, gate). Head of Ops + Ops Eng (systemd + **alert catalog**). MD (routes; incident commander on alarms).

---

### M5 — Risk Module → `v0.6.0`
**Dependencies:** M0–M4 tagged. The seatbelt before execution.

**Deliverables:** `ztb/risk/` — `types.py` (`RiskDecision/State/Event`, enums, `InstrumentSpec`), `config.py` (frozen `RiskConfig`: `max_portfolio_dd=0.25`, `account_killswitch_dd=0.25`, vol target, leverage/position/heat/corr caps, lookbacks, `kill_cooldown_bars`, `sizing_method`), `limits.py` (venue/exposure clamps + Bybit tick/step/min-notional/leverage; non-perp/spot categories raise `NotImplementedError`), `heat.py` (vol, rolling corr/cov, heat `√(wᵀΣw)`, scaling), `sizing.py` (vol-target + **`dd_budget_scalar`** + heat cap), `killswitch.py` (HWM, 25% trip, cooldown, reset, flatten-to-zero), `manager.py` (`RiskManager.evaluate(...)->RiskDecision` — single pure seam, order sizing→heat/corr→limits→kill). **`engine/portfolio.py` grows from M2 passthrough into real multi-symbol aggregation here (fix #23).** Engine wiring: `backtest.py`+`forwardtest.py` call `evaluate()` (default risk-ON, `--no-risk` for A/B baselines only). Store additive `risk_events` + result columns (`risk_aware`, `max_portfolio_dd_realized`, `kill_count`, `mean_gross_leverage`). Scorecard risk block. `docs/risk-module.md` (math spec, V&R co-signed **before** code).

**Required tests (hermetic, numeric):** limits (min-qty/step round-down exact; min-notional reject; leverage cap; gross/net cap; position-count drop deterministic tie-break; per-symbol notional). sizing (vol-target exact+monotonic; vol floor no div-by-zero; **DD scalar = 1.0 @0%, →0 monotonically, =0 @/over 25%, asserted at 0/12.5/25%**; determinism; equity scaling). heat (single-position exact; corr matrix known series; corr-adjusted = scalar-sum @ρ=1, `√(Σwᵢ²σᵢ²)` @ρ=0; heat cap exact+event; short-history fallback). killswitch (trip ≥25% from HWM; no false trip @24.9%; HWM updates; cooldown ordering; **state round-trip** for forward continuity). manager (pipeline order; **kill overrides → all zeros**; purity/no mutation; event aggregation; no-op path). **integration (headline + honesty fix #13):** on >25% un-risked series, risk-aware maxDD *reduced vs `--no-risk`*; costs on post-risk qty; kill flattens after the kill bar; determinism; **`--no-risk` == pre-M5 (regression guard)**. **Adversarial gap-down fixture (fix #13): a gap where `dd_budget_scalar` is INSUFFICIENT, asserting the KILL-SWITCH catches it.** forwardtest-risk (same `RiskManager`, kill state carries across steps, events persist). store/reporting (`risk_events`; columns; real scorecard values). Coverage ≥90%.

**DoD (honesty-corrected, fix #13):** **The kill-switch is the HARD floor (proven, incl. the adversarial gap case). The `dd_budget_scalar` is a best-effort target (proven to reduce DD vs no-risk, not guaranteed <25% under gap risk).** No venue limit violated; both engines route every order through `evaluate()` (default ON); `--no-risk` reproduces pre-M5 exactly; determinism; A/B scorecard committed with real values (no fabrication); ≥90% coverage; risk layer pure (no network/wall-clock/global state); docs match code; CHANGELOG + `__version__=0.6.0`; CI-green + V&R PASS → tag `v0.6.0`; Research logs one lessons-ledger entry.

**Who:** Head of Eng (freeze contract, merge+tag). Platform Eng (`risk/*` + tests). Strategy Eng (engine seam, portfolio aggregation, A/B dogfood). Validation Eng (re-run, review every risk file + seams, gap-case audit). Head of V&R (co-signs math spec; owns thresholds; gate). MD (routes). Research (lesson).

---

### M6 — Execution (DEMO) → `v0.7.0`
**Dependencies:** M0–M5 tagged. **M5 mandatory** — executor routes every order through risk. Scope: **linear USDT perps + spot only** (other venues deferred; Research logs them as backlog lessons — fix #26).

**Deliverables:** `execution/models.py` (typed order/fill/position/account + `Mode{DEMO,LIVE}`), `bybit_client.py` (signed REST; **demo URL hard-pinned `api-demo.bybit.com`; `mode=LIVE` raises `LiveModeBlockedError` in M6**; HMAC-SHA256, recv-window/time-sync, rate governor, idempotent retries on network/5xx only — never 4xx), `idempotency.py` (**`orderLinkId` from stable `(strategy,symbol,bar_ts,intent_hash)` — NOT run_id — fix #21**; SQLite dedupe ledger), `reconcile.py` (positions/orders/fills→`AccountState`; realized+unrealized PnL; drift/orphan/missing-fill detect+repair; irreconcilable→kill-switch), `executor.py` (`step`/`run`: data(closed bar)→signal→reconcile→**risk gate(M5)**→diff→round→idempotent place/amend/cancel→re-reconcile→persist→notify; kill honored; `--dry-run`/`--once`), `errors.py`. Store `exec_io.py` (append-only `exec_runs/orders/fills/positions_snapshots/pnl_ledger/idempotency`). CLI `ztb run --mode demo [--dry-run] [--once]`, `ztb reconcile`; refuses non-demo. `docs/m6_execution.md` + lessons entry (REST-poll-vs-WS).

**Required tests (transport mocked, zero network in unit CI):** client (**signing golden vector**; demo URL pin; **`mode=LIVE` raises**; param canonicalization; retry network/5xx never 4xx; governor + 429). models/rounding (tick/step/min-notional reject pre-send; side/qty sign). idempotency (same intent→same id; **replay→one placement; restart→same id no double-fill — proves stable-tuple key, fix #21**; distinct intents distinct ids). reconcile (PnL partial fills+fees long&short; drift flagged; orphan cancelled; missing-fill convergence; idempotent dedupe by execId). executor (happy path one rounded order; no-op; rebalance; **risk veto→no order→`RiskRejectedError` proves risk before placement**; **kill→halt+flatten+notify**; closed-bar-only; dry-run zero placements; **failure-mid-loop→next reconcile detects placed order, no re-place — restart-safe**). signal-parity (`generate_signals` == M2 backtest target same bar). store (round-trip; append-only; position reconstructable). CLI (`--mode live`→non-zero `LiveModeBlockedError`; demo `--once --dry-run`→0). Gated live-demo smoke `@pytest.mark.live_demo` (env-gated, off-CI, run by Ops on infra). Coverage ≥90% on `execution/`; hypothesis on rounding + id.

**DoD:** **demo-only proven** (every path→demo URL; non-demo raises; only demo env vars in `execution/` — grep/test asserted); end-to-end demo trade — reference via `ztb run --mode demo` **places a real demo order, fills, reconciles** with correct PnL (smoke log + store rows); signal parity; **risk gate enforced** (no order without M5 pass; kill at 25% account DD); **idempotency under retry/crash-restart** (replay+restart green, stable-tuple key); reconcile correctness vs hand-computed; suite green ≥90% hermetic; append-only track record; CLI per spec; PnL includes real demo commission + observed slippage (no fabrication); docs + ledger; CHANGELOG + `__version__=0.7.0`; CI-green + V&R PASS → tag `v0.7.0`. Sustained demo run is `ztb run` under a Board-owned unit (§0.8).

**Who:** Head of Eng (design note, merge+tag). Platform Eng (client/idempotency/reconcile/exec_io/CLI + most tests). Strategy Eng (signal→order, signal-parity, dry-run, dogfood). Validation Eng (review signing/demo-lock/reconcile/risk-wiring/idempotency; re-run; smoke-evidence audit). Head of V&R (gate; go-live checklist owner). Ops Eng (runs gated smoke). MD (routes; incident commander).

---

### M7 — v1.0 Live-Ready → `v1.0.0` (armable, **disarmed by default**)
**Dependencies:** M0–M6 tagged; M6 demo executor ran a clean multi-day paper loop. Live keys NOT used in M7 build; arming is a separate, later, Board-only act.

**Deliverables:** **HARDEN** `execution/client.py` (explicit demo/live resolution, mainnet/demo URL switch, signing audit, time-sync, idempotent `orderLinkId` on every order, hard-fail on auth). **NEW** `execution/live_guard.py` (arming gate; reads Board `ZTB_LIVE_ARMED` + signed `live_arm.json`; **default disarmed**; any live path asserts `is_armed()` or `LiveDisarmedError`; refuses to arm unless preflight all-PASS; **no automatic arm path**). **HARDEN** `executor.py` (bounded retries, reconcile-on-startup adoption, graceful SIGTERM flatten-or-hold, heartbeat, per-tick risk re-check, one bad tick never kills the loop). **HARDEN** `reconcile.py` (startup adoption + periodic heal; irreconcilable→kill). **NEW** `execution/killswitch.py` (unified: account-DD 25%, portfolio-DD 25%, reconcile-drift, **data-staleness (G7)**, heartbeat-stale, manual; trip = cancel-all + policy-flatten + halt + notify + persist; idempotent). **HARDEN** `cli.py ztb run` (pins/verifies released tag; refuses dirty/non-tagged unless `--allow-dirty`; version-match) + `ztb rollback <tag>`. **NEW** `ops/preflight.py` (`PreflightReport`). **NEW** `reporting/health.py` (heartbeat/freshness). **HARDEN** `notify.py` (live-critical events). **NEW** `dashboard_live.py` (read-only :8501 Live page: mode banner, armed state, tag, positions/orders, heartbeat, DD-vs-thresholds, recent trips — **no trade/arm control**; localhost-only, **on go-live checklist that it's unreachable off-host — fix #25**). **NEW** `docs/runbooks/go-live.md` + `incident-rollback.md`.

**Key tasks (safety-gate before live path):** A hardening → B safety gate (killswitch then live_guard) → C pinned-tag run + preflight + rollback → D live order path **behind `is_armed()`** → E observability → F tests + CI hardening → G **sustained DEMO proof on a pinned tag** (multi-day `ztb run` under Board-owned unit; ≥1 forced kill-switch trip, ≥1 forced reconcile-drift heal, a `ztb rollback` drill) → H V&R → merge+tag. Live remains disarmed.

**Required tests (mocked client, no real keys):** client-mode (demo/live URL; **default=demo regression-lock**; deterministic `orderLinkId` reused on re-issue; auth→hard-fail; transient→bounded retry; skew→blocked). live-guard (**disarmed by default→live raises**; arming refused unless preflight all-PASS; demo unaffected; needs Board token; **no auto-arm**). killswitch (each source trips independently; trip→cancel-all+flatten+halt+notify+persist; idempotent; tripped blocks new orders until reset). preflight (each item fails when precondition unmet; all-pass→ok). executor-live-path (full tick risk+kill every tick; raised tick caught, loop survives; SIGTERM graceful; disarmed→live branch never taken). reconcile-hardening (adoption; orphan/unexpected-fill/mismatch healed; irreconcilable→kill). run-pinned-tag (match proceeds; mismatch/dirty/non-tagged aborts). rollback (resolves prior tag; no-op safe). health (freshness; stale flagged; DD-vs-threshold). **All M0–M6 suites still pass (regression).** Live dashboard imports/renders against a mocked snapshot.

**DoD:** entire suite (M0–M6 + M7) green on clean checkout, zero skips on live-safety tests; **demo default proven**; **live unreachable unless armed** (disarmed-by-default, no auto-arm, no live keys in repo — CI secret-scan passes); full loop on a pinned tag in DEMO sustained ≥ multi-day with ≥1 injected tick exception survived; kill-switch live-grade (≥ account-DD + reconcile-drift trips → cancel-all+halt+Discord+persisted reason, V&R-verified); reconcile heals an injected drift; irreconcilable trips kill; `ztb validate` runs full preflight→`PreflightReport`, arming refused on any fail; **rollback drill done** (returns to known-good cleanly, runbook matches reality); read-only Live page renders real demo snapshot, **no trade/arm control, unreachable off-host**; runbooks reviewed by Head of Ops + Head of V&R; **all numbers from store/logs/scorecard (no fabrication)**; CI-green + V&R PASS → merge + `__version__=1.0.0` + CHANGELOG + tag `v1.0.0`. **Live money remains DISARMED pending a separate explicit Board action.**

**Preflight note (fix #20):** the strategy-readiness item asserts **"a risk-active forward-test holding within the acceptance band + risk-cleared"** — NOT "≥20% realized" (the ≥20%/12mo is a doctrine aspiration, not an arming precondition, else nothing could ever arm).

**Who:** Head of Eng (decompose, merge+`v1.0.0`+CHANGELOG+tag, rollback semantics). Platform Eng (hardening, live-path wiring behind the guard, live_guard/killswitch/preflight/health/live-dashboard/CI-hardening, bulk of tests). Strategy Eng (pinned strategy plugs in unchanged, loop integration test, drives sustained DEMO proof). Validation Eng (independent re-runs of demo loop/kill/reconcile/rollback; review of safety-critical modules; test audit). Head of V&R (evidence gate; signs go-live checklist; confirms live disarmed; PASS = merge gate). Head of Ops + Ops Eng (pinned-tag `ztb run` under systemd rails, cost-guard/notifier integration, co-own incident-rollback runbook, live-incident triage). MD (routes, incident commander, Board interface). **Human Board: the only party that arms live money, after `v1.0.0`.**

---

## 3. How the Agents Work Together

**One law:** work flows **UP** from a member to a Head, **BACK** to the MD; only the MD routes **ACROSS** to another Head. No member-to-member hand-offs, ever. Every hand-off is a created task with one owner (no duplicates). V&R is independent; her PASS is the merge gate. The merge to `main` IS the validation gate.

### 3.1 The MODULE relay (e.g., `engine/backtest.py`, `risk/sizing.py`)
1. **MD → Head of Engineering** — "Improve module X to spec S."
2. **Head of Eng → Platform Engineer** — build task on `feat/<module>` with acceptance criteria + required pytest cases.
3. **Platform Engineer** builds + writes/extends the suite, green locally, conventional commits → **hands back UP to Head of Eng** (never sideways).
4. **CI runs on push.** **A red CI never advances** — it stays inside Engineering; the Head re-tasks the member (fix #3).
5. **Head of Eng → MD** — once CI is green on the head commit, hands the validation request BACK (no self-certification).
6. **MD → Head of V&R** — routes ACROSS.
7. **Head of V&R → Validation Engineer** — review + independent re-run **against the same SHA** + robustness → hands back UP.
8. **Head of V&R decides:** FAIL → BACK to MD → re-route fix to Head of Eng (loop). PASS (recorded against that SHA) → BACK to MD.
9. **MD → Head of Eng** — merge authorization. **Head of Eng merges (CI-green AND V&R-PASS on the same commit)**, CHANGELOG, SemVer per §0.2, tag.
10. **Head of Eng → MD** — "Module X merged + tagged." MD routes the next milestone.

**Gate:** `feat/<module>` → **CI green on head (precondition)** → **V&R PASS on the same SHA** → Head-of-Eng merge + tag → MD.

### 3.2 The STRATEGY relay (a `strategies/<name>.py` plugin)
1. **MD → Head of Research** — "Find one Bybit edge for regime R."
2. **Head of Research → Market Analyst** — scan + regime-check + surface ONE candidate → hands back UP.
3. **Head of Research** writes the plugin SPEC against the `Strategy` ABC, enforces the ≤3-candidate cap, records it in registry + lessons ledger → **hands the SPEC back UP to the MD** (never sideways to Engineering).
4. **MD → Head of Eng** — "Implement plugin to SPEC."
5. **Head of Eng → Strategy Engineer** — implement `strategies/<name>.py` on `strat/<name>` (plugin only, no engine edits), run `ztb backtest` cost-aware (commission+slippage, IS/OOS), net metrics → hands back UP with evidence.
6. **Head of Eng → MD** — once CI green, hands validation BACK.
7. **MD → Head of V&R → Validation Engineer** — independent OOS/robustness re-run, plugin review, cost-realism → hands back UP.
8. **Head of V&R decides:** FAIL (overfit / DD too deep / unrealistic costs) → BACK to MD → re-route fix to Eng OR kill the candidate and route a lessons-ledger write to Research. PASS → BACK to MD.
9. **MD → Head of Eng** — merge `strat/<name>` (CI-green + V&R PASS) + tag.
10. **MD → forward-test** — routes a **risk-active `ztb forwardtest`** task (§0.3) to Eng → Strategy Eng. Track record accumulates in the store.
11. After durable risk-active paper proof, **MD → Head of V&R** for the go-live judgment; **the human Board arms live**.

**Gate:** SPEC (≤3 cap) → `strat/<name>` build + backtest → **CI-green + V&R PASS = merge** → tag → **risk-active forward-test (decay-watched)** → track record → V&R go-live judgment → **Board arms live.**

### 3.3 Git / validation gates
Branches `feat/*`, `fix/*`, `strat/*`; conventional commits; secrets gitignored. **Two-key merge:** CI-green on the PR head **and** a recorded V&R PASS on the identical SHA. Branch protection enforces require-PR-+-green-CI. Head of Eng performs merge + tag. Rollback = `git checkout <prev tag>`.

### 3.4 Cadence & triggers — what creates agent work
Two clocks: **deterministic systemd timers** ($0, no agent) and **one Paperclip R&D routine + event wakes** (the only things that spin up agents). No agent spawns a daemon/timer (§0.8).

- **MD R&D review — every 2 days (the one heartbeat routine):** MD reads scorecard, track record, decay flags, open lessons, routes the next module/strategy work, honoring engine-first and **anti-drift (every cycle ends in a tagged artifact OR a proven plugin OR a documented lesson — a written close-out with a tag/ledger-id/PR-link, else the cycle is flagged)**.
- **Deterministic systemd jobs that CREATE agent work:**

| systemd job ($0 code) | Watches | Event raised | Wakes → acts |
|---|---|---|---|
| forward-test decay monitor | live-vs-backtest decay | "decay flag on strategy N" | MD → re-tune (Eng) or retire-with-lesson (Research) |
| **data-staleness (G7)** | kline freshness | "stale data" | trips kill path; MD → Ops triage |
| risk kill-switch | account/portfolio DD, reconcile drift, heartbeat | "kill-switch tripped" (halts `ztb run`) | MD (commander) → Ops (confirm halt) + V&R (post-mortem) |
| CI on push | branch build + tests | "CI red on branch B" | owning Head re-tasks member; **red CI never reaches V&R** |
| cost-guard | daily spend vs ~$1.65 AUD | "cost cap breached" | Head of Ops → Ops Eng triage; MD informed |
| **dep/CVE drift (G3)** | dependency closure | "vulnerable/abandoned dep" | task → Platform Eng |
| **network smoke (M1)** | Bybit API shape | "API drift" | task → Platform Eng |
| notifier | scorecard/incidents | Discord push | informational → MD |

**One task per job, one owner, no duplicates.** Members report UP; Heads hand BACK to the MD; the MD is the only router ACROSS; V&R independent; PASS = merge gate.

---

## 4. Rollout & Sequencing — Empty Repo → Working Demo Bot

**Principle:** build the ruler before you measure; calibrate it on something whose length you already know (the trivial reference strategy); only then measure the unknown (real alpha). M0–M3 build and prove the machine; M4–M6 wire it to live data, risk, and a demo venue; M7 declares it armable.

### 4.1 The dependency spine (why this order)
M0 before all (nowhere to merge / no CI / no version to pin until the scaffold exists). M1 before M2 (a backtest with no deterministic cached data is non-reproducible = no evidence). M2 before any alpha (the keystone: engine + plugin contract + metrics + indicators + registry; until M2 no strategy *can* be written). M3 before forward-testing matters (a forward test is only meaningful against a stored backtest; the store is the track record). M4 before M5/M6 (prove the runner cheaply on paper — engine-validation only, §0.3). M5 before M6 (never let execution place an order risk hasn't sized and a kill-switch can't stop). M6 before M7 (can't declare live-ready until a real order filled + reconciled on demo).

### 4.2 Checkpoints (each = a tag)
`v0.1.0` skeleton runs → `v0.2.0` cold==warm cached data, offline-replayable → `v0.3.0` reference backtests with cost-aware net IS/OOS → `v0.4.0` runs persist + scorecard + dashboard → `v0.5.0` deterministic/resumable paper runner (engine-validation) → `v0.6.0` risk sizes + kill-switch unit-proven incl. adversarial gap → `v0.7.0` a real demo order fills + reconciles → `v1.0.0` full demo loop unattended on a pinned tag, go-live checklist PASS, disarmed.

### 4.3 Risks & mitigations
| Risk | Mitigation |
|---|---|
| Over-scaffolding M0 | dirs + stubs only; Head of Eng rejects premature logic |
| Bybit API drift / gaps / rate limits | offline fixtures; cache + incremental fetch; gap/freshness detection; weekly Ops network-smoke timer |
| Look-ahead / unrealistic costs flatter strategies | engine owns the 1-bar shift; T-B2/T-I4 lookahead-defeat; hand-calc on the trivial strategy; V&R audits the *tests* |
| Non-reproducible deps over time | lockfile in M0 DoD; CVE/dep-drift timer |
| Forward-test proof runs without risk | §0.3: M4 runs are engine-validation only; the go-live forward-test is risk-active (M5+) |
| DD scalar can't guarantee <25% on gaps | fix #13: kill-switch is the hard floor (adversarial-gap-tested); scalar is best-effort |
| Idempotency breaks on restart | stable-tuple `orderLinkId` (§0.7); restart test |
| Accidental live trading | demo URL hard-pinned; `LiveModeBlockedError`(M6)/`LiveDisarmedError`(M7); demo default regression-locked; arming Board-only |
| Secret leak | secret-scan from M0; env-only keys confined to `execution/`; no-secret-in-output tests |
| Drift into "just research" | anti-drift written close-out each 2-day cycle; ledger catch-all |

---

## 5. Go-Live & the Proving Loop

**Prime directive:** survival first. A strategy *earns* capital; it is never granted it. Every step is a forward-only gate.

### 5.1 Doctrine gates (preconditions)
Live runs a **pinned released tag** (`v1.0.0`+), never `main`/a branch. M5+M6+M7 tagged and V&R-PASSED. The merge gate already passed (CI-green + V&R PASS). **Demo until the human Board arms.** No agent flips the flag. Honesty: every Board-facing number is reproducible via `ztb report` from the store; if it can't be regenerated, it doesn't exist.

### 5.2 Forward-test phase (risk-active — §0.3)
Minimum **3 continuous weeks** of paper-on-live via `ztb forwardtest`, **with the M5 risk module + kill-switch ACTIVE** (this is the go-live-qualifying run; M4-era pre-risk runs do not count). Decay checks: forward net Sharpe ≥ 0.7× OOS Sharpe and same sign on every core metric; observed-fill slippage reconciled against the modeled cost (re-cost + re-validate if optimistic); ≥30 trades (or extend); regime tagged. **Exit criteria (all):** ≥21 continuous days no unexplained gaps; live-vs-backtest in band **and still holding at presentation**; cost model reconciled; **kill-switch + risk limits demonstrably fired correctly in a drill**; no anti-pattern detected.

### 5.3 The go-live checklist (V&R signs; any FAIL halts)
| # | Gate | Pass condition | Evidence |
|---|---|---|---|
| 1 | QA-passed, credible, cost-aware | V&R PASS; commission+slippage modeled; IS/OOS honored; **net** metrics | `ztb backtest` + scorecard + V&R review |
| 2 | Risk-cleared & sized | sizing keeps portfolio DD ≤25%; heat/corr within limits; venue limits checked; **25% account kill-switch wired** | risk config + V&R risk review |
| 3 | **Risk-active forward-test holding** | ≥3wk, live-vs-backtest in band, **still holding now**, decay green | `ztb forwardtest` + store |
| 4 | Not a known anti-pattern | not overfit (param-sensitivity); no survivorship/look-ahead; not curve-fit to one regime; no martingale/avg-into-loss | V&R review + lessons-ledger cross-check |
| 5 | Bybit key hardened | **IP-restricted to host; withdrawals DISABLED; trade-only scope; secrets in `execution/` only, gitignored** | Ops key audit |
| 6 | Kill-switch tested | fired correctly in a recent **demo drill**; trips flatten + halt | drill log in store |
| 7 | Tiny first size | first-live = floor size, **fixed by policy not conviction** | risk config |
| 8 | Rollback rehearsed | prior tag identified; `git checkout <prev tag>` + flip-to-demo rehearsed | Ops runbook |
| 9 | **Dashboard not reachable off-host** (fix #25) | Live page localhost-only, no off-host route, no trade/arm control | Ops verification |

Packet also carries: released tag + version, CHANGELOG, the full trade ledger (not a summary), regime caveat.

### 5.4 Arming, sizing, scaling (earn capital)
**Board arming — human only.** Per-strategy, per-size, against a single pinned tag. Logged. Implicit disarm-on-doubt: MD/Board can revoke anytime. **First-live = tiny by policy** — smallest meaningful size above venue minimum (real fees/fills, irrelevant loss); portfolio DD ≤25% and the account kill-switch apply from the first dollar. **Scale on proof — tranches:** Tranche 0 ≥2–4 weeks; each step-up ≤2× prior, requires V&R re-confirm that live is holding and fills haven't degraded (market-impact check); DD budget never exceeds 25%. **Ratchet, never leap;** a drawdown/decay event resets to the previous proven tranche (a hard rail trip resets harder). Large step-ups are Board-visible with human sign-off.

### 5.5 Kill-switch, incident, rollback
**Account-level 25% kill-switch is the hard rail:** breach → flatten all + halt + page MD. Per-strategy/portfolio DD limits sit inside and trip first. Cost-guard ($1.65 AUD/day) independent. **Tested in a drill before every go-live** (checklist #6). **Incident (MD = commander):** Contain (executor halts; confirm flat vs exchange via reconcile) → Notify (Discord; event = the work item) → Diagnose (root cause from ledger + reconcile log) → Decide (**default bias: disarm first, investigate second**) → Postmortem → lessons ledger (a repeated class becomes a new checklist anti-pattern). **Rollback:** live always on a pinned tag; rollback = `git checkout <prev tag>` + restart `ztb run`, OR flip to demo to stop live risk instantly. Rehearsed in go-live prep. A bad release is patched on `main`, re-clears the V&R gate, then the host is pinned forward.

### 5.6 The ongoing proving / track-record loop
The store is the track record; the dashboard (read-only :8501) and `ztb report` render it — that ledger, not anyone's claim, earns the next tranche. Continuous decay surveillance (Market Analyst watches, breach → V&R review task — G8) catches drift early, even while still profitable. The earn-more ladder (proven tranche + holding + clean ops → V&R re-confirm → bounded step-up → Board-visible) is mirrored by a symmetric de-risk ladder (decay/DD/incident → size-down or disarm) — the system de-risks faster than it scales. Live results that contradict the backtest feed back into the cost model, the anti-pattern list, and the validation gate, so the machine gets harder to fool over time.

---

## 6. Continuous Improvement — the Bridge Forward

`v1.0.0` is enrollment in continuous proof, not a finish line. This playbook hands off to the separately-produced **EXPANSION ROADMAP** and the **self-developing mechanism**:

- **Horizon 1 — harden & widen the proven core:** more validated plugins through the same relay; portfolio-level multi-strategy allocation (built on M5's aggregation); WebSocket private streams replacing REST-poll reconcile (the M6 deferred lesson); the deferred Bybit venues (inverse perps, USDC options, leveraged tokens, spot margin, Earn — each a plugin/adapter to the same engine, logged as backlog lessons in M6, fix #26).
- **Horizon 2 — options & richer instruments:** USDC options support (options-greek risk extends `ztb/risk/` beyond the M5 perps/spot scope, which currently raises `NotImplementedError` for other categories — the explicit extension point); multi-venue-within-Bybit portfolio risk.
- **Horizon 3 — the self-developing mechanism:** the 2-day MD R&D review + event-driven hand-offs + the lessons ledger form a closed improvement loop where every cycle ends in an engine improvement, a proven plugin, or a documented lesson. Live decay feeds the cost model and anti-pattern list; the validation gate ratchets tighter; the firm compounds its own track record. The anti-drift rule and the cost-guard keep it cheap and honest as it scales.

The through-line, from empty repo to a compounding machine: **one reusable engine, evidence at every gate, cost-realistic and demo-safe, survival first — capital earned, never assumed.**