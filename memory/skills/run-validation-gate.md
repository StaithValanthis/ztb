# Run the validation (two-key) gate
- **Type:** process
- **When to use:** any module or strategy result, before it reaches `main`.

## Steps
1. **Precondition:** CI green on the PR-head SHA. A red CI never reaches V&R.
2. MD routes **ACROSS** to the Head of Validation & Risk (independent of Engineering).
3. HoVR delegates the independent re-run / code review / test-suite audit / secret-leak audit to the **Validation Engineer** (against the **same SHA**); HoVR makes the PASS/FAIL call herself.
4. **AUTO-FAIL:** cost-blind, thin-sample (<~30 trades), no-OOS, goalpost-moved criteria, or any known anti-pattern (check lessons-learned.md).
5. Record the verdict against **that exact SHA**; hand back to the MD (PASS → merge-authorization; FAIL → decline + lesson).

## KEY
Merge = **CI-green AND a recorded V&R PASS on the SAME commit SHA**.

- **Last-verified:** 2026-06-09
- **Source:** docs/playbook (the merge gate); ENGINEERING.md.
