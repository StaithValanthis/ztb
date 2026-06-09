# Run the validation (two-key) gate
- **Type:** process · **When to use:** any module/strategy result, before it reaches `main`.

## Steps
1. Precondition: CI green on the PR-head SHA. 2. MD routes ACROSS to the Head of V&R (independent of Engineering). 3. HoVR delegates the independent re-run / review / test-audit / secret-leak-audit to the Validation Engineer (same SHA); HoVR makes the PASS/FAIL call. 4. AUTO-FAIL: cost-blind, thin-sample (<~30 trades), no-OOS, goalpost-moved, or a known anti-pattern. 5. Record the verdict against that SHA; hand back to the MD.

## KEY: merge = CI-green AND a recorded V&R PASS on the SAME commit SHA.
- **Last-verified:** 2026-06-09 — **Source:** docs/playbook (merge gate); ENGINEERING.md.
