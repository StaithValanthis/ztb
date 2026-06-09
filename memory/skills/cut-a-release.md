# Cut a release
- **Type:** process
- **When to use:** merging a validated branch and tagging a milestone or strategy (Head of Engineering only).

## Steps (only on a recorded V&R PASS for the SHA)
1. Merge the branch into `~/zero-alpha`'s `main` (CI-green AND V&R-PASS on the same SHA). Keep `~/zero-alpha` on `main`.
2. Bump `ztb/__init__.py __version__` (SemVer per the milestone tag map), update `CHANGELOG.md` with **measured evidence** ("unknown" over a guess).
3. `git tag vX.Y.Z`; remove the merged worktree: `git -C ~/zero-alpha worktree remove ~/ztb-wt/<name>`.
4. Publish: `git push origin main --tags`; close the PR; verify `origin/main == local main` and the tag is on the remote.
5. `ztb run` pins a **released tag**, never `main`/a branch. Rollback = `git checkout <prev tag>`.

- **Last-verified:** 2026-06-09
- **Source:** docs/playbook (CD-0.2 tag map; release discipline).
