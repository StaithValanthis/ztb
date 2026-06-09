# Add a strategy plugin
- **Type:** process
- **When to use:** turning a Head-of-Research SPEC into a strategy plugin.

## Steps
1. Receive the **SPEC from the Head of Research** (signal logic, params, symbols/TF, pre-registered pass criteria). Never invent an edge.
2. Strategy Engineer: `git -C ~/zero-alpha worktree add ~/ztb-wt/<name> -b strat/<name>`; implement ONE `ztb/strategies/<name>.py` against the `Strategy` ABC (`generate_signals(df)->Series` in [-1,1], warmup-flat, no-NaN; engine owns the 1-bar shift). **No engine edits.**
3. Run `ztb backtest <name>` (cost-aware, IS/OOS) — never a bespoke cost-blind script. Report **net** metrics.
4. Hand UP to HoE → MD → the V&R gate (see run-validation-gate).
5. On **PASS**: merge + tag; the MD routes a **risk-active forward-test**. On **FAIL**: decline + append a lesson to lessons-learned.md.

## BOUNDARY (critical)
The plugin file is the artifact; the **edge is NOT a skill**. An edge counts only after the full evidence gate (cost-aware backtest → OOS → ≥3-week risk-active forward-test). **Never record a market edge in memory/skills** — that would auto-overfit to noise.

- **Last-verified:** 2026-06-09
- **Source:** docs/playbook (Relay 2 — ship-a-strategy).
