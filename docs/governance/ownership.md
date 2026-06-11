# Path ownership & the mechanical V&R gate

Board-directed governance change (2026-06-11) turning two prose rules — "engine edits = Platform
Engineer only" and "the V&R PASS is the merge key" — into mechanism. Staged so nothing blocks today.

## Path → owner map

| Path | Builds (author) | Reviews / co-signs |
|---|---|---|
| `ztb/engine/`, `ztb/execution/`, `ztb/data/`, `ztb/store/` | Platform Engineer | Head of Engineering |
| `ztb/risk/` (code) | Platform Engineer | Head of Engineering |
| `ztb/risk/` (threshold **numbers**) | — | **Head of V&R co-signs before code** |
| `ztb/strategies/` | Strategy Engineer | Head of Engineering |
| `CHANGELOG.md`, version bumps, tags | Head of Engineering | — |
| `.github/`, CI, systemd | Head of Operations | — |

Each agent now commits under its own identity (`ZTB <Role>`), so authorship is auditable and the
advisory check below can enforce the map.

## Stage 1 (this PR) — advisory, non-blocking
`.github/workflows/governance-advisory.yml` runs on every PR and emits a `::warning::` when a commit
touching a protected path is authored by an identity that does not own it. It is `continue-on-error`
and NOT a required status — it surfaces violations without blocking, while the firm adapts.

## Stage 2 (follow-up) — make the V&R PASS a required GitHub status
The two-key gate's V&R PASS lives in Paperclip (an issue comment on a SHA), which GitHub CI cannot
read. To make it a *required* merge gate:
1. A local operator bridge (ops-owned) posts a commit status `ztb/vr-pass = success` to GitHub on the
   exact validated SHA at the moment V&R records a PASS (and `pending`/`failure` otherwise).
2. Branch protection on `main` adds `ztb/vr-pass` (and the existing CI) to required status checks.
3. Promote the ownership-authorship check from advisory to required once authorship is clean.

This closes the gap the 2026-06-11 audit found: v0.7.2 shipped CI-red and a V&R PASS was recorded one
minute after a FAIL on the same SHA — both impossible to merge once `ztb/vr-pass` + exact-SHA-green
are required.
