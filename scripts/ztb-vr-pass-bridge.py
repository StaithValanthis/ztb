#!/usr/bin/env python3
"""
ztb-vr-pass-bridge.py — set GitHub commit status for V&R PASS/FAIL.

Usage:
    python3 scripts/ztb-vr-pass-bridge.py --sha <commit-sha> --outcome PASS|FAIL
    python3 scripts/ztb-vr-pass-bridge.py --sha <commit-sha> --mode notify

Reads owner/repo from the local git remote. Uses `gh` CLI for API auth.

--mode notify posts ztb/vr-pass = pending as a signal that V&R human review
has not yet occurred. This is the CI-on-push path. --outcome PASS|FAIL is
the explicit V&R verdict path (manual or agent-driven).

Void-on-FAIL rule (ZTB-496 / ZTB-527):
  - V&R PASS is only posted as "success" if ALL CI checks on the same SHA
    also succeeded. If any CI check is FAILURE, the bridge posts
    "ztb/vr-pass = failure" even though V&R said PASS — the CI FAIL voids
    the PASS.
  - V&R FAIL always posts "ztb/vr-pass = failure".
"""

import argparse
import json
import subprocess
import sys
from typing import NoReturn


def fail(msg: str) -> NoReturn:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def gh(args: list[str], input_data: str | None = None) -> dict:
    """Run `gh api` and return parsed JSON. Exits on error."""
    cmd = ["gh", "api"] + args
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            input=input_data,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        fail("gh API call timed out")
    except FileNotFoundError:
        fail("gh CLI not found — install GitHub CLI (gh)")
    if r.returncode != 0:
        msg = r.stderr.strip() or f"exit code {r.returncode}"
        fail(f"gh API call failed: {msg}")
    if not r.stdout.strip():
        return {}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        fail(f"gh returned non-JSON: {e}\n{r.stdout[:500]}")


def get_repo_owner_repo() -> tuple[str, str]:
    """Read owner/repo from 'git remote get-url origin'."""
    try:
        r = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode != 0:
            fail("not a git repo or no 'origin' remote")
        url = r.stdout.strip()
    except FileNotFoundError:
        fail("git not found")
    except subprocess.TimeoutExpired:
        fail("git remote query timed out")

    # Parse: https://github.com/owner/repo.git  or  git@github.com:owner/repo.git
    for prefix in ("https://github.com/", "git@github.com:"):
        if url.startswith(prefix):
            rest = url.removeprefix(prefix).removesuffix(".git")
            parts = rest.split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]
    fail(f"cannot parse owner/repo from remote URL: {url}")


def get_ci_conclusion(owner: str, repo: str, sha: str) -> str | None:
    """Check combined CI check-runs for the given SHA.

    Returns 'success', 'failure', 'neutral', 'cancelled', 'timed_out', or
    None if no check runs found for this SHA.
    """
    # Check runs API for the commit
    path = f"/repos/{owner}/{repo}/commits/{sha}/check-runs?per_page=100"
    data = gh([path])
    check_runs = data.get("check_runs", [])

    # Filter out our own status to avoid circular dependency
    active = [c for c in check_runs if c.get("name") != "ztb/vr-pass"]

    if not active:
        return None

    conclusions: list[str] = []
    for run in active:
        c = run.get("conclusion", run.get("status", "unknown"))
        conclusions.append(c)

    # If any check failed, overall is failure
    for c in conclusions:
        if c in ("failure", "cancelled", "timed_out"):
            return "failure"

    # If all are success or neutral, consider green
    if all(c in ("success", "neutral", "skipped") for c in conclusions):
        return "success"

    # Some are still pending/queued/in_progress or unknown
    return None


def post_commit_status(
    owner: str,
    repo: str,
    sha: str,
    state: str,
    description: str,
) -> None:
    """Post a commit status via GitHub API.

    state: 'success', 'failure', 'pending', 'error'
    """
    body = json.dumps(
        {
            "state": state,
            "target_url": f"https://github.com/{owner}/{repo}/commit/{sha}",
            "description": description,
            "context": "ztb/vr-pass",
        }
    )
    url = f"/repos/{owner}/{repo}/statuses/{sha}"
    gh([url, "--method", "POST", "--input", "-"], input_data=body)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set ztb/vr-pass GitHub commit status for a V&R verdict."
    )
    parser.add_argument(
        "--sha",
        required=True,
        help="Commit SHA to set status on",
    )
    parser.add_argument(
        "--mode",
        choices=["outcome", "notify"],
        default="outcome",
        help="'outcome' (default, requires --outcome) or 'notify' (post pending)",
    )
    parser.add_argument(
        "--outcome",
        choices=["PASS", "FAIL"],
        help="V&R validation outcome (required when --mode=outcome)",
    )
    parser.add_argument(
        "--owner",
        help="GitHub owner (default: auto-detect from git remote)",
    )
    parser.add_argument(
        "--repo",
        help="GitHub repo (default: auto-detect from git remote)",
    )
    args = parser.parse_args()

    if args.mode == "notify":
        owner = args.owner
        repo = args.repo
        if not owner or not repo:
            detected_owner, detected_repo = get_repo_owner_repo()
            owner = owner or detected_owner
            repo = repo or detected_repo
        post_commit_status(
            owner,
            repo,
            args.sha.strip(),
            "pending",
            "V&R validation pending — awaiting human review",
        )
        sha_short = args.sha.strip()[:12]
        print(f"ztb/vr-pass = pending on {sha_short} (notify mode — awaiting V&R review)")
        return

    # mode is "outcome" — require --outcome
    if args.outcome is None:
        fail("--outcome is required when --mode=outcome")

    owner = args.owner
    repo = args.repo
    if not owner or not repo:
        detected_owner, detected_repo = get_repo_owner_repo()
        owner = owner or detected_owner
        repo = repo or detected_repo

    sha = args.sha.strip()

    if args.outcome == "FAIL":
        post_commit_status(owner, repo, sha, "failure", "V&R FAIL — validation rejected")
        print(f"ztb/vr-pass = failure on {sha[:12]} (V&R FAIL)")
        return

    # Outcome is PASS — check CI status first (void-on-FAIL rule)
    ci_conclusion = get_ci_conclusion(owner, repo, sha)

    if ci_conclusion is None:
        # No CI checks found — warn and post pending
        print(
            f"WARNING: No CI check runs found for {sha[:12]}. Posting pending status.",
            file=sys.stderr,
        )
        post_commit_status(
            owner,
            repo,
            sha,
            "pending",
            "V&R PASS pending CI verification — no CI checks found (yet)",
        )
        print(f"ztb/vr-pass = pending on {sha[:12]} (no CI checks found)")
        return

    if ci_conclusion == "failure":
        post_commit_status(
            owner,
            repo,
            sha,
            "failure",
            "V&R PASS VOIDED — CI FAIL on same SHA (void-on-FAIL rule)",
        )
        print(f"ztb/vr-pass = failure on {sha[:12]} (V&R PASS voided: CI has failures on this SHA)")
        return

    # CI is green (success)
    post_commit_status(owner, repo, sha, "success", "V&R PASS — CI green")
    print(f"ztb/vr-pass = success on {sha[:12]} (V&R PASS + CI green)")


if __name__ == "__main__":
    main()
