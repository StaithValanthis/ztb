# Incident response
- **Type:** process · **When to use:** kill-switch fired, abnormal P&L, data-staleness, or a CI/cost/runtime alert.

## Steps (MD = incident commander)
1. **Contain:** Ops halts `ztb run` if needed; confirm flat vs exchange via reconcile. Default: disarm first, investigate second. 2. **Notify:** Discord; the alert is a work item. 3. **Diagnose:** root cause from ledger + reconcile log + logs; re-verify live state, never a cached belief. 4. **Decide+fix:** triage→Ops, judgment→V&R; rollback = `git checkout <prev tag>` or flip to demo. 5. **Postmortem:** lesson to lessons-learned.md.

- **Last-verified:** 2026-06-09 — **Source:** docs/playbook (incident/kill-switch/rollback).
