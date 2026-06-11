# Incident Rollback Runbook

## When to Roll Back

- Killswitch tripped unexpectedly.
- Reconcile drift exceeds threshold.
- Data staleness error persists.
- Unexplained P&L divergence from expected.
- Board or V&R orders a halt.

## Immediate Actions

```bash
# 1. Killswitch already tripped — verify
ztb report --exec-run-id <id>

# 2. Manual trip if needed
export ZTB_LIVE_ARMED=0
ztb rollback v0.7.0
```

## Rollback Procedure

1. **Identify safe tag** — previous known-good version:
   ```bash
   git tag --list 'v*' --sort=-version:refname
   ```
2. **Dry-run the rollback**:
   ```bash
   ztb rollback v0.7.0 --dry-run
   ```
3. **Execute rollback**:
   ```bash
   ztb rollback v0.7.0
   ```
4. **Verify**:
   ```bash
   git describe --tags --exact-match
   ```
5. **Restart** with the previous version.

## Post-Incident

1. Collect killswitch triggers from store.
2. Run reconciliation report.
3. File incident report for Head of Engineering.
4. Board reviews before re-arming live.
