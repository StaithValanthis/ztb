# Post-Mortem: v0.7.2 Release — Tag SHA != Validated SHA

**Date:** 2026-06-11  
**Severity:** HIGH (gate integrity)  
**Filed under:** [ZTB-496](/ZTB/issues/ZTB-496) board audit  

## Summary

The `v0.7.2` git tag pointed to commit `c02ad5c` — a post-merge version-bump commit that was **never validated** by V&R. The V&R PASS was recorded against SHA `bad7a26`. The tagged SHA (`c02adc5`) failed `ruff-format --check`, violating the invariant that every released tag must be CI-green.

## Timeline

| Time (UTC) | Event |
|------------|-------|
| 2026-06-11 ~12:00 | PR #15 (`feat/fix-reconcile-equity`) merged to main (merge commit `d6ffef3`) |
| | V&R PASS recorded against SHA `bad7a26` (PR head) |
| | Post-merge version bump committed: `c02ad5c` (bump to v0.7.2, update CHANGELOG) |
| | Tag `v0.7.2` applied to `c02ad5c` — NOT the validated SHA |
| | CI run on `c02ad5c` fails: ruff-format check on `ztb/execution/executor.py` |
| 2026-06-11 ~18:00 | Board audit (Fable-5) discovers the mismatch |

## Root Cause

The release procedure had the version-bump step **after the merge**:

```
PR head (validated) → Merge → Post-merge version bump → Tag → ❌ tag SHA != validated SHA
```

The version bump (`__version__`, `CHANGELOG.md`) was a post-merge commit, so the tag necessarily pointed to a different SHA than the one V&R validated.

## Impact

- The `v0.7.2` tag shipped with a failing ruff-format check.
- A V&R FAIL existed on the same SHA as the V&R PASS (same SHA, different CI run), which should have voided the PASS.
- The CHANGELOG for v0.7.2 falsely claimed "ruff/mypy clean."

## Fix Applied

### Process fix (two-key merge gate)

The release procedure was rewritten ([ZTB-536](/ZTB/issues/ZTB-536), [ZTB-512](/ZTB/issues/ZTB-512)) to require the version bump IN the PR head **before validation**:

```
PR head (bumped + CHANGELOG + CI green) → V&R PASS on same SHA → Merge → Tag merge commit (== validated SHA)
```

The corrected flow is documented in `docs/release-process.md`.

### Void-on-FAIL rule

The `scripts/ztb-vr-pass-bridge.py` bridge script implements a void-on-FAIL rule [ZTB-527]: if ANY CI check on a commit is FAILURE, a V&R PASS on that same SHA is posted as "failure" instead of "success." This prevents CI-red tags from receiving a green commit status.

### Ruff-format fix

The unmet format issue on `ztb/execution/executor.py` was fixed in commit `78d9e1e` and verified via `ruff format --check .` (112 files already formatted).

### Skills updated

- `cut-a-release.md` — steps reordered: version+CHANGELOG in PR head before validation
- `run-validation-gate.md` — CI-check step added before PASS
- `vr-pass-bridge.md` — void-on-CI-FAIL rule documented

## Acceptance Criteria Verified

- [x] `ruff format --check .` passes on main
- [x] CHANGELOG documents the process change (v1.0.1 entry)
- [x] Any future tag will be CI-green AND V&R-PASSED on the EXACT same SHA (per `docs/release-process.md` and the bridge script)

## Lessons Learned

1. **Post-merge version bumps are forbidden.** The version and CHANGELOG must be in the PR head before V&R review.
2. **Two keys, one SHA.** CI-green alone or V&R PASS alone is insufficient. Both must hold on the identical commit.
3. **No self-certification.** Engineering does not approve its own validation.
4. **Re-verify live state.** Never act on a cached conclusion. Verify the tag SHA, CI status, and V&R PASS SHA from primary sources before any release action.
