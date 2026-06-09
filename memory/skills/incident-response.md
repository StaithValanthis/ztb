# Incident response
- **Type:** process
- **When to use:** kill-switch fired, abnormal P&L, data-staleness, or a CI/cost/runtime alert.

## Steps (the MD is incident commander)
1. **Contain:** Head of Ops halts `ztb run` if needed; confirm flat vs the exchange via reconcile. Default bias: **disarm first, investigate second**.
2. **Notify:** Discord; the alert becomes a tracked work item.
3. **Diagnose:** root cause from the ledger + reconcile log + logs. **Re-verify live state — never act on a cached belief.**
4. **Decide + fix:** route triage to Ops, judgment to V&R. Rollback = `git checkout <prev tag>`, or flip to demo to stop live risk instantly.
5. **Postmortem:** append a lesson to lessons-learned.md; a repeated class becomes a checklist anti-pattern.

- **Last-verified:** 2026-06-09
- **Source:** docs/playbook (go-live + proving loop; incident / kill-switch / rollback).
