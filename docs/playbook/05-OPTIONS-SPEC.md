I'll spec this out directly — this is a design task, no codebase exploration needed since ztb's architecture is already well-defined in the context. Let me write a tight, honest spec.

# ztb Options-Support Module Set — Bybit USDC Options (BTC/ETH/SOL)

## 0. Honest framing (read first)

Options add **real edge in exactly one place**: harvesting the variance risk premium (selling IV that prints rich vs. subsequently-realized vol) under disciplined risk and assignment handling. Most other "edges" (vol-arb, dispersion, gamma scalping) are **execution-cost and liquidity traps** for a small bot on Bybit, where option books are thin and spreads are wide. The doctrine ("the cheapest agent is the one that doesn't run") applies double here: a mispriced spread looks like alpha until you cross it twice.

The module set below is built so the *pricing/data/risk layer* is reusable and trustworthy first, and only **one conservative income strategy** is allowed live after evidence-gating. Everything else is research-flagged.

Bybit specifics that shape the design: USDC-settled (not coin-settled) options on BTC/ETH/SOL, European exercise, cash settlement at expiry against Bybit's delivery/settlement price (a TWAP of the index over the final window), portfolio-margin or per-option margin, hourly funding does NOT apply (options aren't perps), and an active market-maker program meaning quoted IV exists but depth past the top of book is shallow.

---

## 1. DATA module — `ztb.options.data`

Extends the existing Bybit public-REST + cache layer; no new venue.

| Component | Source (Bybit v5 public) | Cached artifact |
|---|---|---|
| Instrument catalog | `/v5/market/instruments-info?category=option` | `options_instruments.parquet` — symbol, base, strike, expiry, type (C/P), tick, min qty, settle coin |
| Chain snapshot | `/v5/market/tickers?category=option&baseCoin=BTC` | `chain/{base}/{ts}.parquet` — bid/ask/mark, markIv, bidIv, askIv, underlyingPrice, delta/gamma/vega/theta (Bybit-supplied), OI, 24h vol |
| Orderbook (top-N) | `/v5/market/orderbook?category=option&symbol=...` | `book/{symbol}/{ts}.parquet` — for honest spread/depth modeling |
| Underlying index/mark | `/v5/market/tickers?category=linear` + index | reuse perp data layer |
| Delivery price | `/v5/market/delivery-price?category=option` | `delivery/{base}.parquet` — historical settlement |
| Risk-free / funding proxy | derive from USDC perp funding + term structure | `rates.parquet` |

Design notes:
- **Snapshot, not tick.** Store periodic chain snapshots (e.g. 1–5 min cadence for paper, hourly for research history). Bybit gives no deep historical option chain; **we must build our own history from forward snapshots** — this is the single biggest data constraint and the reason the phased plan front-loads a logging period before any backtest claims.
- Persist **Bybit's own greeks and markIv** alongside ours so we can validate our pricing engine against the venue (sanity check, not ground truth).
- Surface object: build an `IVSurface(base, ts)` indexed by (expiry, log-moneyness) with interpolation, so strategies query a clean surface, not raw rows.
- `expiries`: track daily/weekly/monthly/quarterly buckets; tag DTE and whether an expiry is "liquid" (OI + volume thresholds) — most far/odd strikes are untradeable and must be filtered early.

**Edge vs. complexity:** data layer is pure plumbing — necessary, low-risk, reusable. Do it well; it's the foundation everything else trusts.

---

## 2. PRICING + GREEKS engine — `ztb.options.pricing`

Deterministic, vectorized, no LLM. Pure functions over numpy arrays.

- **Model:** Black-76 on the **forward** (crypto has no clean dividend/carry; use forward F = S·e^{(r)·T} or, cleaner, the option-implied forward from put-call parity per expiry). Black-Scholes-Merton as the degenerate fallback. USDC settlement means premium and payoff are in USDC — no quanto adjustment needed (this is *why* USDC options are simpler than coin-margined Deribit-style contracts; lean into it).
- **Inputs:** F (forward), K, T (year-fraction to settlement, using Bybit's actual settlement timestamp), σ, r≈0 (USDC). 
- **IV solve:** Newton-Raphson on vega with a Brent/bisection fallback for deep ITM/OTM where vega→0; clamp to [1%, 1000%], flag non-convergence rather than returning garbage.
- **Greeks (closed-form, Black-76):** delta, gamma, vega, theta; second-order **vanna** and **vomma** as research-tier (needed for honest vega-risk under spot moves, but not for v1 sizing).
- **Validation harness:** reprice Bybit's markIv → assert our price within tick of mark; reprice our IV from their greeks. Continuous CI-style check against snapshots. Any drift > threshold halts strategy use (fail-closed).
- **Forward construction:** prefer put-call-parity-implied forward per expiry over a modeled carry — it absorbs Bybit's basis/funding regime automatically and avoids a rate assumption.

**Edge vs. complexity:** real and necessary, but **commoditized** — the engine is table stakes, not alpha. The only alpha-relevant subtlety is getting the **forward and T exactly right** (settlement-window TWAP, not spot-at-expiry), because mispricing T/F by hours near expiry dwarfs any model nicety.

---

## 3. OPTIONS-AWARE backtest + risk — `ztb.options.backtest`, `ztb.options.risk`

Plugs into the **one existing engine** as a position/instrument type — not a separate backtester. Adds an options accounting layer.

**Cost model (the part that actually decides viability):**
- **Spread cost = the dominant cost.** Fill at bid/ask from stored books, NOT at mark. Model the half-spread as the baseline cost and add slippage for size beyond top-of-book depth. On Bybit options, half-spreads of several % of premium on non-ATM/non-near strikes are normal — a strategy that's profitable at mark and dead at the touch is the default failure mode, so the engine assumes touch fills.
- Bybit option **taker/maker fees** (fee capped as a % of underlying index price, not of premium — model the actual cap), plus **delivery/settlement fee** at expiry.
- **No funding** on options (unlike perps) but funding DOES hit any perp/spot hedge legs — account for it on the hedge side.
- Liquidity gate: reject any backtest fill on a strike/expiry whose snapshot OI/volume/depth was below threshold. **No phantom fills on dead strikes.**

**Margin model:**
- Long options: premium paid, no further margin.
- Short options: Bybit's option margin formula (initial = premium + max(a%·index − OTM amount, b%·index)-style); implement the actual Bybit USDC-options margin spec, plus a **portfolio-margin** approximation when enabled (margin offset across the book by net greeks). Be conservative: if uncertain, over-margin.
- **Kill-switch integration:** the existing 25% account kill-switch and ≤25% portfolio-DD floor apply unchanged; short-vol books must be stress-tested against gap moves (see below) so a single overnight gap can't breach the floor.

**Greeks-based sizing & limits (`ztb.options.risk`):**
- Size positions by **risk contribution**, not notional: target a portfolio vega budget and per-trade vega cap.
- Hard limits enforced pre-trade and continuously: **net |delta|**, **net vega**, **net gamma**, and **max short-gamma near expiry** (gamma explodes into expiry — cap or force roll/close at a DTE threshold).
- **Scenario/stress grid** (not just linear greeks): reprice the whole book on a grid of spot shocks (±5/10/20/30%) × IV shocks (±5/10/20 vol pts) × time decay. The floor is checked against the **worst grid cell**, because greeks lie on big crypto gaps. This is the single most important risk control for short premium.

**Expiry / settlement / assignment:**
- European + cash-settled = **no early assignment, no physical delivery, no pin-the-stock surprises** — a genuine simplification vs. equity options. Settlement = cash P&L vs. Bybit delivery price.
- Engine must model the **settlement-window TWAP**, auto-close/settle at expiry, realize cash P&L, and handle **roll logic** (close near-DTE, open next expiry) as an explicit, costed action.
- "Covered call / cash-secured put" on Bybit = collateralized in USDC against a spot or perp leg; model the combined position and its margin offset, not the option in isolation.

**Edge vs. complexity:** the risk/cost layer is where the real value is, and it's **honest-cost modeling that creates the edge** (it's what stops you trading the 90% of strategies that only work at mark). High effort here, fully justified.

---

## 4. STRATEGY CLASSES unlocked — `ztb.strategies.options.*`

Each is a plugin into the existing strategy framework. Viability graded for a **small, cost-lean Bybit bot**.

| Strategy | What it harvests | Small-bot viability | Caveats |
|---|---|---|---|
| **Covered call / cash-secured put** | Variance risk premium, directional-ish | **A — the one to ship first.** Single short leg, defined collateral, cash-settled (no assignment drama), low operational complexity, tolerant of wide spreads if held to expiry / few rolls. | Caps upside / takes downside; sells cheap vol in low-IV regimes → gate on IV rank. Over-trading the roll eats the premium. |
| **Vertical spreads (credit/debit)** | Defined-risk directional or premium | **B.** Defined max loss is margin-friendly and floor-friendly. | **Two legs = two spreads crossed** → cost often kills the edge on thin strikes. Needs the credit to clearly exceed round-trip cost. |
| **Calendar / diagonal** | Term-structure of IV | **C.** Real when front IV >> back IV. | Multi-leg cost, and Bybit term liquidity is patchy; vega/theta interaction is subtle → easy to overfit. |
| **Delta-neutral premium selling (strangle/straddle, delta-hedged)** | Pure variance risk premium | **B-, research→ second strategy.** This is the "real edge" core: sell rich IV, hedge delta with perp. | Hedging cost + perp funding + gamma risk into expiry; gap risk is the killer — only viable with the stress-grid floor and small vega budget. |
| **Vol-arb vs. realized (sell IV when IV>RV forecast)** | VRP, timing overlay | **C.** It's the *signal* behind premium selling, not a separate strategy. | RV forecast is easy to overfit; <30 expiries of clean data = noise (doctrine). Treat as a gate, not a standalone book. |
| **Dispersion (index vs single-name)** | Correlation premium | **F — do not build.** Needs an index option + a basket; Bybit has only BTC/ETH/SOL, no clean index, 3 names ≠ dispersion. Pure complexity, no edge. |
| **Gamma scalping (long gamma, hedge spot)** | Realized > implied | **D.** Needs cheap, tight, continuous hedging. | Bybit spread + hedge costs almost always exceed scalped gamma for a small bot. Classic "works on paper at mark" trap. |

**Bottom line on classes:** ship **covered call / cash-secured put** first. The only credible *second* book is **delta-neutral premium selling** once data history and the stress-grid risk layer are proven. Treat vol-arb as a *gate/signal*, dispersion and gamma scalping as **don't-build** for this scope.

---

## 5. PHASED PLAN (evidence-gated, demo-until-Board-arms)

**Phase 0 — Data + pricing (no trading).** Ship `options.data` (catalog, chain/book snapshots, IV surface) and `options.pricing` (Black-76, IV solve, greeks). Stand up the **continuous snapshot logger** to build the proprietary option-chain history Bybit won't give us. Validate engine against Bybit markIv/greeks in CI. *Exit gate:* pricing matches venue within tolerance; ≥ several weeks of clean snapshot history accumulating.

**Phase 1 — Options-aware backtest + risk (paper math only).** Ship `options.backtest` (touch-fill cost model, margin, settlement/TWAP, liquidity gate) and `options.risk` (greeks limits, vega budget, stress grid). Backtest covered-call/CSP on the accumulated history with **honest touch fills**. *Exit gate:* strategy survives cost-real backtest **and** out-of-sample split; ≥30 trades; positive net of touch-spread + fees.

**Phase 2 — Forward paper test (demo).** Run covered-call/CSP live-paper on Bybit demo through the forward-test runner for **≥3 weeks** (doctrine minimum), logging modeled-vs-actual fills and slippage to validate the cost model in the wild. *Exit gate:* forward Sharpe > 1.5, DD < 15%, modeled cost ≈ realized cost (the cost model didn't lie).

**Phase 3 — ONE conservative income strategy, tagged release.** Promote **covered call / cash-secured put** to a validated tagged release; demo-live only; the human Board arms real money. Tight vega budget, IV-rank entry gate, minimal rolling. Reporting + dashboard get options panels (greeks exposure, vega budget usage, expiry ladder, stress-grid worst cell).

**Phase 4 — Expand, gated per strategy.** Only after Phase 3 prints stable edge: add **delta-neutral premium selling** (reusing the proven risk layer + perp hedge), each new class re-running the full Phase 1→3 gate. Vol-arb folded in as an entry gate. Dispersion/gamma-scalping stay shelved unless the thesis materially changes.

---

## 6. Where options genuinely add edge vs. add complexity

- **Real edge:** systematically **selling the crypto variance risk premium** (covered calls / CSP, later delta-neutral strangles) with honest touch-fill costs and a stress-grid floor. Crypto VRP is historically fat; cash-settled European options remove assignment risk; the edge is real *if and only if* costs are modeled at the touch and gamma/gap risk is capped.
- **Mostly complexity (cost/liquidity/overfit traps for a small Bybit bot):** gamma scalping, calendars, and any multi-leg structure where you cross 2–4 wide spreads; **dispersion is a non-starter** (no index, 3 names).
- **The discipline that makes it worth it:** the honest cost model and stress grid are what convert "options" from a complexity sink into an edge — they kill the 90% of book-pretty strategies before they trade, leaving only the variance-premium harvest that survives real Bybit frictions.

---

Spec files (to be created under the ztb tree when built):
- `ztb/options/data/` — `instruments.py`, `chain.py`, `book.py`, `surface.py`, `delivery.py`, `logger.py`
- `ztb/options/pricing/` — `black76.py`, `iv_solve.py`, `greeks.py`, `validate.py`
- `ztb/options/backtest/` — `cost_model.py`, `margin.py`, `settlement.py`, `roll.py`
- `ztb/options/risk/` — `greeks_limits.py`, `vega_budget.py`, `stress_grid.py`
- `ztb/strategies/options/` — `covered_call.py`, `cash_secured_put.py`, (later) `delta_neutral_premium.py`