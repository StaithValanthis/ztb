# ztb — Expansion Roadmap (Horizon 1/2/3)

Produced from an 8-dimension explore + adversarial vet of 102 candidate features.

## Top picks (highest value-per-cost)
- Refined transaction-cost/slippage model — centralize the copy-pasted per-script cost logic (0.055% taker + borrow + slip) into ONE calibrated conservative/expected/optimistic module; the single best lean move, the seam for engine consolidation, and the antidote to 'gross Sharpe lies'
- Reproducibility + look-ahead audit + cost-attribution harness — pin data-hash/git-SHA/seed, shift-by-one leak tripwires, decompose P&L into fees/funding/slippage/alpha; the evidence-gated doctrine made executable and the forcing function for one-engine consolidation
- Volatility-targeted position sizing — highest-Sharpe-per-effort risk primitive; turns the vague 25% DD limit into a sizing rule by construction on existing kline data, with a rebalance deadband to avoid over-trade cost-bleed
- Funding-rate harvest engine (delta-neutral carry) — the single best edge on the list, Bybit-native and deterministic; consolidate the existing ZERA-119 work into the product with honest net-of-funding±borrow±Earn modeling and a >=30-event carry-threshold gate
- Walk-forward / OOS validation harness — the literal antidote to the firm's hardest scar (IS Sharpe 3.69 -> OOS -16.79) and the hard prerequisite for any ML; makes every later bet cheaper to validate
- Cost-and-Edge Reality Engine — per-strategy live edge attribution on the bot's own fills; decomposes net edge vs backtest expectation and auto-throttles decay, enforcing the <30-trade noise floor; the core self-development guardrail
- Bybit Earn (Flexible-Savings-only) sweep — lowest-effort, highest-certainty win: deterministic no-LLM APR on idle collateral with a buffer; fence off On-Chain Earn as off-doctrine
- Pre-trade risk & order-safety gate (preflight) + Heartbeat/watchdog + Layered circuit-breakers — the non-negotiable operational backbone that turns code bugs into rejected-orders-plus-alert instead of liquidation; required before any live arm

## Horizon 1 — Validation & cost-realism infrastructure (build FIRST — the doctrine made executable)

### Refined transaction-cost, slippage & cost-model module  _(Cost modeling, effort M)_
- **Why:** Maximally durable — codifies the central scar 'gross Sharpe lies'; every strategy in every regime routes through it, and funding-sign/borrow accrual alone flip carry results (L-002). The cost logic is already copy-pasted and drifting across every bespoke script (0.055% taker + borrow + 0.05% slip hardcoded per file); centralizing it is the single best lean move.
- **Depends on:** Nothing — it IS the natural seam to start engine consolidation. Ship the fee/funding/borrow/spread stack first; defer the uncalibratable market-impact term.

### Reproducibility, look-ahead audit & cost-attribution harness  _(Validation infrastructure, effort M)_
- **Why:** The connective tissue of a self-developing, evidence-gated product; its value compounds as the bot proposes its own strategies. Given scattered scripts and result JSONs with no pinned data-hash/SHA/seed, this is the highest-ROI infra: pin snapshot-hash+SHA+seed, run shift-by-one leak tripwires, decompose P&L into fees/funding/slippage/alpha. Forces consolidation onto one engine.
- **Depends on:** Pairs with the cost model; requires immutable (not mutate-in-place) data snapshots. Leak probes are a smoke test, not a proof.

### Walk-Forward / Out-of-Sample validation harness  _(Validation infrastructure (ML safety gate), effort M)_
- **Why:** The literal antidote to the firm's hardest lesson (IS Sharpe 3.69 -> OOS -16.79) and the safety gate for the whole self-developing goal. Permanent meta-infrastructure that does not decay; makes every other bet cheaper to validate and is a hard prerequisite for ML.
- **Depends on:** Must consolidate the 10+ bespoke backtest_zera*.py scripts onto one engine first (so effort is realistically M-to-L). Builds on the cost model + repro harness.

### Monte-Carlo robustness suite (block-bootstrap, trade-shuffle, equity resample)  _(Robustness / validation, effort S)_
- **Why:** Cheap pure-post-processing over trade ledgers the scripts already emit; path-risk distributions feed the <=25% DD constraint and kill-switch sizing. Use block bootstrap (iid understates trend DD) and gate on the >=30-trade floor or it just dresses up noise.
- **Depends on:** Existing trade-log CSVs; real bite only on the few survivors that clear the trade-count floor.

### Experiment & Run Tracker + registry  _(Experiment tracking, effort M)_
- **Why:** Institutional memory that lets a self-developing product know what it already tried — directly fights the recycled-candidate/contamination problem the firm already hit. Foundational substrate for the entire self-improvement goal.
- **Depends on:** Must be wired INTO the engine (not bolted on) with data-cache content hashes, or agents bypass it and it rots. Keep the schema tight.

### Overfitting Sentinel / Validation Statistician  _(Anti-overfit guardrails, effort M)_
- **Why:** Encodes the hard lessons (>=30 trades, net not gross Sharpe, multiple-testing/deflated-Sharpe penalty) as an automatic referee. Deflated-Sharpe under multiple testing is the dominant failure mode for a self-proposing system.
- **Depends on:** Wraps the validation harness exports. Build trade-count/net-Sharpe/deflated-Sharpe checks first; defer plateau/regime-stability.

## Horizon 1 — Risk primitives & live-safety backbone (required before any live arm)

### Volatility-targeted position sizing  _(Risk / volatility scaling, effort M)_
- **Why:** Highest-leverage risk primitive on the list and one of the few techniques with robust regime-independent OOS evidence; it is a sizing rule not an alpha bet, so it does not decay. Turns the vague 25% DD limit into a sizing rule by construction; every later module (Kelly, VaR, throttle) sits on top of it.
- **Depends on:** Existing kline/cache data only. Build with a rebalance deadband + jump floor to avoid the documented over-trading cost-bleed.

### Pre-Trade Risk & Order Safety Gate (preflight)  _(Execution safety, effort M)_
- **Why:** Most real bot disasters are dumb order bugs (wrong size, stale price, runaway loop, leverage breach). Non-negotiable prerequisite for arming live — turns code bugs into rejected-order+alert instead of liquidation/rate-ban.
- **Depends on:** Bybit instruments-info + orderLinkId idempotency; must refresh instruments-info, handle per-category quirks, persist client-order-ids across restarts.

### Live Heartbeat & Watchdog Monitor  _(Live monitoring & alerting, effort M)_
- **Why:** A silent stall can liquidate you while 'running'; liveness failure modes (WS drop, hung process, stale wallet) are permanent risks for any unattended leveraged bot, independent of strategy or regime. Cheapest high-leverage safety module.
- **Depends on:** Ship before any live arm with dedup/rate-limited alerts and a narrow safe-state power only.

### Layered Circuit-Breaker Cascade  _(Circuit breakers / kill-switches, effort M)_
- **Why:** The single 25% all-or-nothing kill-switch is genuinely brittle. First build the operationally load-bearing tiers (data-staleness, velocity/loss-rate, order-reject storm) plus graduated portfolio de-lever at 15/20%.
- **Depends on:** Feeds off heartbeat signals. Defer per-strategy Sharpe-decay breakers (no strategies to break yet); default higher tiers to human-arm-to-resume.

### Per-Trade Risk Budgeting & Drawdown-Adaptive Throttle  _(Risk budgeting / governor, effort S)_
- **Why:** Anti-Martingale (risk less while losing) is the simplest robust defense against a streak compounding to a blow-up — the Board's stated worst fear. Turns the 25% DD limit into an enforced, continuously-debited budget that cannot be overspent.
- **Depends on:** Tie budget debit to component-VaR (not naive additive). Calibrate the throttle so it dampens tails without neutering normal variance.

### Parametric+Historical VaR / CVaR module  _(Risk metrics, effort S)_
- **Why:** Cheap, deterministic, code-not-LLM; gives one board-legible 'worst-day' number plus a component view to find the risk hog. Lead with historical-sim + Cornish-Fisher CVaR; skip parametric-normal VaR which lies in fat-tailed crypto.
- **Depends on:** Pair with the liquidity guard so the number isn't fiction; gate on sample size.

### Funding-Rate Risk & Carry-Aware Exposure Manager (cost-side only)  _(Funding / carry risk, effort S)_
- **Why:** Funding is a large predictable drag on any held perp; this makes net-of-funding edge honest on every position, directly enforcing 'gross Sharpe lies, model costs'. Adopt ONLY the cost/penalty + crowded-funding squeeze-flag half.
- **Depends on:** Bybit funding/history endpoint. Explicitly do NOT build the funding-capture sleeve here (that lives in the harvest engine).

## Horizon 1 — First real edges & yield (Bybit-native, deterministic, backtestable today)

### Bybit Earn (Flexible-Savings-only) sweep  _(Yield / mechanism coverage, effort S)_
- **Why:** Lowest-effort, highest-certainty win in the entire set: deterministic, no-LLM, near-risk-free APR on idle collateral that compounds toward the goal. Set-and-forget with a strategy buffer.
- **Depends on:** A strategy cash buffer for redemption latency. Explicitly fence off On-Chain Earn (smart-contract/lockup risk, off-doctrine).

### Funding-Rate Harvest Engine (delta-neutral carry)  _(Strategy — funding/basis capture, effort L)_
- **Why:** The single best edge on the list: structurally persistent (funding is paid by leveraged directional flow, not you), Bybit-native, deterministic and backtestable. Capacity-constrained smallness is a moat here, not a liability. The firm already half-built it (ZERA-119).
- **Depends on:** Cost model + repro harness (for honest net-of-everything accounting). Consolidate ZERA-119; gate on net-of-borrow funding and >=30 funding events/symbol or it's noise.

### Funding-Rate Term-Structure & Carry signal module  _(Data source / derivatives signal, effort S)_
- **Why:** Highest value-per-dollar data lane — tiny 8h-cadence storage, plain REST; opens the diversifying yield lane and feeds the harvest engine. MUST emit NET-of-cost carry to respect the 'basis-arb regime-dead' lesson.
- **Depends on:** Cost model. Feeds the funding harvest engine and the regime classifier.

### Spot-Perp Basis signal module  _(Data source / derivatives signal, effort S)_
- **Why:** Trivially cheap (derived from data already pulled) and completes the carry picture by netting with funding. Adopt strictly as the cost-clearing PROOF/gate that shows WHEN carry clears costs, never as an assume-it-works arb.
- **Depends on:** Funding term-structure module; mostly perp-vs-spot since Bybit quarterly listings are sparse.

### Cost-and-Edge Reality Engine (per-strategy live edge attribution)  _(Self-development guardrail, effort M)_
- **Why:** Operationalizes the deepest doctrine ('gross Sharpe lies', 'in-sample brilliance != edge'); pure analysis on the bot's own fills/fees/funding/marks to decompose net edge vs backtest expectation and auto-throttle decayed strategies. The core mechanism of a self-developing product.
- **Depends on:** Cost model + repro harness. Enforce the <30-trade noise floor before acting so variance doesn't ping-pong strategies on/off.

### Funding-Settlement Timing (collect-side only)  _(Funding/basis capture, effort S)_
- **Why:** Funding is a scheduled deterministic cashflow; ensuring carry positions are on the book at snapshot is a cheap perpetual net-cost improvement. Natural extension of the harvest engine.
- **Depends on:** Funding harvest engine. Gate the trim-to-dodge side HARD (only when funding > round-trip cost) or it leaks fees dodging payments smaller than the trades to dodge them.

## Horizon 1 — R&D governance & self-development rails (keep the loop cost-lean)

### Spec->Build->Validate->Release Module Pipeline (assembly line)  _(Module lifecycle / dev pipeline, effort L)_
- **Why:** The whole evidence-gated doctrine made executable; the real win is making a validated tagged release the ONLY door to trade-eligibility. Partially exists (agent specs + acceptance-gates + registry as release door) but is informal.
- **Depends on:** Validation harness + overfitting sentinel feed its gates. Forward-test is calendar-bound, so feasibility is the limiter.

### R&D Cost Ledger & Compute/LLM Budget Governor  _(Cost governance, effort S)_
- **Why:** Enforces the firm's defining cost-lean constraint as a hard control; high-leverage given idea-gen and param-search are the cost-runaway sources ('cheapest agent is the one that doesn't run').
- **Depends on:** Must hard-separate R&D budget from trading ops so a compute pause can NEVER touch the kill-switch.

### Living Backlog & Roadmap Store (roadmap.yaml + ledger)  _(Backlog/Roadmap infrastructure, effort S)_
- **Why:** Durable substrate whose provenance/kill-reasons compound in value. Already ~70% exists (retest-queue.json + events.jsonl + registry.json) — adopt as CONSOLIDATION into one canonical append-only store with first-class KILL reasons, not a greenfield build.
- **Depends on:** None; feeds the prioritizer and experiment tracker.

### Human-Board Decision Queue & Promotion Gate UI  _(Governance / human-in-the-loop, effort S)_
- **Why:** The human live-arming gate is doctrine and must have exactly one door. Largely exists (registry enforces 'no agent may set live_enabled', Discord notifier present) — consolidate the evidence trail and surface only true Board decisions.
- **Depends on:** Release pipeline; zero side-doors to live arming. Strict criteria to prevent rubber-stamp fatigue.

## Horizon 2 — Adaptive layer & regime awareness (operationalize the hard lessons)

### Regime classifier + strategy router (deterministic)  _(Regime-adaptivity, effort M)_
- **Why:** Converts already-learned regime-conditional failures ('basis dead on compression', 'low-vol grids lose to costs') from passive warnings into active on/off capital-allocation guards. Pure computation on Bybit data.
- **Depends on:** Cost model (so per-regime attribution is honest) + validation harness (to certify labels OOS). Keep rules-based with few free thresholds, point-in-time (no HMM-smoother look-ahead).

### Historical-Volatility / realized-vol regime classifier  _(Derived data / volatility, effort M)_
- **Why:** The realized-vol regime label is the master switch that EXPLAINS the firm's hard lessons (why low-vol grids and basis-arb die); gates carry/grid strategies on/off. Native and cheap.
- **Depends on:** Keep thresholds OOS-validated to avoid curve-fit. Defer the implied/VRP half until an options module exists.

### Volatility breakout strategy family (gated experiment)  _(Volatility strategies, effort M)_
- **Why:** A genuine directional sleeve, but regime-dependent and decay-prone — explicitly the separate, gated half of the vol bundle, NOT shipped with the vol-targeting overlay.
- **Depends on:** Vol-targeting sizing + validation harness + regime classifier. Treat as one experiment among many, hard-gated on net Sharpe.

### Cross-sectional momentum & mean-reversion portfolio (rank-based)  _(Trend/momentum + cross-asset, effort M)_
- **Why:** Among the more durable systematic crypto edges and genuinely market-neutral; spawns many sub-strategies for the self-developing goal. The market-neutral construction is the durable part.
- **Depends on:** Cost-real backtesting + no-trade bands + a liquidity screen; rebalancing churn and alt borrow/squeeze are the killers. Gate hard on net Sharpe.

## Horizon 2 — Portfolio brain & capital allocation (only once survivors exist)

### Walk-Forward Optimization harness (parameterized-strategy gate)  _(Robustness / validation, effort M)_
- **Why:** Best offline proxy for live and directly attacks the in-sample-brilliance scar; the gate keeps mattering as long as the firm proposes parameterized strategies.
- **Depends on:** There is NO single engine to wrap yet — must finish consolidating the bespoke scripts onto one engine first, which is why this is H2 and effort-M-to-L in practice.

### Regime-Switching Meta-Strategy Allocator  _(Regime-switching meta-strategy, effort L)_
- **Why:** High-leverage for curve-smoothing, but is itself a model that can curve-fit in disguise. Keep it dead-simple and rule-based (not HMM) to stay durable.
- **Depends on:** Adopt ONLY after the validation harness can certify regime labels OOS. Consider merging with the regime router/portfolio risk-allocator.

### Portfolio-level risk-allocator & strategy-correlation manager  _(Portfolio construction, effort L)_
- **Why:** The brain the self-developing firm needs to avoid secretly concentrating long-BTC-beta. The need is durable (combining survivors is the core unsolved problem).
- **Depends on:** Premature until enough strategies survive forward-test to estimate correlations. Use capped fractional-Kelly only, recompute slowly; consider merging with the regime allocator.

### Fractional-Kelly capital allocator (1/4-Kelly w/ shrinkage)  _(Capital allocation, effort M)_
- **Why:** Sound mechanism for sizing across edges, but Kelly amplifies estimation error — the exact in-sample-brilliance trap. Ship as a thin shrinkage layer, not a full allocator.
- **Depends on:** Needs 2-3 forward-tested edges to allocate across (portfolio currently N=0). Sits on top of vol-targeting + VaR.

### Correlation-aware group exposure cap (simple heat-cap first)  _(Portfolio construction / diversification, effort L)_
- **Why:** Crypto diversity collapses to BTC-beta in crashes; the doctrine's own rule (cap exposure per underlying-driver group) gets ~80% of the benefit as a ~20-line heat-cap. Static covariance gives false safety.
- **Depends on:** Implement the simple group cap now; defer cvxpy optimization until the roster is real and only on downside correlation.

## Horizon 2 — Live-ops feedback loop (closing the cost-realism loop)

### Paper-vs-Live Execution Reconciler  _(Paper-vs-live reconciliation, effort M)_
- **Why:** Doctrine-central: directly tests 'gross Sharpe lies so model costs' against Bybit's actual fills/fees/funding, and catches state drift (bot flat, Bybit long). The data substrate for decay/attribution/canary.
- **Depends on:** Only works if the live loop durably journals intended-vs-sent orders — build that journaling first.

### Performance Attribution Engine  _(Performance attribution, effort M)_
- **Why:** Decomposes PnL into direction vs funding-carry vs fees vs slippage — tells you if an 'edge' is real or just carry; a question that never goes stale. High allocation value.
- **Depends on:** Rides the reconciler's ledger. Inverse perps are coin-margined (PnL in BTC) — normalize to a base currency or the table lies.

### Strategy Decay / Drift Detector  _(Strategy & model drift detection, effort M)_
- **Why:** Operationalizes 'never overfit' on the live side and feeds retirement. Edges do die.
- **Depends on:** After the reconciler supplies clean PnL. Gate hard on pre-registered min-sample and a tiny fixed metric set, or you retire good strategies on variance.

### Canary / Staged-Capital Rollout Controller  _(A/B + canary deploys, effort M)_
- **Why:** Caps blast radius of paper-good/live-broken strategies — the firm's exact failure mode; regime-agnostic risk-budget governor.
- **Depends on:** On a small demo book a 5% canary often falls below per-symbol min-notional — needs a per-symbol min-lot floor and 'skip canary if untradeable' rule; never exceed Board risk budget.

### Scheduled Re-Validation / Walk-Forward Cadence Runner  _(Scheduled re-validation cadence, effort M)_
- **Why:** Continuously re-enforces the evidence gate on fresh data and catches silent regime/param drift for free; mostly orchestration over the existing backtester/cache.
- **Depends on:** Validation harness. Adopt only with OOS-scored walk-forward and a hard rule that re-fit PROPOSES, never mutates a tagged live release (the re-fit path is itself a re-overfitting trap).

### Spec-as-Contract Test Harness & Auto-Regression Suite  _(Build-quality guardrails, effort M)_
- **Why:** The missing safety net for the firm's biggest liability — a sprawl of per-strategy scripts; the look-ahead/leakage assertion is a real anti-overfit defense.
- **Depends on:** Only pays off AFTER consolidating onto the single plugin engine; sequence it with that refactor.

## Horizon 2 — R&D loop maturation & lifecycle hygiene

### Multi-Factor Idea Prioritizer / Scoring Engine  _(Prioritization & scoring, effort M)_
- **Why:** The cost-runaway brake on an 88-strategy backlog — top-K admission before expensive backtest is the core of cost-lean R&D.
- **Depends on:** Backlog store. Keep the weighting dead simple to avoid meta-overfitting the scorer; calibrated over time by the reality engine.

### Innovation / R&D Strategy Owner ('Head of Research' routine)  _(Ownership / orchestration, effort M)_
- **Why:** The loop-closer; an orchestrator already runs (events.jsonl shows automated research/forward cycles). Formalize as WIP-limited and mostly-deterministic.
- **Depends on:** Keep the LLM to a small bounded synthesis step per the 'cheapest agent doesn't run' doctrine; cron/event-bound, never always-on.

### Strategy Lifecycle & Decay Manager / Automated Retirement + Quarantine  _(Lifecycle / portfolio hygiene, effort M)_
- **Why:** Pruning is as valuable as proposing; with 88 strategies, decay-driven retirement prevents capital dilution and scope-bloat. Separate 'stop adding capital' (safe, automate) from 'flatten now' (conservative, Board-visible).
- **Depends on:** Consumes decay/reconcile signals; ship only after decay is proven calibrated. Require hysteresis + min-evidence window + confirmation/cooldown to avoid retire/re-add whipsaw.

### Idea Generator with hard novelty/dedup guard  _(Automated idea generation, effort M)_
- **Why:** The DEDUP GUARD is the durable, high-value part — cheaply stops re-proposing the 88 strategies and known-dead configs.
- **Depends on:** Adopt the novelty/dedup hash; be skeptical of template-grid generation (a combinatorial overfitting funnel) — cap hard, keep LLM hypotheses off by default.

## Horizon 2 — Selective data lanes & execution realism (cheap, native, build-on-demand)

### Instruments-info filter enforcement (min-notional, tick/lot, post-only/reduce-only legality)  _(Execution realism, effort M)_
- **Why:** Cheap, deterministic, high-value — catches mechanically-impossible strategies and illegal orders. The durable half of the latency/partial-fill candidate.
- **Depends on:** Fold into the execution/cost layer. Defer the latency-distribution half until calibrated against actual demo-account order timestamps.

### Liquidity-aware turnover floor / capacity governor  _(Liquidity / execution risk, effort M)_
- **Why:** The position you can't exit is what turns 15% DD into 40%; the durable ~10% is a per-instrument turnover floor that refuses thin alt-perps and far-OTM strikes, and keeps every strategy honest about fill size. Smallness is a moat IF you stay in-band.
- **Depends on:** Cheap static depth/ADV cache now; defer full stressed-depth modeling until account size grows. Adopt the governor into the risk module regardless.

### Open-Interest & positioning feed (overlay only)  _(Data source / derivatives signal, effort S)_
- **Why:** Cheap and shares plumbing with funding; a confirmation/context signal. Adopt only as part of a positioning stack.
- **Depends on:** Funding plumbing. Never trade it directly (the <30-trade noise lesson bites if you do).

### News / Macro-Event time-gate (economic calendar)  _(Alt-data / risk overlay, effort S)_
- **Why:** Cheapest high-ROI 'sentiment' input and doctrine-compatible (structured timestamps, not LLM news): flatten/halve size around CPI/FOMC.
- **Depends on:** Off-venue data dependency — needs a staleness fallback so a missed fetch doesn't silently disarm the gate. Keep the event list small and pre-committed to avoid overfitting which events 'matter'.

### Cross-sectional universe feature matrix (point-in-time)  _(Data infrastructure / feature store, effort M)_
- **Why:** Enforces one point-in-time join (killing per-module look-ahead) and enables market-neutral rank trades.
- **Depends on:** Adopt only AFTER 2-3 cheap signals (funding/basis/OI/rvol) exist to justify it. Point-in-time integrity + survivorship handling are everything.

### Risk Attribution & Capital-Efficiency Reporter  _(Risk reporting, effort M)_
- **Why:** The right closing-the-loop artifact for Board arming decisions; cheap-deterministic.
- **Depends on:** Consumer of VaR/correlation/margin/allocator outputs that mostly don't exist yet. Build lean to a few decision-driving numbers (return-on-margin, single-factor concentration alert) to avoid dashboard sprawl.

## Horizon 2 — Options & short-vol — signal-only beachhead (NO trading lane yet)

### USDC Options data layer + chain/greeks snapshotter (signal-only)  _(Data / instrument coverage, effort M)_
- **Why:** Keystone for the entire options dimension and cheap to read; scope to IV/skew SENTIMENT snapshots that overlay the perp strategies as a tail-risk gauge. The hard limit is real: no deep historical options tape, so this can only ever enable forward-tests.
- **Depends on:** Adopt ONLY if the firm commits to the months-long forward record options require; otherwise it is shelfware. This is the prerequisite gating ALL H3 options items.

### Covered-call / cash-secured-put yield overlay  _(Strategy (plugin), effort M)_
- **Why:** Theta/variance-risk-premium is one of the few structurally positive crypto edges and a genuinely low-correlation income stream — the SIMPLEST, least ruin-prone way to touch options. But it is a hidden leveraged short-vol book (caps upside, eats full downside).
- **Depends on:** Options data layer + a tail-aware sizing rule inside the 25% DD limit + a 3-week forward gate all in place. Only worth it once spot exposure is large enough to write against (premature on a $200 book).

### Maker-rebate / passive-fill execution layer (deferred half)  _(Maker-rebate capture, effort XL)_
- **Why:** Fee savings compound across every strategy — a force-multiplier, not a bet, that attacks 'costs turn brilliance into losses'. But the durable part is inseparable from adverse selection.
- **Depends on:** Effectively XL — needs a credible passive-fill + adverse-selection simulator. Adopt ONLY if the carry book actually trades enough touches to matter; never ship with 100%-fill-at-touch assumptions. Start with just the post-only-resting-fill flag in the cost model.

## Horizon 3 — Options trading lane & tail-hedging (defer until capital scales + forward tape exists)

### Protective-put / collar tail-hedge risk module  _(Risk / mechanism coverage, effort M)_
- **Why:** Long puts are the only true convex on-venue downside hedge with no liquidation risk (max loss = premium) — makes the 25% DD limit defensible against overnight gaps the kill-switch can't stop. But tail hedges bleed continuously and right-sizing the insurance budget is genuinely hard.
- **Depends on:** Options data layer + spot/options exposure large enough to insure. Premature on a $200 demo book.

### Options-aware backtest/payoff engine extension  _(Engine, effort XL)_
- **Why:** Required to model any options strategy honestly, but discrete expiry + path-dependence break vectorization and invite expiry-boundary look-ahead, and thin history forces <30-trade noise samples.
- **Depends on:** Defer until a real unified engine exists AND a forward options tape has been recorded. Realistically you are building the shared engine + options cost model that don't yet exist.

### Options Vol-Risk-Premium / short-vol harvester (defined-risk only)  _(Options vol-risk-premia, effort XL)_
- **Why:** The variance-risk premium is genuinely durable, but its expectancy lives entirely in the tail — calm-regime Sharpe is a mirage and a single gap erases months of theta. On-venue and a real diversifier.
- **Depends on:** Options data layer + options backtester + far stricter tail-risk module + scaled capital. Only ever defined-risk; revisit after carry + infra are proven.

### Short-vol / theta complex (strangles, iron condors, calendars)  _(Strategy (plugin), effort XL)_
- **Why:** 'Pennies in front of a steamroller' — most complex, most ruin-prone, least backtestable item in the set; delta-hedge round-trips can exceed theta in low vol.
- **Depends on:** Defer well past the simpler covered-call overlay; needs the delta-hedger + IV-rank + multi-leg legging support. Edge can only be forward-proven.

### Delta/Greeks hedging engine for USDC options  _(Hedging / options risk, effort XL)_
- **Why:** Economically nonsensical at current scale — a single option spread dwarfs a $200 balance, far-OTM insurance is unfillable, and Greeks/pricing code carries catastrophic-bug risk.
- **Depends on:** Park until the account is orders of magnitude larger and an options strategy has actually proven out in demo.

## Horizon 3 — Heavy infrastructure & instrument coverage (build only on proven demand)

### Portfolio-margin & liquidation-distance monitor  _(Margin risk / liquidation safety, effort M)_
- **Why:** On a leveraged UTA, liquidation/ADL bypasses your own kill-switch entirely, so Bybit's reported margin ratio is the only true catastrophe floor. Durable backstop — but only once leverage is live.
- **Depends on:** Gate the build to coincide with first leveraged go-live. Treat client-side liq math as conservative-only; lean on Bybit's reported margin ratio; validate demo-vs-live margin before arming.

### Spot-margin coverage (short/borrow leg only)  _(Instrument / mechanism coverage, effort M)_
- **Why:** The durable piece is the SHORT-spot leg — the borrow side the funding/basis trades need; borrow rate is also a crowding signal. Introduces liquidation risk and hourly interest that's easy to under-model.
- **Depends on:** Funding harvest engine demand. Adopt only that slice with honest hourly-interest accounting; the leveraged-long use duplicates perps — don't build it for its own sake.

### Resilient WS data-layer foundation (scoped on demand)  _(Data infrastructure, effort L)_
- **Why:** The keystone for any microstructure/streaming feature and the sole path to ever backtest microstructure (every live-recorded day is a forward-test asset Bybit won't sell you). Durable enabling infra, not alpha.
- **Depends on:** Build only when a near-term streaming strategy needs it; scope to ONLY those streams, with watchdogs/gap-accounting and supervised lifecycle (prior runaway-daemon lesson). Without a demanding strategy it is premature.

### Liquidation feed + cascade detector / reversion  _(Microstructure / event, effort M)_
- **Why:** Forced-liquidation overshoots are a genuinely repeatable mean-reverting pattern and a strong risk overlay, but cascade fills are awful and it is forward-test-only (no Bybit history), so the evidence gate is slow.
- **Depends on:** WS foundation + a punishing slippage assumption. Bybit's liquidation feed is sampled/throttled; survivorship-bias risk in the backtest.

### Historical & Monte-Carlo stress / scenario engine  _(Stress testing, effort L)_
- **Why:** The 'prove DD<25% survives an FTX' artifact the evidence-gated doctrine demands. But it is an arming-time gate and the firm has nothing to arm yet.
- **Depends on:** Reuses the backtest engine. When built use block-bootstrap (not iid) + explicit assumptions; run pre-arming/weekly, not per-cycle, to honor cost-lean.

### Guarded ML signal plugin (gradient-boosted / tree ensemble)  _(ML-driven (guarded), effort L)_
- **Why:** Lowest durability of any item — crypto's low signal-to-noise and non-stationarity make ML edges fragile and short-lived; in tension with the deterministic/cost-lean doctrine.
- **Depends on:** Fund LAST, strictly after the validation harness exists, with pinned/seeded inference, champion-challenger gating, and tiny sizing until it clears the same forward-test bar.

## Horizon 3 — Long-tail validation & ops polish

### Cointegration & hedge-ratio pairs engine (stat-arb v2)  _(Statistical-arb / pairs, effort L)_
- **Why:** A real upgrade over naive fixed-pair work, but crypto cointegration is notoriously unstable/spurious and two legs double round-trip cost (the exact basis-arb trap); multiple-testing inflates false discoveries.
- **Depends on:** Only fund with FDR-correction, a hard min-trades gate, and per-pair forward-testing. After the validation harness + cost model.

### A/B & champion-challenger shadow harness  _(A/B + canary deploys, effort L)_
- **Why:** Good for cheap variant screening, but shadow fills are simulated (no market impact/queue) so it flatters challengers — necessary-not-sufficient.
- **Depends on:** Defer until canary + reconciler exist; a paper win still needs a real canary. Keep dual-signal-path-clean to avoid coupling bugs.

### SLO / ops quality scorecard  _(Live monitoring (ops quality), effort M)_
- **Why:** Separating 'plumbing broken' from 'losing money' is useful, but it largely aggregates signals heartbeat+reconciler already produce; risks SLO sprawl / vanity-metric wall.
- **Depends on:** Fold the few load-bearing signals (data-freshness, job-success, reconcile-age) into the existing dashboard/digest. Defer until heartbeat + reconciler exist.

### Incident auto-snapshot & replay bundle  _(Post-incident quality, effort L)_
- **Why:** Deterministic replay turns each incident into regression coverage, but 'exact' market capture is best-effort and it is not blocking for go-live.
- **Depends on:** Scope strictly to critical events, reuse the experiment tracker for storage, scrub secrets. After the alert sources (heartbeat/SLO/reconcile) exist to trigger it.

### Multi-timeframe (MTF) point-in-time resample utility  _(Engine capability, effort M)_
- **Why:** How robust crypto strategies are built; the TF-boundary look-ahead trap is exactly the bug to fear. But it presupposes the unified plugin engine that doesn't exist yet.
- **Depends on:** Bundle the point-in-time resample utility WITH engine consolidation rather than funding it standalone.

## Avoid (tempting-but-bad)
- **Leveraged Tokens (spot lever token) coverage & rebalance-drift exploiter** — Structurally NEGATIVE durability: daily-rebalance volatility decay bleeds LTs in any choppy tape, baked-in management+funding fees, and they miss the stated multiple over any non-trending hold. A backtest ignoring rebalance drag is a textbook overfitting trap. The only use (short-hold strong-trend) is better expressed with a perp the firm already has, and the drift-exploiter version hinges on rebalance timing Bybit does not publish. Reject.
- **Maker-rebate market-making module (post-only quoting) as a standalone edge** — Canonical small-bot edge in theory but structurally unavailable here: XL streaming runtime, unfaithful kline fill-sim, retail-latency adverse selection (filled only when wrong), and near-zero rebate tier at $200 capital. A complexity trap, not an edge. Only the post-only-resting-fill flag in the cost model is worth keeping.
- **Order-book microstructure / OFI scalping & maintained-L2 strategies** — Signal half-life in seconds, colocation-sensitive, and a bar-close Python bot is too slow to act on most of it. Requires L2/streaming infra the stack lacks and book reconstruction that corrupts silently. The latency/infra cost outweighs the few robust features; revisit only if a streaming runtime is built for something else.
- **Inverse (coin-margined) perps coverage for its own sake** — Adds nonlinear coin-margined P&L math (a subtle backtest-bug and surprise-liquidation source) and a contagion surface that complicates USDT-denominated DD/kill-switch accounting, to chase a thin, less-liquid inverse-vs-linear funding spread. Marginal new edge for real complexity before the core linear book is even consolidated onto one engine.
- **Convert (RFQ) execution / cost-routing module** — Solves a problem the firm barely has on a $200 book (it isn't shuffling large illiquid collateral). Convert's spread is opaque and often WORSE than market on liquid pairs, quotes are short-lived, and it is easy to misuse as if it were alpha. Skip until rebalance volume actually hurts.
- **Cash-and-carry basis capture & dated-futures calendar/term-structure engine** — Double-counts the funding-harvest edge (perp basis ~ funding capitalized) and Bybit's thin dated coverage kills the only differentiated leg. The firm already scouted it (ZERA-111/114): ~22bps cost vs ~20bps spread = negative net edge today, with low trade frequency that fails the min-trades gate. Salvage only the regime-gate logic inside the funding engine.
- **Bespoke funding/basis backtest module (separate from the cost+regime modules)** — The lessons-ledger has buried carry twice (L-002 net -0.05%, L-004 2 trades/18 months, spread compressed to 16bps vs 120bps). The refined cost model + regime module already cover funding accrual and spread-compression detection, so a dedicated carry module is maintenance for a regime-dead edge. Don't build unless the regime module first flags carry is alive.
- **Unified-margin / cross-product portfolio-margin collateral optimizer (now)** — Genuinely valuable connective tissue ONCE the firm holds offsetting options+perp+inverse+spot legs — but premature: formulas are complex and Bybit-changed, a wrong model under-reserves and invites correlated-leg liquidation, and there are zero validated sleeves. High-complexity premature optimization for a 'small fast bot'; revisit after 2-3 instrument modules are live and proven.
- **Portfolio-level backtester (cross-strategy capital allocation) now** — The risk doctrine IS portfolio-level, but with 0 strategies past the 3-week forward gate there is no live portfolio to allocate. Replicating UTA collateral coefficients/portfolio-margin offline is XL and error-prone (mis-modeled coeffs hide liquidation risk). Revisit only after >=2 strategies pass the forward gate.
- **Event-driven backtester with L2 order-book & tick replay** — Maximal cost (L2 archive ingestion, book reconstruction, queue model, huge storage) against zero current demand — only useful for microstructure strategies the firm has never built or proposed. A textbook over-build violating cost-lean; gate strictly behind a forward-validated microstructure strategy that does not exist.
- **Options pricing + greeks engine for an illiquid venue (now)** — Bybit options books are thin beyond near-ATM BTC/ETH; a sparse/stale surface means backtested fills are wildly optimistic, so any 'edge' is a liquidity mirage (garbage surface in = garbage greeks out). The firm hasn't shipped a single linear-perp strategy live — premature scope-expansion. Defer until the core perp/spot product is profitable, and only ever as signal-only first.
- **On-chain data module & general news/sentiment NLP feed** — Doctrine-hostile on two fronts: off-venue PAID data that fights cost-lean, and (for NLP) non-deterministic LLM/ML in the ops loop. Both are slow, regime-dependent, macro-scale <30-trade-noise, and the highest backtest-overfit risk of all lanes (headline timestamps lie). Defer indefinitely; if anything carve out only the structured Bybit-announcement/listing flag as a tiny deterministic add.
- **Cross-quote / triangular spot arbitrage & liquidation-cascade sniper** — On-venue dislocations are tiny, transient, fee-sensitive and contested by faster co-located bots — fills are adverse-selected leaving hanging legs, and both rely on the classic 'all legs fill at top-of-book instantly' backtest trap. The cascade sniper is catching a falling knife with a small survivorship-biased sample on a throttled feed. Generic arb bloat for this latency profile.
- **Auto parameter-search / WFO optimizer & dynamic cross-strategy reallocator (build now)** — The canonical overfitting + cost-runaway pair: re-optimizing and performance-chasing on rolling windows manufactures overfit winners and buys tops/sells bottoms, with rebalance churn hitting two documented lessons. The stack lacks a programmatic purged/embargoed CV harness. Both must be gated hard behind the Overfitting Sentinel + budget governor and behind a real 5+ strategy live roster — neither exists yet.
- **Post-validation calibration loop & capability/coverage-gap mandate (now)** — Premature and bias-inducing: the calibration loop needs a stream of RESOLVED forward/live outcomes that doesn't exist (registry empty, 0 live), so small-sample feedback just chases noise. The coverage map invites filling empty cells for their own sake when an empty cell usually means 'no edge there' (e.g. low-vol grids) — it must never override the Sentinel. Keep coverage as a one-input hint only; defer calibration until a track record exists.
