# Opportunities Registry — Strategy Funnel

**Owner:** Head of Research
**Scope:** Zero Alpha / `ztb` — the single deterministic Bybit trading engine. Strategies are plugins to that one engine; never per-strategy scripts.
**Status:** EMPTY. No candidates yet. The only strategy carried to `v1.0.0` is the trivial reference `sma_cross`, which dogfoods the engine (M2) and is NOT alpha.

This registry is the single source of truth for every strategy idea and its position in the proving funnel. The Head of Research owns it (writes SPECs, maintains rows, enforces the candidate cap). Members report UP; only the MD routes work ACROSS to Engineering or V&R.

---

## Funnel

| id | name | thesis | symbols / TF | stage | net evidence | owner | updated |
|----|------|--------|--------------|-------|--------------|-------|---------|
| _(none yet)_ | | | | | | | |

> No rows. The funnel opens only after the engine is proven (M0–M7) and the MD routes the first "find one Bybit edge" task to the Head of Research. Until then, the engine — not alpha — is the work.

---

## Stage pipeline

A candidate advances one forward-only gate at a time. Each transition is a created task with exactly one owner; a failure routes BACK to the MD, who re-routes a fix or kills the candidate with a lessons-ledger entry.

```
idea
  -> backtested              (ztb backtest run; cost-aware, IS/OOS, net metrics recorded)
  -> validated (V&R PASS)    (independent OOS/robustness re-run on the same SHA; merge gate passed)
  -> risk-cleared            (routed through risk/manager.evaluate; sizing + kill-switch wired; venue limits checked)
  -> forward-test            (risk-active ztb forwardtest, >=3 continuous weeks, kill-switch ACTIVE)
  -> board                   (V&R go-live judgment + go-live checklist packet to the human Board)
  -> live  /  declined       (Board arms live money — human only;  OR  declined with a documented lesson)
```

Notes per stage:
- **idea** — surfaced by the Market Analyst, written into a `Strategy`-ABC SPEC by the Head of Research. SPEC id assigned here (see below).
- **backtested** — Strategy Engineer runs `ztb backtest` against the M1 loader; commission + slippage modeled; IS/OOS chronological split; all metrics **net**. No fabricated numbers — `credible=False` when the sample is too small.
- **validated (V&R PASS)** — Validation Engineer independently re-runs OOS + robustness against the identical SHA; not overfit, no look-ahead, costs realistic. The recorded V&R PASS + CI-green on the same commit IS the merge gate. PASS here merges + tags `strat/<name>`.
- **risk-cleared** — every order routes through `RiskManager.evaluate(...)`; vol-target sizing + `dd_budget_scalar`; 25% account kill-switch wired; Bybit tick/step/min-notional/leverage honored.
- **forward-test (>=3wk risk-active)** — the go-live-qualifying run: `ztb forwardtest` with the M5 risk module + kill-switch ACTIVE for **>=3 continuous weeks** (>=21 continuous days, >=30 trades or extend, decay green, slippage reconciled). M4-era pre-risk runs are engine-validation only and NEVER count as track-record evidence.
- **board** — Head of V&R signs the go-live checklist (any FAIL halts); the packet carries the pinned released tag, CHANGELOG, the full trade ledger (not a summary), and the regime caveat.
- **live / declined** — only the **human Board** arms live money, per-strategy, per-size, against one pinned tag. A killed candidate exits to **declined** with a lessons-ledger entry so the machine gets harder to fool over time.

---

## Rules

- **Candidate cap: <= 3 active candidates at any time.** "Active" = any row in stages `idea` through `forward-test` (i.e., not yet `live`/`declined`). The Head of Research enforces this; a new idea cannot be admitted while three candidates are already in flight. This keeps the funnel honest and the firm cheap.
- **SPEC ids are monotonic and immutable.** Each SPEC gets the next integer id (e.g. `SPEC-001`, `SPEC-002`, ...). Ids only ever increase, are assigned once at the `idea` stage, and are never reused, renumbered, or recycled — even after a candidate is `declined`. A declined id is retired permanently; the next idea takes the next-higher id.
- **One engine, plugins only.** A row here corresponds to a `strategies/<name>.py` plugin against the `Strategy` ABC — never an engine edit, never a standalone script.
- **Evidence is the gate.** A row advances only on reproducible, store-backed, net-of-cost numbers regenerable via `ztb report`. If it can't be regenerated from the store, it doesn't exist.

---

## Horizons (backlog — NOT current work)

The expansion roadmap's **Horizon 1 / Horizon 2 / Horizon 3** are explicitly **deferred** until after the core machine is built and proven (M0–M7, ending at tag `v1.0.0` on Linux `~/zero-alpha`). **Do not build any of these now.** They are recorded here only so they are not lost as backlog; admitting any of them is a future MD-routed decision, not current work.

- **H1 — harden & widen the proven core (deferred):** more validated plugins through the same relay; portfolio-level multi-strategy allocation on M5's aggregation; WebSocket private streams replacing the M6 REST-poll reconcile; the deferred Bybit venues (inverse perps, USDC options, leveraged tokens, spot margin, Earn) — each a plugin/adapter to the same engine.
- **H2 — options & richer instruments (deferred):** USDC options support (options-greek risk extends `ztb/risk/` beyond the M5 perps/spot scope, which raises `NotImplementedError` for other categories — the explicit extension point); multi-venue-within-Bybit portfolio risk.
- **H3 — the self-developing mechanism (deferred):** the 2-day MD R&D review + event-driven hand-offs + the lessons ledger as a closed improvement loop, where every cycle ends in an engine improvement, a proven plugin, or a documented lesson.

**Current work is the engine, not alpha.** The only strategy taken to `v1.0.0` is the trivial reference `sma_cross` (a dogfood, not a candidate — it does not occupy a funnel row). The first real candidate is admitted only after M0–M7 are tagged and the MD routes the first edge-discovery task to the Head of Research.
