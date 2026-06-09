# ztb — Go-Live Checklist (the Board's gate before ANY live money)

**Source:** `docs/playbook/01-MASTER-PLAN.md §5.3` (the go-live checklist), gated by `§5.1` doctrine
preconditions and `§5.2` forward-test exit criteria.

**Who signs:** Head of Validation & Risk (V&R) signs this packet. V&R is independent of
Engineering; her PASS is the gate. **Any single FAIL halts go-live.** No partial passes, no
overrides, no "we'll fix it after arming."

**Prime directive:** survival first. A strategy *earns* capital; it is never granted it. Every
Board-facing number must be reproducible via `ztb report` from the store — if it can't be
regenerated, it does not exist (no fabrication).

**Deployment context (reconciled):** host is Ubuntu Linux at `~/zero-alpha`; private GitHub remote
`zero-alpha/ztb`. Agent models run on `deepseek-v4-flash`. (These supersede the `01-MASTER-PLAN`
Windows build-host path and the `[reasoner]/[chat]` label shorthand — see `00-README` reconciliations.)

---

## Preconditions (must already be true before this checklist is even opened)

- Live runs a **pinned released tag** (`v1.0.0`+), never `main` and never a branch.
- M5 (risk) + M6 (demo execution) + M7 (live-ready) are all tagged and **V&R-PASSED**.
- The merge gate already passed for each: **CI-green on the PR head AND a recorded V&R PASS on the
  identical SHA** (two-key merge).
- The system is **demo until the human Board arms it**. No agent ever flips the live flag.
- The risk-active forward-test (`§5.2`) has met its exit criteria: **≥21 continuous days, no
  unexplained gaps, live-vs-backtest in band and still holding at presentation, cost model
  reconciled, kill-switch + risk limits demonstrably fired correctly in a drill, no anti-pattern.**

---

## The gates (V&R signs each; any FAIL halts)

| # | Gate | Pass condition | Evidence | Status |
|---|---|---|---|---|
| 1 | **QA-passed, credible, cost-aware** | V&R PASS recorded; commission **and** slippage modeled; IS/OOS split honored; all metrics are **net** (cost-aware), and the sample is credible (`credible=True`, not flat / not below `min_bars`/`min_trades`) | `ztb backtest` output + scorecard + V&R review | ☐ PASS ☐ FAIL |
| 2 | **Risk-cleared & sized** | Sizing keeps **portfolio DD ≤ 25%**; heat and correlation within configured caps; Bybit venue limits (tick/step/min-notional/leverage) checked; the **25% account kill-switch is wired** and confirmed in the run path | risk config + V&R risk review | ☐ PASS ☐ FAIL |
| 3 | **Risk-active forward-test holding** | **≥ 3 continuous weeks** of paper-on-live via `ztb forwardtest` with the **M5 risk module + kill-switch ACTIVE**; live-vs-backtest **in band**; **still holding now** (at presentation, not just historically); decay **green** (forward net Sharpe ≥ 0.7× OOS Sharpe, same sign on every core metric) | `ztb forwardtest` + result store | ☐ PASS ☐ FAIL |
| 4 | **Not a known anti-pattern** | Not overfit (param-sensitivity checked); no survivorship bias; no look-ahead; not curve-fit to a single regime; no martingale / averaging-into-a-loss | V&R review + lessons-ledger cross-check | ☐ PASS ☐ FAIL |
| 5 | **Bybit key hardened** | API key is **IP-restricted to this host**; **withdrawals DISABLED**; **trade-only scope** (no transfer/withdraw permissions); secrets live in **`execution/` only**, env-only, gitignored — never elsewhere in the repo, logs, scorecard, Discord payload, or dashboard frame | Ops key audit | ☐ PASS ☐ FAIL |
| 6 | **Kill-switch tested** | Fired correctly in a **recent demo drill**; a trip **flattens all positions + halts** `ztb run` | drill log in the store | ☐ PASS ☐ FAIL |
| 7 | **Tiny first size** | First-live size = the **floor size**, smallest meaningful size above venue minimum, **fixed by policy, not by conviction** | risk config | ☐ PASS ☐ FAIL |
| 8 | **Rollback rehearsed** | Prior good tag identified; **`git checkout <prev tag>` + flip-to-demo** rehearsed (returns to known-good cleanly; runbook matches reality) | Ops runbook (`docs/runbooks/incident-rollback.md`) | ☐ PASS ☐ FAIL |
| 9 | **Dashboard not reachable off-host** | Live page is **localhost-only** (`127.0.0.1:8501`); **no off-host route**; **no trade or arm control** on the page | Ops verification | ☐ PASS ☐ FAIL |

---

## Packet that accompanies this checklist

The go-live packet handed to the Board also carries:

- The **released tag + version** being armed (a single pinned tag).
- The **CHANGELOG** for that tag.
- The **full trade ledger** from the forward-test — the complete ledger, **not a summary**.
- The **regime caveat** (what market regime the evidence was gathered in, and where it may not generalize).

---

## Arming — human Board only

**Arming is a separate, explicit, human-Board-only act**, performed *after* every gate above reads
PASS. No agent and no automatic path may arm live money:

- Arming is **per-strategy, per-size, against a single pinned tag**, and is **logged**.
- The live path is **disarmed by default** (`live_guard.py`); it refuses to arm unless preflight is
  all-PASS and reads the Board's signed arm token (`ZTB_LIVE_ARMED` + `live_arm.json`).
- **First-live is tiny by policy** (gate 7); portfolio DD ≤ 25% and the account kill-switch apply
  from the first dollar.
- **Implicit disarm-on-doubt:** the MD or the Board may revoke arming at any time. Default incident
  bias is **disarm first, investigate second**.

**If any gate is FAIL, go-live halts here. The machine stays in demo.**
