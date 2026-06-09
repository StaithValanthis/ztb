All facts confirmed. The grep confirms zero `max_tokens`/output cap anywhere in the kit. The model-routing-policy hard rule (line 15) explicitly forbids demoting Validation & Risk to chat — confirming the verification's mission-conflict finding. I now have everything I need to write the definitive plan with all corrections applied.

Here is the definitive cost operating manual.

---

# Zero Alpha — DeepSeek Cost-Efficiency Plan (Operating Manual)

**Cap: ≤ $50 AUD / month (~$32.50 USD at AUD/USD 0.65). As-of: 2026-06-09.**
This is the firm's cost operating manual. It is decisive, conservative, and faithful to the cost-lean doctrine: *the cheapest token is the one never sent; deterministic `ztb` code (data, backtest, forward-test, execution, reporting, dashboard, cost-guard) runs at $0; LLMs do R&D only.*

---

## 1. Pricing facts (as-of 2026-06-09)

Source: DeepSeek official docs (`api-docs.deepseek.com/quick_start/pricing`, `/guides/kv_cache`, `/guides/thinking_mode`), corroborated by CloudZero / Apidog trackers. **Re-verify live before every monthly top-up — DeepSeek changes pricing and model names often.**

### 1.1 Current rates (USD per 1M tokens)

| Model (what your aliases hit) | Input cache-miss | Input cache-hit | Output (incl. reasoning) |
|---|---|---|---|
| **deepseek-v4-flash** — *all 10 roles today* | **$0.14** | **$0.0028** (50× cheaper) | **$0.28** |
| **deepseek-v4-pro** — *scaling option only* | $0.435 | $0.003625 | $0.87 |

- Context window **1M tokens**, max output **384K**.
- **v4-pro 75% cut became permanent on 2026-05-22** (no expiry). **CAVEAT:** secondary trackers still show the old $1.74/$3.48 Pro rate — a 4× disagreement. The Pro rate only matters if/when you scale (§6); **re-verify the live Pro rate at that moment, never assume.**

### 1.2 Model mapping — ACTION REQUIRED before 2026-07-24

`deepseek-chat` and `deepseek-reasoner` are now **aliases** of `deepseek-v4-flash` (non-thinking vs thinking mode). They both bill at the **same** Flash rate. **The aliases deprecate 2026-07-24 15:59 UTC.** Before then, repoint `agents.json` to `deepseek-v4-flash` with explicit thinking/non-thinking selection, or every call errors. *Budget math is unchanged — same per-token rate.*

### 1.3 Mechanics that drive the levers

- **Reasoner ≠ pricier per token anymore.** Under Flash, reasoner and chat bill identically. Reasoner costs more *only because thinking mode emits a large `reasoning_content` chain-of-thought, billed as OUTPUT* ($0.28/M). **Output is the cost driver; reasoner output is the single biggest line.** *(Caveat: the V4 thinking-mode page does not restate the "CoT bills as output" rule; it is established convention, high-confidence but officially under-documented.)*
- **Context caching is automatic, on by default, no opt-in, no storage fee.** A cache hit requires a **byte-identical leading prefix**. Hit input is 1/50th of miss. Every response's `usage` returns `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` — your real hit-rate signal.
- **NO off-peak discount exists for V4.** The old "50% chat / 75% reasoner, 16:30–00:30 UTC" window was a V3/R1 program and is **dead**. Do not design around it. *(DEEPSEEK.md still advertises it — strike that line; §5 defect list.)*
- **NO Batch API for V4.** Do not design around a batch discount.
- **Rate limits:** no RPM/TPM caps; only concurrency (Flash 2,500 / Pro 500). For a 10-agent firm, concurrency is never the wall. **Spend is the only wall.**
- **Prepaid hard wall:** balance is topped-up; granted balance spends first; **no overdraft** — at $0 balance, calls fail rather than incur debt. **CAVEAT:** a built-in low-balance email alert is unconfirmed — assume you must poll balance yourself (§5).

---

## 2. Expected monthly spend & headroom vs the $50 AUD cap

Modeled conservatively. The firm is LLM-light: one MD R&D review every 2 days + event-driven hand-off chains (research→spec→build→backtest→validate→release), one task per run, no idle routines.

**Per-run cost (current Flash rates):** chat run ≈ 7.5k in + 2.5k out ≈ **$0.0018/run**; reasoner run ≈ 9k in + 7.5k out (6k CoT + 1.5k answer) ≈ **$0.0034/run**. Reasoner ~2× a chat run, driven entirely by output.

| Scenario | chat / reasoner runs/mo | Flash USD | **Conservative stress** (old R1 rates)¹ | AUD | % of cap |
|---|---|---|---|---|---|
| **Optimistic** (lean burst, cache hits) | 150 / 80 | ~$0.4 | ~$1.7 | ~$2.6 | ~5% |
| **Expected** | 216 / 124 | **~$0.8** | ~$3.5 | **~$1.2–5.4** | **~3–11%** |
| **Pessimistic** (2 milestones, fat context, re-loop churn, no caching) | 350 / 220 | ~$2.0 | ~$8.5 | ~$3–13 | ~6–26% |

¹ *Stress column prices reasoner at the retired $0.55/$2.19 R1 SKU — a deliberate 4–8× overstatement so the conclusion survives even if billing reverts.*

**Verdict: fits with enormous headroom.** Expected ≈ **$0.8 USD (~$1.2 AUD) on current rates**, ~$3.5 USD (~$5.4 AUD) on the conservative stress — **3–11% of the cap**. Even a brutal two-milestone month stays under ~26%. You would need ~9× Expected throughput to approach the cap.

> **Worst-case caveat (this is the real risk, not the token math):** the above assumes the daily cost-guard works. It depends entirely on Paperclip populating `spentMonthlyCents` (confirmed: cost-guard.js:42, cost-report.js:13 read only that field). **If metering is not wired, the spend HALT never fires, the digest shows $0.00 forever, and the only true wall is the prepaid balance.** In that state a *slow, low-task-count reasoner loop* (few tasks, huge CoT each) evades every cost-guard trigger and can drain the full month's prepaid load in a day or two. **The $50 AUD guarantee rests on Layer 0 (prepaid), NOT on the daily cap.** Close this before trusting any other layer (§5).

---

## 3. Ranked levers — what the firm DOES to stay cheap

Ordered by impact. Levers 1–4 are structural (permanent efficiency at any budget); 5–7 are rationing (first to relax when the cap rises).

### 1. Model routing — reasoner only where judgment truly pays. (~20–40%)
**Do:** Keep `deepseek-reasoner` (thinking mode) for genuinely open-ended judgment only: **Managing Director** (2-day R&D prioritisation) and **Head of Research** (novel ideation). Demote **Head of Engineering** to chat + a deterministic spec-conformance rubric (its calls are mostly checklist/threshold judgments). **Save:** reasoner output dominates the bill; routing one of four reasoner roles to chat removes its CoT output.
**Tradeoff / guardrail:** Make it reversible — route per-task and escalate to reasoner only when chat flags low confidence. **HARD RULE — do NOT demote Head of Validation & Risk.** `model-routing-policy.md:15` states *"Never run the Validation & Risk decision-maker on the cheap tier — its judgment gates capital."* Saving ~$1/month by weakening the gate before live money is a bad trade for a trading firm. **V&R stays on reasoner.**

### 2. Cap output length — add a real `max_tokens`. (~15–25%, AND closes the biggest risk)
**Do:** Add a per-call `max_tokens` to the adapter config — **4,000 for chat, 8,000 for reasoner**. Demand terse structured outputs (JSON verdict: `{decision, reason ≤2 lines, next_task}`); forbid restating context or echoing the spec. **Save:** output is the priciest token class and is currently unbounded — a single reasoner run can emit up to 384K output tokens with nothing stopping it.
**Tradeoff / guardrail:** **This control does NOT exist yet** (verified: zero `max_tokens` anywhere in the kit; `maxTurnsPerRun` caps turn *count*, not tokens-per-turn). It is the single highest-value missing control and the direct mitigation for the §2 worst case. Keep the one-line `reason` field so decisions stay auditable in the lessons ledger.

### 3. Prefix-stable prompts for automatic cache hits. (~10–20% of input cost)
**Do:** Structure every invocation as **[byte-stable block first] → [variable block last]**. Byte-stable = system role / `AGENTS.md` persona / output schema / registry schema — literally identical across runs (no timestamps, run-IDs, "today is…", or spend counters in the prefix). Variable suffix = the specific task / data summary / diff, kept small and last. **Save:** cache-hit input is 1/50th of miss; the 4 judgment roles re-run the same persona every 2 days.
**Tradeoff / guardrail:** One stray interpolated byte busts the whole prefix. Add a CI lint that hashes each agent's prefix and fails on unintended drift. Monitor `prompt_cache_hit_tokens` (§5).

### 4. Trim context + feed code-generated summaries, never raw data. (~10–20% of input)
**Do:** Keep `AGENTS.md` short and role-specific (no duplicated boilerplate). Agents read the registry / lessons ledger / deterministic summary rows (metrics, verdict, top-N) — never raw OHLCV, raw backtest logs, or full dumps. `ztb` produces the compact summary at $0. **Save:** every input token is paid on cache-miss; this also keeps the variable suffix (lever 3) tiny so misses are cheap.
**Tradeoff / guardrail:** Summaries must be deterministic/code-generated so they're free, consistent, and can't hide a real signal.

### 5. Lean, event-driven cadence + low maxTurns. (~10–15%)
**Do:** One standing LLM routine only — the MD review every 2 days — and make it a **deterministic no-op early-exit** ("any new backtest/validation/release since last run? if not, skip the LLM call entirely"). Everything else event-driven. Never wake an agent on a timer "just to check." Keep `maxTurnsPerRun` low (reasoners 40, doers 30 — do not raise; each turn re-sends growing context). **Save:** the cheapest token is the one never sent; this eliminates whole calls.
**Tradeoff / guardrail:** Risk of missing a slow-burn issue between events — covered by the deterministic cost-guard, not an LLM heartbeat. *(The firm's prior runaway came from rogue minute-level routines — the no-daemons rail must stay on.)*

### 6. Push more ops into deterministic `ztb` code. (~5–15%, structural & growing)
**Do:** For each capability ask "can this be a deterministic check instead of an LLM call?" Migrate spec-conformance linting, the Sharpe>1.5/DD<15% threshold gate, dedup detection, release checklists, regression diffs to $0 systemd jobs. **Save:** each migrated job is permanent — pay once in tokens to write it, free forever.
**Tradeoff / guardrail:** Up-front engineering cost; prioritise the most-frequently-invoked LLM steps.

### 7. Strict de-dup + lessons-ledger memory. (~5–10%, growing)
**Do:** A deterministic dedup gate before any run (hash task intent vs open + recently-closed tasks; reject duplicates) plus a queryable **lessons ledger** ("mean-reversion BTC 1h, Sharpe 0.8, rejected — don't re-propose"). Registry = current state of truth so agents never re-establish context. **Save:** stops paying to re-derive dead ends.
**Tradeoff / guardrail:** Keep the ledger as a *queried store* (pull relevant rows), not a growing blob in every prompt — or it bloats the cacheable prefix and inverts the saving.

> **Struck lever — off-peak scheduling.** Previously listed as ~50% off. **Dead on V4** (§1.3). Do not schedule timers into 16:30–00:30 UTC expecting a discount; there is none. Savings come from caching + bounded output, not scheduling.

**Combined:** levers 1–3 plausibly cut spend 50–70% vs a naive verbose/prefix-unstable setup. **Highest-impact single action: add `max_tokens` (lever 2)** — it both saves tokens and closes the worst-case loop.

---

## 4. Concrete config

### 4.1 Prepaid load (Layer 0 — the only guaranteed wall)
- **Load $30 USD/month. Never enable auto-recharge.** $30 USD ≈ $46 AUD at 0.65 — under the ceiling with ~$4 AUD FX headroom (survives AUD falling to ~0.60).
- Set a DeepSeek console **balance alert at $10 USD remaining**.
- **Top up manually, monthly, only after reading the prior month's cost digest.** Carry unspent balance — don't reload to $30 on top of a $26 balance.
- After 2–3 months confirm single-digit spend, **ratchet the load down toward $25 USD** (worst case ~$38 AUD).

### 4.2 Daily cap (Layer 1 — the active control)
- **`COST_DAILY_CAP_CENTS = 110`** (≈ $1.10 USD/day). Alert 70% (~77c), HALT 90% (~99c). Resets each calendar day.
- Its job: bound a runaway's blast radius to **one day (~$1.65 AUD)**, not the month.
- **Be honest about its limit:** 110c × 31 = $34.10 USD ≈ **$52.5 AUD** — the daily cap *alone* can exceed $50 AUD in a 31-day month. The AUD ceiling holds **only because Layer 0 ($30 prepaid) caps it below**. Layer 1 is not independently sufficient.

### 4.3 Per-agent `budgetMonthlyCents` (all 10 — replace stale budgets.json)
Authoritative roster is `agents.json` (sum **2640c = $26.40 USD ≈ $40 AUD**), under both the $30 prepaid wall (~12% headroom) and the $50 AUD ceiling.

| Agent | Model | budgetMonthlyCents |
|---|---|---|
| Managing Director | deepseek-reasoner | 400 |
| Head of Engineering | deepseek-reasoner¹ | 350 |
| Head of Research | deepseek-reasoner | 300 |
| Head of Validation & Risk | deepseek-reasoner | 300 |
| Platform Engineer | deepseek-chat | 300 |
| Strategy Engineer | deepseek-chat | 300 |
| Validation Engineer | deepseek-chat | 250 |
| Market Analyst | deepseek-chat | 200 |
| Head of Operations | deepseek-chat | 120 |
| Ops Engineer | deepseek-chat | 120 |
| **TOTAL** | | **2640 ($26.40)** |

¹ *If you adopt lever 1, Head of Engineering moves to `deepseek-chat`; budget unchanged. MD, Research, V&R stay reasoner.*

### 4.4 Model routing
- **Reasoner:** MD, Head of Research, Head of Validation & Risk (and Head of Engineering unless demoted per lever 1).
- **Chat:** everyone else. **Repoint `deepseek-chat`/`deepseek-reasoner` → `deepseek-v4-flash` (thinking/non-thinking) before 2026-07-24.**

### 4.5 maxTurnsPerRun & max_tokens
- `maxTurnsPerRun`: reasoners 40, doers 30 (as set — do not raise).
- **`max_tokens` (ADD — does not exist yet):** chat **4000**, reasoner **8000**, in the adapter config. This is the missing output bound.

### 4.6 Cost-guard thresholds (cost.env)
| Signal | Threshold | Action |
|---|---|---|
| Daily spend ≥ 70% (≈77c) | `ALERT_PCT=0.7` | Discord ⚠️ (once/day on level-change) |
| Daily spend ≥ 90% (≈99c) | `HALT_PCT=0.9` | **HALT**: pause all agents + stop Paperclip + Discord 🛑 (manual reset) |
| Tasks > 25 / 20 min | `COST_MAX_TASKS=25`, `COST_WINDOW_MIN=20` | **HALT** (runaway/dup signature) |
| Concurrency > 6 | `COST_MAX_CONCURRENT=6` ⬅ **tighten from 8** | Discord ⚠️ |

Runs every 10 min, deterministic, $0. Tighten concurrency to **6** — with 10 agents, 8 is 80% of the roster and barely detects fan-out; normal operation is a 2–4 agent hand-off chain.

### 4.7 cost-report soft cap
- Set **`COST_SOFT_CAP_CENTS = 2640`** (currently defaults to 3000) so the digest's "% of cap" tracks the real per-agent roster sum.

---

## 5. Guardrails & ownership

### 5.1 Cost-guard behaviour (primary enforcer, $0 tokens)
Three-layer defense; **the AUD guarantee rests on Layer 0.**
- **Layer 0 — prepaid balance:** physical hard wall; no bug crosses it.
- **Layer 1 — daily cost-guard:** alert 70%, HALT 90% / task-spike / concurrency. Bounds a runaway to one day.
- **Layer 2 — per-agent budgets:** defense-in-depth; an agent that hits `budgetMonthlyCents` stops for the month. **Enforcement is unconfirmed in Paperclip — verify it actually hard-stops; until then Layers 0+1 carry the line.**

**Two mandatory fixes before trusting Layers 1–2 (load-bearing — the metering blind spot is the firm's biggest structural risk):**
1. **Prove metering end-to-end.** Run one real DeepSeek call and confirm `spentMonthlyCents` increments in the Paperclip API. If it stays 0, the spend HALT is blind and the digest lies — **do not rely on the daily cap until proven.**
2. **Add a balance-poll backstop independent of Paperclip.** In `cost-guard.js`, poll DeepSeek's own balance endpoint and HALT on a daily *balance-delta* exceeding the cap. This is the one signal that's true even if `spentMonthlyCents` is broken — and it doubles as the low-balance alert DeepSeek may not provide. Wire `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` into the log to monitor cache hit-rate (lever 3).

### 5.2 Ownership
- **Deterministic cost-guard** — primary enforcer. No judgment, no tokens, cannot be argued with.
- **Head of Operations** (cheap, `deepseek-chat`, 120c) — owns the daily `cost-report.js` digest (22:00 Discord: MTD spend, % of cap, top spenders), watches drift, *recommends* reallocations to the MD. **May only tighten/recommend — never raise caps** (no fox guarding the henhouse).
- **You / the Board** — sole authority to edit prepaid load, daily cap, per-agent budgets.

### 5.3 Review cadence
- **Continuous (10 min):** cost-guard circuit-breaker.
- **Daily (22:00):** `cost-report.js` digest — read it passively.
- **Monthly (at top-up):** human review + reload decision — the *only* time caps change. Re-verify live DeepSeek pricing here. **Drop any weekly LLM cost-review routine** (the v3 firm had one — a daily deterministic digest + monthly human review is cheaper and sufficient).

### 5.4 Defects to fix before go-live (verified against the deploy files)
1. **`cost/budgets.json` is the stale 27-agent v3 roster** (Chief Strategist, CRO, Order Placer…, sum 3070c). Regenerate from `agents.json` (the 10 rows above, sum 2640c) and fix its `_note`. *(It's applied at setup as per-agent caps; note `cost-report.js` reads live API spend, not this file — fix it for the setup caps, not the digest.)*
2. **`COST-MANAGEMENT.md`** says "$30.70 / 3070c" — correct to **$26.40 / 2640c**.
3. **`DEEPSEEK.md`** — strike the off-peak-discount line (dead on V4) and the V3/R1 + 27-agent references.
4. **No `max_tokens` anywhere** — add per §4.5.
5. **`cost-guard.js`** — tighten `MAX_CONCURRENT` to 6; add the balance-poll backstop.
6. **Before 2026-07-24** — repoint aliases to `deepseek-v4-flash`.

---

## 6. Scaling (if the cap rises)

One knob: **`k = new_AUD_cap / 50`**, applied top-down. The layered guarantee is preserved.

| Lever | $50 (k=1) | $100 (k=2) | $200 (k=4) |
|---|---|---|---|
| Prepaid wall (USD) | $30 | $60 | $120 |
| Daily cap (cents) | 110 | 220 | 440 |
| Per-agent budgets sum | 2640c | 5280c | 10560c |
| Concurrency / task-rate | 6 / 25 | unchanged | unchanged |
| Review cadence | monthly | monthly | bi-weekly |

**Rules so it stays clean, not just bigger:**
- **Re-derive the prepaid wall from FX each step:** `prepaid_USD = new_AUD_cap × 0.65 × 0.92` (the 0.92 keeps ~8% FX headroom). Never just double a USD number — a falling AUD can't breach it that way.
- **Scale daily cap + per-agent budgets by `k` together;** keep the per-agent sum ≤ 85% of the prepaid wall (88% today).
- **Safety thresholds scale with HEADCOUNT, not dollars.** A bigger budget on the same 10 agents must not loosen the runaway detector. Only raise concurrency/task-rate if you add agents: `MAX_CONCURRENT ≈ 0.6 × agent_count`, `MAX_TASKS ≈ 2.5 × agent_count` per 20 min.
- **Spend the increase on capability, not noise:** prefer raising the reasoners' budgets/`max_tokens`, re-enabling a demoted reasoner role, or adding a specialist — over loosening safety thresholds. Migrating work to deterministic `ztb` beats more tokens every time.
- **Structural levers (1, 3, 4, 6, 7) keep paying at any budget** — raising the cap buys *more research per dollar*. Rationing levers (2, 5) relax first.
- **Promoting the 4 judgment roles to `deepseek-v4-pro`** is the natural quality upgrade — **but re-verify the live Pro rate first** (sources disagree 4×; at the old $3.48/M output a Pro reasoner run is ~12× Flash, not 3.1×). Promote only after confirming the rate.
- **At k ≥ 4, tighten review to bi-weekly** — a bigger cap means a bug's daily blast radius is bigger.

Implementation at any step: one edit to `cost.env` + a `×k` pass over `budgets.json` + a new manual top-up. No structural change.

---

### Bottom line
Expected spend is **~$1–5 AUD/month against a $50 AUD cap (3–11%)**, with vast headroom in every realistic case. The cap is never the binding constraint — LLM use is structurally tiny by design. **The real risk is not token math; it is the metering blind spot.** Ship the two load-bearing fixes — **(1) prove `spentMonthlyCents` is wired, (2) add `max_tokens` + a balance-poll backstop** — and the $50 AUD ceiling is guaranteed by the prepaid wall regardless of any bug.