# Add a strategy plugin
- **Type:** process · **When to use:** turning a Head-of-Research SPEC into a strategy plugin.

## Steps
1. Receive the **SPEC from the Head of Research** (signal, params, symbols/TF, pre-registered pass criteria). Never invent an edge.
2. Strategy Engineer: `git -C ~/zero-alpha worktree add ~/ztb-wt/<name> -b strat/<name>`; implement ONE `ztb/strategies/<name>.py` vs the `Strategy` ABC (`generate_signals(df)->Series` in [-1,1], warmup-flat, no-NaN; engine owns the shift). No engine edits.
3. `ztb backtest <name>` (cost-aware, IS/OOS) — never a bespoke script. Report **net** metrics.
4. Hand UP to HoE → MD → V&R gate (run-validation-gate). PASS → merge + tag + risk-active forward-test. FAIL → decline + lesson.

## BOUNDARY (critical)
The plugin file is the artifact; the **edge is NOT a skill** — it counts only after the full evidence gate (backtest → OOS → ≥3-week risk-active forward-test). Never record a market edge in memory/skills.

- **Last-verified:** 2026-06-09 — **Source:** docs/playbook (Relay 2).
