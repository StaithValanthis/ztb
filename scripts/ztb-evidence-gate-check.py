#!/usr/bin/env python3
"""
ztb-evidence-gate-check.py — CI gate that blocks strategy PRs without V&R PASS.

Usage:
    python3 scripts/ztb-evidence-gate-check.py --sha <commit-sha>

Detects whether the PR touches ztb/strategies/. If so, checks that
ztb/vr-pass = success on the exact SHA. Posts its own status
ztb/strategy-evidence-gate for UI visibility.
"""

import argparse
import json
import subprocess
import sys
from typing import Any, NoReturn

GATE_CONTEXT = "ztb/strategy-evidence-gate"
EVIDENCE_CONTEXT = "ztb/vr-pass"
# The deterministic CI edge gate. A strategy PR that passes this cleared the walk-forward OOS
# bar in CI ($0, ungameable) — STRONGER evidence than a per-PR V&R attestation, so it satisfies
# the evidence gate directly (no DeepSeek V&R cycle needed). Name == the ci.yml job id.
STRATEGY_VALIDATE_CHECK = "strategy-validate"


def fail(msg: str) -> NoReturn:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def gh(args: list[str], input_data: str | None = None) -> dict[str, Any]:
    cmd = ["gh", "api"] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, input=input_data, timeout=30)
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

    for prefix in ("https://github.com/", "git@github.com:"):
        if url.startswith(prefix):
            rest = url.removeprefix(prefix).removesuffix(".git")
            parts = rest.split("/")
            if len(parts) >= 2:
                return parts[0], parts[1]
    fail(f"cannot parse owner/repo from remote URL: {url}")


def is_strategy_pr() -> bool:
    """Detect if PR changes files under ztb/strategies/.

    Uses git diff against origin/main. Falls back to HEAD~1..HEAD diff
    if the 3-dot diff fails (new branch, no common ancestor).
    """
    # Try 3-dot diff first
    r = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode == 0:
        files = r.stdout.strip().splitlines()
        return any(f.startswith("ztb/strategies/") for f in files if f)

    # Fallback: 2-dot diff against HEAD~1
    r = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~1..HEAD"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode == 0:
        files = r.stdout.strip().splitlines()
        return any(f.startswith("ztb/strategies/") for f in files if f)
    return False


def get_commit_status(owner: str, repo: str, sha: str, context: str) -> str | None:
    """Query GitHub commit status for a given context.

    Returns 'success', 'failure', 'pending', or None if not set.
    """
    data = gh([f"/repos/{owner}/{repo}/commits/{sha}/statuses"])
    statuses = data if isinstance(data, list) else data.get("statuses", [])
    for s in statuses:
        if s.get("context") == context:
            return s.get("state")
    return None


def get_check_conclusion(owner: str, repo: str, sha: str, name: str) -> str | None:
    """Return a named check-run's conclusion on the SHA, or None if absent/not completed."""
    data = gh([f"/repos/{owner}/{repo}/commits/{sha}/check-runs?per_page=100"])
    runs = data.get("check_runs", []) if isinstance(data, dict) else []
    for run in runs:
        if run.get("name") == name:
            if run.get("status") != "completed":
                return None
            return run.get("conclusion")
    return None


def post_commit_status(
    owner: str,
    repo: str,
    sha: str,
    state: str,
    description: str,
    context: str = GATE_CONTEXT,
) -> None:
    body = json.dumps(
        {
            "state": state,
            "target_url": f"https://github.com/{owner}/{repo}/commit/{sha}",
            "description": description,
            "context": context,
        }
    )
    gh(
        [f"/repos/{owner}/{repo}/statuses/{sha}", "--method", "POST", "--input", "-"],
        input_data=body,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CI gate: block strategy PRs without V&R evidence-gate PASS."
    )
    parser.add_argument("--sha", required=True, help="Commit SHA to check")
    parser.add_argument("--owner", help="GitHub owner (default: auto-detect)")
    parser.add_argument("--repo", help="GitHub repo (default: auto-detect)")
    args = parser.parse_args()

    owner = args.owner
    repo = args.repo
    if not owner or not repo:
        detected_owner, detected_repo = get_repo_owner_repo()
        owner = owner or detected_owner
        repo = repo or detected_repo

    sha = args.sha.strip()

    # Step 1: detect if this is a strategy PR
    if not is_strategy_pr():
        post_commit_status(owner, repo, sha, "success", "Non-strategy PR — evidence gate skipped")
        print(f"{GATE_CONTEXT} = success on {sha[:12]} (non-strategy PR, trivially passed)")
        sys.exit(0)

    print(f"Strategy PR detected on {sha[:12]} — checking evidence...")

    # Step 1b: deterministic edge gate. If the CI strategy-validate check passed on this SHA, the
    # strategy cleared the walk-forward OOS bar — accept it directly (no V&R attestation / DeepSeek
    # cycle needed). Fails closed if strategy-validate failed; falls back to the V&R path if it did
    # not run (None), preserving the legacy attestation route.
    sv = get_check_conclusion(owner, repo, sha, STRATEGY_VALIDATE_CHECK)
    if sv == "success":
        post_commit_status(
            owner,
            repo,
            sha,
            "success",
            "strategy-validate PASS (deterministic OOS edge gate) — V&R attestation not required",
        )
        print(f"{GATE_CONTEXT} = success on {sha[:12]} (strategy-validate PASS — auto-cleared)")
        sys.exit(0)
    if sv in ("failure", "cancelled", "timed_out"):
        post_commit_status(
            owner,
            repo,
            sha,
            "failure",
            "strategy-validate FAILED — strategy did not clear the OOS edge gate",
        )
        print(f"{GATE_CONTEXT} = failure on {sha[:12]} (strategy-validate FAILED)", file=sys.stderr)
        sys.exit(1)

    # Step 2: strategy-validate did not run (None) — fall back to the V&R vr-pass attestation
    ev_status = get_commit_status(owner, repo, sha, EVIDENCE_CONTEXT)

    if ev_status == "success":
        post_commit_status(owner, repo, sha, "success", f"{EVIDENCE_CONTEXT} = PASS on this SHA")
        print(f"{GATE_CONTEXT} = success on {sha[:12]} ({EVIDENCE_CONTEXT} = PASS)")
        sys.exit(0)

    if ev_status is None:
        reason = f"{EVIDENCE_CONTEXT} not set on this SHA — no V&R evidence gate verdict"
    elif ev_status == "failure":
        reason = f"{EVIDENCE_CONTEXT} = FAIL on this SHA — V&R rejected this commit"
    elif ev_status == "pending":
        reason = f"{EVIDENCE_CONTEXT} = pending on this SHA — V&R review not yet complete"
    else:
        reason = f"{EVIDENCE_CONTEXT} = {ev_status} on this SHA"

    post_commit_status(owner, repo, sha, "failure", reason)
    print(f"{GATE_CONTEXT} = failure on {sha[:12]} ({reason})", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
