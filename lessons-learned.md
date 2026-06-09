# ztb — Lessons Ledger

The canonical anti-pattern record for `ztb`, Zero Alpha's deterministic Bybit trading engine on Linux `~/zero-alpha`. Owned by Head of Research; cross-checked by Head of V&R on the go-live checklist (gate #4) and in the 2-day MD R&D review.

> **This ledger starts fresh for the new ZTB firm.** It is **append-only** — entries are added, never deleted or rewritten. It is seeded below with the canonical anti-patterns only (no prior-firm content).

---

## How to use this ledger

- Every retired candidate, killed thesis, or hard-won negative result becomes a new entry (append-only; one entry per lesson).
- Before any strategy SPEC is written, Head of Research cross-checks the candidate against this list and the 3-candidate cap.
- A repeated class of failure becomes a new go-live checklist anti-pattern (gate #4).
- Every entry states the anti-pattern, **why** it has no durable edge, and the **bar a new candidate must clear** to escape it.

---

## Seeded canonical anti-patterns

### L1 — Bare RSI / oversold mean-reversion on alts
Buying alts purely because RSI is "oversold" (or any naked oversold trigger) is **not a durable edge**. Oversold on an alt is most often the start of a trend down, not a reversion signal; the apparent win-rate evaporates out-of-sample and on the fat left tail.
**Bar to clear:** a mean-reversion candidate must add a real conditioning edge (regime/structure/flow), not a bare oscillator threshold, and prove it survives OOS with a credible sample — not a backtest that pays you on the way to ruin.

### L2 — Funding / basis carry where gross yield < round-trip costs
Funding-rate and basis "carry" theses routinely look profitable on **gross** yield while the **round-trip cost** (commission + slippage on entry and exit, plus rolls) quietly exceeds it.
**Bar to clear:** the thesis must demonstrate a **NET-of-cost edge** — gross carry minus the full modeled round-trip cost is positive and durable. Gross yield is not evidence. If the edge only exists before costs, it does not exist.

### L3 — EMA-crossover trend on 4H (overfit / whipsaw)
Naive EMA-crossover trend strategies on the 4H timeframe **overfit and whipsaw**: the crossover fires constantly in chop, bleeding round-trip costs, and the in-sample parameters do not generalize.
**Bar to clear:** an **explicit regime filter** (trend-vs-chop gate, not a tuned lookback) **and** at least **~100 out-of-sample trades** — never a handful. A trend thesis proven on a few OOS trades is noise wearing a trend costume.

### L4 — Spot/perp basis arb when spreads are compressed
Spot/perp basis arbitrage is **regime-dead** in compressed-spread environments: the spread you backtested against no longer exists, so the modeled edge is a memory of a different regime.
**Bar to clear:** **first verify the current spread distribution** — the live/recent spread must average **≥ 50% of the entry threshold** before the thesis is even worth speccing. If today's spreads don't support the trigger, the strategy is shelved with a lesson, not deployed.

### L5 — Grid on low-vol pairs
Grid strategies on low-volatility pairs **lose to round-trip costs**: each grid fill pays commission + slippage, and on a quiet pair the intra-band swings don't cover the cost of churning in and out.
**Bar to clear:** only viable if **historic intra-band swings exceed the round-trip cost by > 2×**, **and** `trade_frequency × cost < expected_edge`. If the grid trades more than the edge can pay for, it is a cost pump, not a strategy.

---

## META — the laws behind the list

- **< ~30 trades = noise.** A handful of trades is not a track record; it is an anecdote. Sample size gates credibility before any metric is believed (the engine's credibility guard enforces this — a thin sample returns `credible=False`, never a fabricated number).
- **Gross Sharpe lies — model the costs.** Any Sharpe (or return, or PF) computed without commission + slippage is a marketing number. Only **net-of-cost** metrics count as evidence. If the edge dies once costs are modeled, there was no edge.
- **In-sample brilliance ≠ edge.** A beautiful in-sample fit is the default outcome of searching, not proof of anything. **OOS and forward-test are the truth.** A strategy earns belief only by holding out-of-sample and continuing to hold in a risk-active forward-test — never on its in-sample curve.

---

*Append new lessons below this line. Do not edit or delete existing entries.*
