I have the context I need. The memory confirms the v4 10-agent product-building org (Managing Director, Head of Research, Head of Engineering, Head of Validation & Risk [independent], Head of Operations, plus members), the `ztb` product, the gates (cost-real backtest → OOS → ≥3wk forward-test → Board arms live), the engineering hygiene (git, SemVer, CHANGELOG, merge-to-main = V&R gate, `ztb run` pins to a released tag), cost-guard, and lessons-learned ledger. Now I'll write the self-developing mechanism spec aligned to all of that.

This is a design task — the deliverable is the spec itself, returned as my final message.

# ztb SELF-DEVELOPMENT MECHANISM (`SELF-DEV.md`)

How Zero Alpha makes `ztb` a product that proposes, prioritizes, and builds its own roadmap — indefinitely, beyond any fixed scope, without bloating, overfitting, or burning cost.

This sits alongside `ORG.md`, `PRODUCT.md`, `ENGINEERING.md`, and the lessons ledger. It is the loop that keeps the backlog alive after the original scope is "done."

---

## 0. Core principle

> The firm's job is not to finish `ztb`. It is to run a perpetual, evidence-gated loop that keeps `ztb` getting *more capable per dollar* — where every cycle is forced to terminate in one of three durable artifacts and nothing is ever built on a hunch.

A new **module** (engine capability, data source, execution venue feature, reporting view, risk control) goes through the **exact same gates as a strategy**: spec → build → engine tests → V&R sign-off → tagged release → CHANGELOG. There is no "trust me" path to main, and `ztb run` only ever pins to a validated tag.

---

## 1. Roadmap ownership (the 10-agent org)

| Artifact | Owner | Role |
|---|---|---|
| **Living Roadmap** (themes, 1–2 quarters out) | **Managing Director (MD)** | Sets direction, breaks ties, enforces WIP + cost guardrails, approves what enters the backlog. Single source of truth: `roadmap/ROADMAP.md`. |
| **Research backlog** (idea → spec candidates) | **Head of Research** | Owns the *what-to-build* funnel; runs the horizon scan; converts findings into spec'd backlog items. Market Analyst feeds signals. |
| **Engineering backlog** (spec → built modules) | **Head of Engineering** | Owns the *how-to-build* funnel; sizes effort, dependency-readiness, owns releases/tags/CHANGELOG. Platform + Strategy Engineers build. |
| **The gate** (anything → trustworthy) | **Head of Validation & Risk (independent)** | Hard veto. No item is "Done" without V&R sign-off. Reports to MD but cannot be overruled on a *fail* by Research or Engineering — only the human Board can override a V&R fail. |
| **Cadence + cost telemetry** | **Head of Operations** | Runs cost-guard, keeps the scoring inputs honest (real $/effort, real cycle outcomes), publishes the cost report the rubric consumes. |

**One backlog, three lanes, one board.** A single file `roadmap/BACKLOG.md` (or the Paperclip issue board) holds every item in one of these states. The MD owns the board; Heads own the lanes.

```
IDEA → SPEC'D → APPROVED → IN-BUILD → IN-VALIDATION → FORWARD-TEST(if strategy) → RELEASED → (LIVE | RETIRED)
                                                                                            ↘ DECLINED (with lesson)
```

Rule: **an item with no named owner-Head and no acceptance criteria cannot leave IDEA.**

---

## 2. The Horizon Scan — "what to build next" review

**Cadence:** one dedicated routine, **fortnightly** (every 2 weeks, piggy-backing the existing MD R&D review), owned by **Head of Research**, output reviewed by MD. Keep it cheap: a bounded reasoner run, not a standing committee.

**Inputs (all already in the firm):**
1. **Lessons ledger** (`lessons-learned.md`) — every declined cycle's lesson is a candidate capability ("basis-arb died on spread compression" → *build a regime-detector module*).
2. **Scorecard + cost report** — where is the product losing money, leaving edge on the table, or spending tokens/compute it shouldn't?
3. **Validation backlog of pain** — what does V&R keep flagging that the engine can't yet measure? (e.g. "we can't model funding decay" → engine gap.)
4. **Bybit surface coverage map** — which in-scope products (spot, USDT/USDC/inverse perps, USDC options BTC/ETH/SOL, leveraged tokens, spot margin, Earn) are *unserved* by current modules? Gaps are candidates.
5. **Market-Analyst signal scan** — regime shifts, new Bybit listings/products, fee/funding changes that open or close an edge.

**Output — every horizon scan MUST produce, in writing:**
- 0–5 new **backlog items**, each as a one-paragraph **capability brief** (see §4 spec template, lite form): problem → proposed module → what it unlocks → rough dependency list.
- A **re-score** of the existing backlog (inputs drift; priorities move).
- An explicit **retire list**: features/strategies flagged for the auto-retire check (§5).
- If the scan finds nothing worth building: it says so, and **that null result is itself logged as a lesson** ("scanned X, no edge because Y"). The cycle still closes per §5's rule.

> Anti-sprawl: the scan may *propose* freely but may only *promote* items that fit under the WIP limit and beat the rubric floor. Proposing is cheap; building is gated.

---

## 3. Scoring & prioritization rubric

Every backlog item gets a **Priority Score** at the horizon scan and whenever its inputs change. Computed deterministically (it's a spreadsheet/`score.py`, not an LLM judgment call — cost-lean doctrine: ops run as code).

```
Priority = (Value × Durability × Alignment × DependencyReadiness) / Cost
```

| Factor | Scale | What it means |
|---|---|---|
| **Value** | 1–5 | Expected $ / edge / risk-reduction if it works. Income or yield or drawdown-cut all count. |
| **Durability** | 0.5–2.0 | Does the edge/capability *persist*? Regime-robust, structural, reusable across strategies = high. One-regime trick = low. **This is the anti-overfit multiplier** — a brilliant in-sample result with no durability story scores ≤0.5. |
| **Alignment** | 0 or 1 | Bybit-only? Within doctrine? Serves stable-growth-#1 / capital-preservation-#2? **0 = auto-reject, no score.** (Kills the US-stocks/MT5 runaway class of idea at the rubric.) |
| **DependencyReadiness** | 0.25–1.0 | Are its prerequisites already RELEASED? Ready = 1.0; needs an unbuilt dependency = 0.25 (and it cannot enter IN-BUILD until the dependency ships). |
| **Cost** | 1–5 | Build effort + ongoing run-cost (tokens, compute, data, maintenance). The cheapest module is the one that doesn't run — recurring cost is weighted, not just build cost. |

**Decision rule:** rank by Priority. Promote top items into IN-BUILD **only up to the WIP limit**. Anything scoring **Alignment 0** or **Durability ≤ 0.5 with no durability evidence** is declined with a logged lesson. Score and rationale are written into the backlog item — no silent reprioritization.

**WIP limit:** at most **2 modules IN-BUILD + 1 strategy IN-BUILD** at any time across the firm (tunable by the Board; default reflects the 10-agent lean roster). New work cannot start while WIP is full — it waits in APPROVED. This is the primary anti-bloat throttle.

---

## 4. The spec → build → validate → release path for a new MODULE

Same gates as a strategy. A module is *anything* added to the product; strategies are just the most common kind.

**Stage A — SPEC (Head of Research → MD approves)**
`specs/<module>.md` must contain: problem statement; proposed interface (how it plugs into the *one* engine — modules are injected, never per-module scripts); **acceptance criteria** (the measurable bar V&R will check); the **durability hypothesis** (why this edge/capability persists); cost estimate; dependency list. MD approves → item moves APPROVED. No spec, no build.

**Stage B — BUILD (Head of Engineering → Platform/Strategy Engineer)**
- Branch off main. Implement as a plugin/module into the single engine. **Never a standalone script** (hard lesson from the runaway).
- **Engine tests required**: unit tests for the module + the existing engine regression suite must stay green. New engine capability ships with the test that proves it.
- Cost-real where it touches PnL: model Bybit taker (~0.055%) + slippage + realistic fills; data from Bybit public REST.
- Bump `__version__` (SemVer), draft the CHANGELOG entry.

**Stage C — VALIDATE (Head of Validation & Risk — independent, hard veto)**
- Verifies acceptance criteria are *actually* met (reads it back — counters hollow completions).
- For strategy/PnL modules: ≥30 trades (else "noise"), cost-real, **out-of-sample** holdout, no in-sample-only brilliance, durability hypothesis survives OOS.
- For engine/infra modules: tests green, deterministic, no hidden network/persistence side-effects, doesn't widen risk surface.
- **Merge-to-main IS the V&R gate.** V&R sign-off = the merge. A fail returns the item to IN-BUILD with a written reason. Only the Board overrides a fail.

**Stage D — FORWARD-TEST (strategy/PnL modules only, Head of Execution/Ops)**
≥3-week paper/demo forward-test before any live arming. Engine/infra modules skip this but still must run clean in demo for one full cycle.

**Stage E — RELEASE (Head of Engineering)**
- Tag a SemVer release; finalize `CHANGELOG.md`.
- `ztb run` pins to the new tag only after sign-off. Bleeding `main` never trades. Rollback = `git checkout <prev tag>`.
- Item → RELEASED. Backlog updated; WIP slot freed.

---

## 5. Guardrails (never bloat, overfit, or burn cost)

1. **WIP limits** (§3) — the hard throttle on how much can be in flight. Full = new work waits.
2. **Daily cost-guard** (existing `cost-guard.js`, 10-min timer) — pauses agents + Discord-alerts + stops the service on a spend / task-rate / concurrency spike. Self-development cannot outrun the $50 AUD/mo ceiling. Build-cost and recurring run-cost both feed the rubric's `Cost` term, so expensive-to-run modules are penalized *before* they ship.
3. **The Three-Outcomes Rule (the heartbeat):** **every R&D cycle MUST end in exactly one of —**
   - (a) a merged **engine improvement** (capability or test), OR
   - (b) a **proven plugin** (strategy or module past its gate), OR
   - (c) a **documented lesson** in `lessons-learned.md`.
   "Scouted, nothing survived" is a *valid, expected* close via (c) — that's the evidence gate working, not a failure. A cycle that ends with none of the three is itself a process defect the MD logs.
4. **Auto-retire (earn-their-keep sweep)** — monthly, Ops-driven, deterministic:
   - **Strategies:** if a live/forward strategy's rolling performance falls below its retirement floor (e.g. realized Sharpe < hard floor over the trailing window, or net-of-cost PnL ≤ 0 over N weeks), it is **demoted to demo / removed from the live allocation** and the slot returns to the portfolio. Logged as a lesson.
   - **Modules/features:** if a module hasn't been exercised in M cycles, or its maintenance cost exceeds its measured value, it's flagged DEPRECATE → removed in a tagged release with a CHANGELOG note. Dead code doesn't get to ride along.
   - Retirement is **reversible and tagged** — re-promotion requires re-validation, never a quiet flip.
5. **Alignment auto-reject** (rubric Alignment = 0) — anything off Bybit-only / off-doctrine dies at scoring. The runaway class of idea (US stocks, MT5, agent-spawned daemons, off-platform persistence) cannot enter the backlog.
6. **No standalone scripts, ever** — capabilities are modules in the one engine; ops run as code on timers, not as LLM calls. The cheapest agent is the one that doesn't run.

---

## 6. Meta self-improvement (the product proposing its own ideas) — with anti-overfit controls

`ztb` is allowed to **generate its own strategy ideas and run guarded parameter searches** — this is what makes it *self*-developing rather than firm-developing. But the loop is wrapped in hard anti-overfitting rails, because the doctrine's worst failure mode is in-sample brilliance mistaken for edge.

**6a. Auto-proposed strategy ideas.** A bounded `ztb propose` routine mines: the lessons ledger, the unserved-surface map, and recent regime data → emits **capability briefs into the IDEA lane** (never directly into build). They enter the *same* rubric and gates as a human-authored idea. The product can fill its own funnel; it cannot fast-track itself past V&R.

**6b. Guarded parameter / strategy search.** When searching parameters or generating strategy variants, ALL of the following are mandatory (V&R auto-fails otherwise):
- **Train / OOS / forward split is fixed up front** — the holdout and the ≥3-week forward window are reserved *before* the search runs and are touched exactly once, at the end. No peeking.
- **Multiple-comparisons penalty:** the more variants tried, the higher the bar. Report the number of configurations searched; require the survivor to clear an OOS Sharpe threshold that scales with the search size (deflated/Bonferroni-style). A backtest that's the best of 500 random configs is treated as noise until proven OOS.
- **≥30 trades** on the OOS slice — thin samples are auto-noise.
- **Cost-real always** — gross Sharpe lies; model fees/slippage/fills before any number is believed.
- **Durability hypothesis required** — the search must state *why* the surviving params should persist (structural reason), scored by the rubric's Durability multiplier. "It just fit best" → Durability ≤ 0.5 → declined.
- **Walk-forward, not single split** where feasible — robustness across multiple regimes beats one lucky window.
- **Parameter stability check** — neighbors of the chosen params must also be profitable; a knife-edge optimum is overfit and is rejected.
- **Search compute is metered** — sweeps run as code under the cost-guard; an unbounded grid that blows the budget is killed.

**Outcome of meta-search is still one of the Three Outcomes:** a proven plugin, an engine improvement (e.g. a better validation harness discovered along the way), or a documented lesson ("swept the funding-arb param space, no stable OOS edge — regime-dead, see ledger").

---

## 7. The loop, in one picture

```
HORIZON SCAN (fortnightly, Research) ─ proposes ─▶ BACKLOG (MD owns)
        ▲                                              │ score (score.py, deterministic)
        │ lessons / scorecard / cost / gaps            ▼
LESSONS LEDGER ◀── close ── CYCLE ── promote (≤ WIP) ─▶ SPEC ─▶ BUILD ─▶ V&R GATE ─▶ FORWARD-TEST ─▶ RELEASE(tag)
        ▲                  must end in 1 of 3                  (engine tests)  (merge=gate)   (≥3wk)      │
        │                                                                                                 ▼
        └──────────────── AUTO-RETIRE sweep (monthly) ◀──────────────────────── LIVE (Board-armed) ◀── ztb run @tag
        meta: ztb propose / guarded search feed IDEA lane, same gates
```

---

## 8. Definition of Done for the mechanism itself

The self-development loop is healthy when, every cycle: the backlog is scored and current; WIP ≤ limit; the cost-guard is green; every closed item produced one of the three outcomes; the retire sweep ran on schedule; and `ztb run` is pinned to a tag whose every module passed the V&R gate. The MD reports this checklist at standup. If any line fails, *that* becomes the next backlog item — the loop improves itself.

---

**Files this introduces** (all under the firm dir, none standalone executables): `roadmap/ROADMAP.md`, `roadmap/BACKLOG.md`, `specs/<module>.md`, `score.py` (deterministic rubric), plus reuse of existing `lessons-learned.md`, `CHANGELOG.md`, scorecard, cost-report, and the cost-guard. One new routine: **Horizon Scan (fortnightly, Head of Research)**. Everything else rides the gates and timers that already exist.