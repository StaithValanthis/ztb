# Cut a release
- **Type:** process · **When to use:** merging a validated branch + tagging (Head of Engineering only, on a recorded V&R PASS).

## Steps
1. Merge to `~/zero-alpha`'s `main` (CI-green AND V&R-PASS on the same SHA). 2. Bump `ztb/__init__.py __version__` (SemVer), update CHANGELOG with measured evidence. 3. `git tag vX.Y.Z`; `git -C ~/zero-alpha worktree remove ~/ztb-wt/<name>`. 4. `git push origin main --tags`; close the PR; verify origin==local + tag on remote. **Never force-push main.** 5. `ztb run` pins a released tag; rollback = `git checkout <prev tag>`.

- **Last-verified:** 2026-06-09 — **Source:** docs/playbook (CD-0.2; release discipline).
