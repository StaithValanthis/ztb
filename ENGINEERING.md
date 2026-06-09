# ENGINEERING.md — ztb Engineering Standards

Engineering standards for `ztb` — Zero Alpha's single, reusable, deterministic Python trading engine for Bybit. Derived from `docs/playbook/01-MASTER-PLAN.md`. These standards are binding on every PR, every milestone, every agent.

**Deployment target:** Ubuntu Linux `~/zero-alpha` (the canonical deployment root). The master plan's Windows build-host path is a drafting-context artifact and does not apply here.
**Model:** the firm's agents run on `deepseek-v4-flash` (thinking on/off); `deepseek-chat`/`deepseek-reasoner` are deprecating aliases — repoint before 2026-07-24.

---

## 1. Branches

All work happens on a topic branch off `main`; `main` is protected (require-PR + green-CI). Three prefixes:

- `feat/<x>` — new engine/module/feature work (e.g., `feat/m0-scaffold`, `feat/backtest`).
- `fix/<x>` — bug fixes and corrections.
- `strat/<x>` — strategy plugin authoring only (`strategies/<name>.py`; no engine edits) (e.g., `strat/sma_cross`).

Never commit directly to `main`. Never do member-to-member hand-offs of a branch; work flows UP to a Head, BACK to the MD.

### 1.1 Worktrees — keep `~/zero-alpha` on `main` (non-negotiable)
NEVER `git checkout -b` or `git checkout <branch>` inside the shared `~/zero-alpha`: that switches the ONE tree every agent reads its instructions and the ledger (`opportunities-registry.md`, `lessons-learned.md`) from, silently making them branch-stale (this has bitten the firm before). Build every topic branch in an ISOLATED git worktree instead:
```
git -C ~/zero-alpha worktree add ~/ztb-wt/<name> -b <feat|fix|strat>/<name>
cd ~/ztb-wt/<name>      # do ALL build / commit / push work HERE
```
`~/zero-alpha` stays pinned to `main`, so the MD, the ledger, and every agent's instructions are always the canonical `main` version. After the branch merges, remove it: `git -C ~/zero-alpha worktree remove ~/ztb-wt/<name>`. The Head of Engineering keeps `~/zero-alpha` on `main` and merges land there; `git worktree list` shows what is active.

## 2. Pull Requests & Commits

- Every change lands via a PR into `main`.
- **Conventional commits** are mandatory on every commit (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, etc.).
- The PR head commit is the unit the gate operates on — CI and V&R both bind to a single commit SHA.

## 3. THE TWO-KEY MERGE GATE (non-negotiable)

A merge to `main` requires **BOTH keys to hold on the SAME commit SHA**:

1. **CI-green** on the PR head commit.
2. A **recorded V&R PASS** on that **identical SHA**.

Rules:

- **A red CI never reaches V&R.** CI-green on the PR head is a *precondition* to validation review. A red build stays inside Engineering; the owning Head re-tasks the member. Validation is never asked to review a red commit.
- The V&R PASS must be recorded **against the same SHA** that CI went green on. Not "the branch," not "a later commit" — the identical commit.
- **Head of Engineering performs the merge, and only when both keys hold on the identical SHA.** No self-certification: Engineering does not approve its own validation; V&R is independent of Engineering.
- Branch protection on `main` enforces require-PR + green-CI mechanically; the two-key discipline enforces the rest.

Merge order, every module: `feat/<x>` → CI green on head (precondition) → V&R PASS on the same SHA → Head-of-Eng merge + tag → MD routes next.

## 4. CI Matrix

CI runs on every push to a PR. **Python 3.11 and 3.13 matrix.** Each job runs all of:

- `ruff` — lint.
- `ruff-format` — formatting check.
- `mypy` — static types.
- `pytest --cov-fail-under=90` — full test suite, coverage floor 90%.
- **secret-scan** — no credential in the diff (from M0).
- **version-consistency** — `__version__` matches the SemVer tag / `importlib.metadata.version`.

The full pytest suite is CI-only; pre-commit runs a fast unit subset (plus ruff, mypy, secret-scan) so the local hook reproduces CI's gate cheaply.

## 5. Versioning & Releases (SemVer)

- **SemVer** tags, one per milestone. Each milestone ends in a tagged, CI-green, V&R-PASSED release on `main`.
- Canonical milestone → tag map (single source of truth):

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

- `__version__` lives single-sourced in `ztb/__init__.py` and flows dynamically into `pyproject`. Every milestone DoD bumps `__version__` + `CHANGELOG.md` to the tag above.
- A plan citing any other tag is stale and yields to this table.

## 6. Runtime Pinning & Rollback

- **`ztb run` executes a pinned, released tag — never bleeding `main`, never a branch.** Live and demo runtimes pin a specific SemVer tag.
- **Rollback = `git checkout <prev tag>`** + restart `ztb run` (or flip to demo to stop live risk instantly). Rehearsed in go-live prep.
- A bad release is patched on `main`, re-clears the two-key gate, then the host is pinned forward to the new tag.

## 7. Secrets & Supply-Chain (from M0)

- **Secrets are env-only and confined to `execution/`**, gitignored. Demo/live keys are never read outside `execution/` and never before M7 arming.
- **`.gitignore` is secret-first** and committed before anything else in M0.
- **Pre-commit secret-scan + CI secret-scan from M0.** `git log -p` shows no credential, ever.
- Secrets never appear in repr/serialization, logs, scorecard, Discord payload, or dashboard frame (no-secret-in-output tests assert this).
- **Lockfile** (reproducible runtime + dev closure) is in M0's DoD; `pip install -e .[dev]` is verified against it.
- A **$0 systemd-timer CVE / dependency-drift check** runs continuously and **creates a task on a finding** (no agent daemon — a `Type=oneshot` timer ticks and exits).

## 8. Schema Discipline (additive, never destructive)

The SQLite result store (M3) is **stable + additively-versioned**, never "frozen":

- Ships with a `schema_meta(schema_version)` table.
- All tables use `CREATE TABLE IF NOT EXISTS`; later milestones (M4/M5/M6) add tables/columns via **guarded additive migrations** — never destructive rewrites.
- Metric access is via a **named function accessor** — `get_oos_metric(run_id, name)` / `get_oos_sharpe(run_id)` — frozen as a function, **not** a column name, so forward-test decay and leaderboards agree across milestones.

## 9. Idempotency Keys (restart-safe)

Execution-order idempotency keys (`orderLinkId`, dedupe ledger) derive from the **stable tuple `(strategy, symbol, bar_ts, intent_hash)`** — **NEVER the ephemeral `run_id`**. A restart, rollback, or re-issue must produce the identical key, or crash-recovery double-fills. M6's restart/replay tests assert this.

## 10. Honesty & Done-ness

- **No fabricated numbers.** The engine returns real numbers or marks results `credible=False` with a reason; it never invents metrics. Every Board-facing number is reproducible via `ztb report` from the store — if it can't be regenerated, it doesn't exist.
- **Verify the artifact exists before declaring done.** A milestone is done only when the tag exists with CI-green + a recorded V&R PASS on its SHA; a deliverable is done only when its file/test/transcript is confirmed present. "Tag `vX.Y.Z` with CI-green + recorded V&R PASS IS done."

---

*Standards source: `docs/playbook/01-MASTER-PLAN.md` (§0.2 versioning, §0.4 merge gate, §0.5 secrets/supply-chain, §0.6 schema, §0.7 idempotency, §3.3 git gates). Reconciliations per `docs/playbook/00-README.md`: deployment root `~/zero-alpha`; model `deepseek-v4-flash`.*
