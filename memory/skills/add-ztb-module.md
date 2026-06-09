# Add / improve a ztb engine module
- **Type:** process
- **When to use:** building or changing core engine code (data, backtest, risk, execution, reporting).

## Steps
1. Head of Engineering **freezes the module contract + acceptance tests BEFORE code**; delegates to the Platform Engineer.
2. Platform Engineer: `git -C ~/zero-alpha worktree add ~/ztb-wt/<name> -b feat/<name>`; build in the worktree. Full pytest ≥90%, ruff + mypy clean, conventional commits. **Keep `~/zero-alpha` on `main`** (ENGINEERING.md §1.1).
3. Push; CI must be **green on the PR-head SHA** (a red CI never advances — it stays inside Engineering).
4. Hand UP to HoE → MD → the V&R gate on the **same SHA** (see run-validation-gate).
5. On PASS: HoE cuts the release (see cut-a-release).

- **Last-verified:** 2026-06-09
- **Source:** docs/playbook (Relay 1 — build-a-module); ENGINEERING.md §1.1.
