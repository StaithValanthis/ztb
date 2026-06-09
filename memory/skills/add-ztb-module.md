# Add / improve a ztb engine module
- **Type:** process · **When to use:** building/changing core engine code (data, backtest, risk, execution, reporting).

## Steps
1. HoE **freezes the contract + acceptance tests BEFORE code**; delegates to the Platform Engineer.
2. Platform Eng: `git -C ~/zero-alpha worktree add ~/ztb-wt/<name> -b feat/<name>`; build in the worktree. pytest ≥90%, ruff+mypy clean, conventional commits. Keep `~/zero-alpha` on `main`.
3. Push; CI green on the PR-head SHA (red CI never advances).
4. HoE → MD → V&R gate on the same SHA → on PASS, cut the release (cut-a-release).

- **Last-verified:** 2026-06-09 — **Source:** docs/playbook (Relay 1); ENGINEERING.md §1.1.
