# Release Process — Two-Key Merge Gate

## Overview

Every release of `ztb` lands via the **two-key merge gate**: a merge to `main` requires CI-green **AND** a recorded V&R PASS on the **identical PR head commit**. This is non-negotiable and encoded in `ENGINEERING.md` §3.

## The Two Keys

1. **CI-green** — the full CI matrix (ruff, ruff-format, mypy, pytest -m "not network" --cov-fail-under=90 --cov=ztb --cov-report=term-missing, secret-scan, version-consistency) passes on the PR head commit across Python 3.11 and 3.13 (`fail-fast: false`). On `main` pushes, a successful `test` job also triggers the `vr-pass` bridge which posts the V&R PASS record.
2. **V&R PASS** — the independent Validation & Risk team records a PASS against the **exact same SHA**.

Both keys must hold on the same commit. A red CI never reaches V&R; a PASS on a different SHA does not unlock the gate.

## Release Flow

```
feat/<x> branch ──→ Bump __version__ + CHANGELOG (IN the PR head)
                           │
                    CI green on PR head (precondition)
                           │
                    V&R PASS on same SHA
                           │
              Head of Engineering merges to main
                           │
                    Tag the merge commit (== validated SHA)
                           │
                    ──→ MD routes next milestone
```

### Step-by-step

1. **Build + version bump.** Platform Engineer (engine/tests/lockfile) or Strategy Engineer (plugin) builds on a topic branch in an isolated worktree (`~/ztb-wt/<name>`). `~/zero-alpha` stays on `main`. The version bump (`__version__`, `CHANGELOG.md`, SemVer consistency) is done **in the PR head**, before validation — never as a post-merge commit.

2. **CI.** Every push runs the full CI matrix. The PR head commit must go green on all checks. No review or validation happens on a red commit. The version already reflects the target tag at this point.

3. **Validation.** Once CI is green on the head commit, the Head of Engineering routes the request BACK to the MD, who routes ACROSS to the Head of V&R. V&R reviews the code and re-runs against the **same SHA** — which already carries the bumped version. V&R records PASS or FAIL on that commit. A FAIL sends the fix back through Engineering; a PASS unlocks the merge.

4. **Merge (two-key).** Head of Engineering performs the merge **only when**:
   - CI is green on the PR head commit, AND
   - V&R PASS is recorded against that **identical SHA**.
   
   Neither alone is sufficient. No self-certification: Engineering does not approve its own validation. The merge commit IS the validated SHA — no additional commits land between validation and tagging.

5. **Tag.** Tag the merge commit — which IS the V&R-validated SHA:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

   **No post-merge commits between validation and tagging.** The version bump and CHANGELOG update were already in the validated PR head. The tagged SHA must equal the V&R-validated SHA (see ZTB-512).

6. **Hand-off.** Create a task assigned to the MD: "Module X merged + tagged vX.Y.Z."

## CI Matrix

Every push runs on **Python 3.11 and 3.13** (matrix, not single-version):

| Check | Tool |
|---|---|
| Lint | `ruff check .` |
| Format | `ruff format --check .` |
| Types | `mypy --strict ztb/` |
| Tests + coverage | `pytest -m "not network" --cov-fail-under=90 --cov=ztb --cov-report=term-missing` |
| Secret scan | `python3 scripts/secret-scan.py $(git diff --name-only HEAD~1..HEAD 2>/dev/null \|\| find . -name '*.py' -o -name '*.toml' -o -name '*.yaml' -o -name '*.yml' -o -name '*.cfg' -o -name '*.ini' \| grep -v __pycache__ \| grep -v .git)` |
| Version consistency | `__version__` matches `importlib.metadata.version('ztb')` |
| V&R PASS bridge (separate `vr-pass` job, `main` push only) | `python3 scripts/ztb-vr-pass-bridge.py --sha ${{ github.sha }} --outcome PASS` on Python 3.11 |

CI configuration: `.github/workflows/ci.yml`

## Versioning

Canonical milestone → tag map (single source of truth, `ENGINEERING.md` §5):

| Milestone | Tag | Theme |
|---|---|---|
| M0 | `v0.1.0` | Scaffold + CI |
| M1 | `v0.2.0` | Data layer |
| M2 | `v0.3.0` | Backtest engine + plugin framework + metrics + indicators + reference strategy |
| M3 | `v0.4.0` | Reporting + result store + scorecard + Streamlit |
| M4 | `v0.5.0` | Forward-test runner |
| M5 | `v0.6.0` | Risk module |
| M6 | `v0.7.0` | Execution (DEMO) |
| M7 | `v1.0.0` | Live-ready (Board-armable, disarmed by default) |

`__version__` lives single-sourced in `ztb/__init__.py`.

## Changelog Requirements

Every CHANGELOG entry must include:
- **Measured evidence** — numbers reproducible via `ztb report` from the store. No fabricated numbers. "Unknown" beats a guess.
- Test count and pass rate.
- V&R PASS SHA reference and issue link.
- PR number.
- Merge commit SHA (the two-key merge).
- Tag.

## Rollback

- `ztb run` executes a pinned, released tag — never bleeding `main`.
- Rollback: `git checkout <prev-tag>` + restart `ztb run`.
- A bad release is patched on `main`, re-clears the two-key gate, then the host is pinned forward to the new tag.

See also: `docs/runbooks/incident-rollback.md`

## References

- `ENGINEERING.md` — full engineering standards (branches, worktrees, CI, versioning, schema, idempotency)
- `ORG.md` — org chart + routing law (§3.1 BUILD-A-MODULE relay)
- `.github/workflows/ci.yml` — CI workflow definition
- `CHANGELOG.md` — release history with two-key evidence per entry
