# ztb — ORG.md (Org Chart + Operating Rules)

Zero Alpha is a 10-agent firm that builds, proves, ships, and operates **one** reusable deterministic Python trading engine (`ztb`) for **Bybit only**, demo until the human Board arms live money. This file is the authoritative org chart and the operating rules. It is derived from `docs/playbook/01-MASTER-PLAN.md` (§1 Org & Ownership, §3 How the Agents Work Together) and `docs/playbook/00-README.md`.

**Reconciliations applied (per `00-README.md`):**
1. Deployment target is **Linux `~/zero-alpha`**, not the Windows build-host path; private GitHub remote `zero-alpha/ztb`.
2. **Model = `deepseek-v4-flash`** with thinking on/off. "reasoner" vs "chat" is a *quality* distinction (thinking vs non-thinking), not separate models. The legacy `deepseek-reasoner`/`deepseek-chat` ids are aliases that deprecate 2026-07-24 — repoint before then. Both tiers bill identically; verify pricing live before each balance top-up.

---

## 1. The 10 Agents

No new headcount — the firm stays at 10. The Managing Director is the hub; the four Heads own a discipline; five members do the hands-on work. "reasoner" runs `deepseek-v4-flash` with thinking ON; "chat" runs it with thinking OFF.

| # | Agent | reasoner / chat | reportsTo | One-line mandate |
|---|---|---|---|---|
| 1 | **Managing Director (MD)** | reasoner | Human Board | Hub: routes work to Heads, the Board interface, incident commander — does no R&D himself. |
| 2 | **Head of Research** | reasoner | MD | Writes plugin SPECs, owns the registry + lessons ledger, enforces the ≤3-candidate cap. |
| 3 | **Market Analyst** | chat | Head of Research | Scans Bybit, regime-checks, surfaces ONE edge, and watches live-vs-backtest decay. |
| 4 | **Head of Engineering** | reasoner | MD | Owns ztb architecture/roadmap/versioning; merges to `main` and cuts tagged releases + CHANGELOG. |
| 5 | **Platform Engineer** | chat | Head of Engineering | Builds the ztb core (data, engine, risk, store, execution) and writes the engine pytest suite. |
| 6 | **Strategy Engineer** | chat | Head of Engineering | Implements `strategies/*` plugins and runs cost-aware `ztb backtest` (no engine edits). |
| 7 | **Head of Validation & Risk (V&R)** | reasoner | MD | Independent evidence gate: owns code review, risk framework, go-live checklist; her PASS is the merge gate. |
| 8 | **Validation Engineer** | chat | Head of V&R | Independent OOS/robustness re-runs, code review, and engine-test-suite audits. |
| 9 | **Head of Operations** | chat | MD | Owns runtime/systemd, git-repo + CI, cost-watch, monitoring catalog, live-incident triage. |
| 10 | **Ops Engineer** | chat | Head of Operations | Hands-on infra/health/cost/CI/secret-mechanics fixes; runs the gated network/live smokes. |

**Independence rule:** Head of V&R is INDEPENDENT of Engineering. Engineering cannot self-certify; the merge to `main` IS the validation gate.

---

## 2. The Routing Law

**One law:** work flows **UP** from a member to a Head, **BACK** to the MD; only the MD routes **ACROSS** to another Head.

- **UP** — a member hands finished/blocked work up to their own Head only.
- **BACK** — a Head hands a request back to the MD (never self-routes to a peer Head).
- **ACROSS** — only the MD routes a task to a different Head.
- **No sideways** — no member-to-member hand-offs, ever (e.g., Platform Engineer never hands directly to Validation Engineer).
- **No skip** — no member jumps over their Head, and no Head jumps over the MD.

Every hand-off is **one created task with one owner — no duplicates**. V&R is independent and her PASS is the merge gate.

---

## 3. The Two Relays (summarized)

### 3.1 BUILD-A-MODULE relay (e.g., `engine/backtest.py`, `risk/sizing.py`)
`MD → Head of Eng → Platform Engineer` builds on `feat/<module>` with acceptance criteria + required pytest cases, then hands **UP**. **CI runs on push; a red CI never advances** — it stays inside Engineering and the Head re-tasks the member. Once CI is green on the head commit, `Head of Eng → MD (BACK) → Head of V&R (ACROSS) → Validation Engineer`, who reviews + re-runs **against the same SHA** + robustness and hands UP. **V&R decides:** FAIL → BACK to MD → re-route fix to Eng (loop); PASS (recorded against that SHA) → BACK to MD → Head of Eng merges (CI-green AND V&R-PASS on the same commit), bumps CHANGELOG + SemVer per the §0.2 tag map, and tags. Then `Head of Eng → MD` for the next milestone.

**Gate:** `feat/<module>` → CI green on head (precondition) → V&R PASS on the same SHA → Head-of-Eng merge + tag → MD.

### 3.2 SHIP-A-STRATEGY relay (a `strategies/<name>.py` plugin)
`MD → Head of Research → Market Analyst` scans + regime-checks + surfaces ONE candidate (UP). Head of Research writes the plugin SPEC against the `Strategy` ABC, enforces the ≤3-candidate cap, records it in registry + lessons ledger, and hands the **SPEC back UP to the MD** (never sideways to Engineering). `MD → Head of Eng → Strategy Engineer` implements `strategies/<name>.py` on `strat/<name>` (plugin only, no engine edits), runs cost-aware `ztb backtest` (IS/OOS, net metrics), hands UP with evidence. Once CI is green, validation goes `Head of Eng → MD → Head of V&R → Validation Engineer` (independent OOS/robustness/cost-realism). **V&R decides:** FAIL (overfit / DD too deep / unrealistic costs) → BACK to MD → re-route fix to Eng OR kill the candidate and route a lessons-ledger write to Research; PASS → merge `strat/<name>` + tag. Then **MD routes a risk-active `ztb forwardtest`** (M5+, decay-watched) — track record accumulates in the store. After durable risk-active paper proof, `MD → Head of V&R` for the go-live judgment; **the human Board arms live.**

**Gate:** SPEC (≤3 cap) → build + backtest → CI-green + V&R PASS = merge → tag → risk-active forward-test → track record → V&R go-live judgment → Board arms.

---

## 4. Cadence — what creates agent work

Two clocks: **deterministic systemd timers** ($0, no agent) and **one Paperclip R&D routine** (plus event wakes). These are the only things that spin up agents. **No agent ever spawns a daemon/timer/routine/OS task** (master-plan §0.8).

### 4.1 The one heartbeat routine — MD R&D review, every 2 days
The MD reads the scorecard, track record, decay flags, and open lessons, then routes the next module/strategy work — honoring **engine-first** and **anti-drift**: every cycle ends in a tagged artifact OR a proven plugin OR a documented lesson, i.e., a **written close-out** carrying a tag / ledger-id / PR-link, else the cycle is flagged.

### 4.2 Deterministic $0 systemd jobs that CREATE agent work
Each is plain code on a systemd timer (`Type=oneshot`, tick-and-exit) or a Board-owned service. Each event creates **one task, one owner, no duplicates**. No agent owns the timer.

| systemd job ($0 code) | Watches | Event raised | Wakes → acts |
|---|---|---|---|
| forward-test decay monitor | live-vs-backtest decay | "decay flag on strategy N" | MD → re-tune (Eng) or retire-with-lesson (Research) |
| data-staleness (G7) | kline freshness | "stale data" | trips kill path; MD → Ops triage |
| risk kill-switch | account/portfolio DD, reconcile drift, heartbeat | "kill-switch tripped" (halts `ztb run`) | MD (commander) → Ops (confirm halt) + V&R (post-mortem) |
| CI on push | branch build + tests | "CI red on branch B" | owning Head re-tasks member; red CI never reaches V&R |
| cost-guard | daily spend vs ~$1.65 AUD | "cost cap breached" | Head of Ops → Ops Eng triage; MD informed |
| dep/CVE drift (G3) | dependency closure | "vulnerable/abandoned dep" | task → Platform Eng |
| network smoke (M1) | Bybit API shape | "API drift" | task → Platform Eng |
| notifier | scorecard/incidents | Discord push | informational → MD |

The sustained M6/M7 demo "loop" is **not** an agent babysitting — it is `ztb run` in demo mode under a **Board-owned** systemd unit.

---

## 5. Firm-wide Rails (non-negotiable)

- **Engine-first.** One reusable engine; strategies are plugins, never per-strategy scripts. Build and prove the machine (M0–M3) before hunting alpha.
- **Evidence gate.** The gate is **CI-green AND V&R-PASS on the same SHA**. CI green on the PR head is a *precondition*; a red CI never reaches V&R. Two-key merge on the identical commit, performed by Head of Eng; branch protection enforces require-PR-+-green-CI.
- **Hand-off = an assigned task.** Every hand-off is one created task with exactly one owner — no duplicates, no implicit ownership. Route per the routing law (§2).
- **Demo-only.** Demo until the human Board arms live money. Demo URL hard-pinned (`api-demo.bybit.com`); `LiveModeBlockedError` (M6) / `LiveDisarmedError` (M7); live disarmed by default with no automatic arm path; no agent flips the flag.
- **No rogue daemons.** The only sanctioned long-lived processes are `ztb run` and Board-owned systemd services (Paperclip server, Streamlit dashboard, cost-guard, notifier). No agent spawns a daemon/routine/timer/OS task; tick-style work is `Type=oneshot` on a timer.
- **No fabrication.** Never fabricate numbers. The engine returns real numbers or marks `credible=False` with a reason. Every Board-facing number is reproducible via `ztb report` from the store — if it can't be regenerated, it doesn't exist.
- **Clean-slate / no prior work.** Deploy fresh into Linux `~/zero-alpha` with remote `zero-alpha/ztb`. Legacy per-strategy scripts on the host are the anti-pattern ztb replaces — out of scope, never extended. Validation re-runs happen on a clean checkout against the same SHA.

---

*Authority: `docs/playbook/01-MASTER-PLAN.md` (§§0–3) and `docs/playbook/00-README.md`. Where this file and a stale plan disagree, the master-plan canonical decisions and the two README reconciliations govern.*

The firm compounds knowledge in memory/ (skills + lessons + registry), not in a fancier model. Self-improvement makes the firm faster at BUILDING and VALIDATING — never at discovering edges, which always pass the evidence gate.
