# ztb/vr-pass Commit Status Bridge

The `ztb/vr-pass` commit status is the mechanical gate that prevents CI-red
releases. It is the Stage 2 gate defined by the Board audit
([ZTB-496](/ZTB/issues/ZTB-496), [ZTB-513](/ZTB/issues/ZTB-513)).

## How It Works

1. **V&R records a verdict** on a commit SHA (PASS or FAIL).
2. **The bridge is called** with `--sha <sha> --outcome PASS|FAIL`.
3. **The bridge checks GitHub commit statuses** on that SHA for CI conclusion.
4. **The bridge posts `ztb/vr-pass`** with one of:
   - `success` — V&R PASS + CI green (mechanical gate passed)
   - `failure` — V&R FAIL, or V&R PASS voided because CI has failures
   - `pending` — V&R PASS but no CI checks found yet

## Void-on-FAIL Rule

A V&R PASS **does not result in a green check** unless ALL CI checks on the
same SHA also passed. If any CI check on that SHA has conclusion
`failure`, `cancelled`, or `timed_out`, the bridge posts
`ztb/vr-pass = failure` instead, with a description that the PASS was
voided by CI failure.

This prevents the exact scenario that shipped v0.7.2 (CI-red on
ruff-format). V&R PASS on a CI-failing SHA is invalid per the two-key gate
principle: **merge = CI-green AND V&R PASS on identical SHA.**

## Script Usage

```bash
# CI notify mode (sets pending — no PASS without human V&R)
python3 scripts/ztb-vr-pass-bridge.py --sha <commit-sha> --mode notify

# Typical V&R PASS (with CI verification)
python3 scripts/ztb-vr-pass-bridge.py --sha <commit-sha> --outcome PASS

# V&R FAIL
python3 scripts/ztb-vr-pass-bridge.py --sha <commit-sha> --outcome FAIL

# Explicit owner/repo (auto-detected from git remote by default)
python3 scripts/ztb-vr-pass-bridge.py \
  --sha <commit-sha> --outcome PASS \
  --owner zero-alpha --repo ztb
```

## CI Integration

The bridge runs automatically on push to `main` as the final CI step
(`Notify V&R pending via bridge`), using `--mode notify`. This posts
`ztb/vr-pass = pending` to indicate that the SHA has passed CI but has
not yet received a human V&R verdict. The gate remains unlatched — the
branch protection rule still requires `ztb/vr-pass = success` before
any PR can merge, so no commit reaches `main` without explicit human
V&R approval.

V&R (or an agent acting on V&R's behalf) then manually posts the
verdict:

```bash
# After human V&R review confirms PASS
python3 scripts/ztb-vr-pass-bridge.py --sha <commit-sha> --outcome PASS

# After human V&R review confirms FAIL
python3 scripts/ztb-vr-pass-bridge.py --sha <commit-sha> --outcome FAIL
```

For V&R workflows (manual PASS on a PR SHA), an operator or V&R agent
runs the bridge explicitly after recording the PASS verdict and confirming
CI is green.

## Branch Protection

The `main` branch requires both:
- `ztb/vr-pass` — green check from this bridge
- `CI / test (3.11)` and `CI / test (3.13)` — the existing CI matrix

This ensures a PR cannot merge without both CI green AND a valid V&R PASS.

## Dependency

Requires `gh` (GitHub CLI) authenticated with `repo` scope. In CI this is
provided by `${{ github.token }}`. Locally, run `gh auth login`.
