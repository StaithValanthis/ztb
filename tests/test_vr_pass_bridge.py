"""Tests for scripts/ztb-vr-pass-bridge.py."""

import sys
from unittest.mock import patch

import pytest


def _bridge():
    """Lazy-import the bridge module (loaded by conftest)."""
    import ztb_vr_pass_bridge

    return ztb_vr_pass_bridge


def test_notify_mode_posts_pending():
    """--mode notify posts ztb/vr-pass = pending with expected description."""
    mod = _bridge()
    with (
        patch.object(mod, "post_commit_status") as mock_post,
        patch.object(mod, "get_repo_owner_repo", return_value=("owner", "repo")),
    ):
        sys.argv = ["ztb-vr-pass-bridge.py", "--sha", "deadbeef", "--mode", "notify"]
        mod.main()
    mock_post.assert_called_once()
    args = mock_post.call_args[0]
    assert args[3] == "pending", f"Expected state=pending, got {args[3]}"
    assert "awaiting human review" in args[4], f"Expected review description, got {args[4]}"


def test_notify_mode_logs_action(capsys):
    """--mode notify prints the expected status line to stdout."""
    mod = _bridge()
    with (
        patch.object(mod, "get_repo_owner_repo", return_value=("owner", "repo")),
        patch.object(mod, "post_commit_status"),
    ):
        sys.argv = ["ztb-vr-pass-bridge.py", "--sha", "deadbeef", "--mode", "notify"]
        mod.main()
    captured = capsys.readouterr()
    assert "ztb/vr-pass = pending" in captured.out
    assert "V&R review" in captured.out


def test_outcome_pass_still_works():
    """--outcome PASS still posts success when CI is green."""
    mod = _bridge()
    with (
        patch.object(mod, "get_repo_owner_repo", return_value=("owner", "repo")),
        patch.object(mod, "post_commit_status") as mock_post,
        patch.object(mod, "get_ci_conclusion", return_value="success"),
    ):
        sys.argv = ["ztb-vr-pass-bridge.py", "--sha", "deadbeef", "--outcome", "PASS"]
        mod.main()
    mock_post.assert_called_once()
    args = mock_post.call_args[0]
    assert args[3] == "success", f"Expected state=success, got {args[3]}"


def test_outcome_fail_still_works():
    """--outcome FAIL still posts failure."""
    mod = _bridge()
    with (
        patch.object(mod, "get_repo_owner_repo", return_value=("owner", "repo")),
        patch.object(mod, "post_commit_status") as mock_post,
    ):
        sys.argv = ["ztb-vr-pass-bridge.py", "--sha", "deadbeef", "--outcome", "FAIL"]
        mod.main()
    mock_post.assert_called_once()
    args = mock_post.call_args[0]
    assert args[3] == "failure", f"Expected state=failure, got {args[3]}"


def test_notify_mode_graceful_without_gh():
    """--mode notify exits gracefully (code 1) when gh CLI is unavailable."""
    mod = _bridge()
    sys.argv = ["ztb-vr-pass-bridge.py", "--sha", "deadbeef", "--mode", "notify"]
    with (
        patch.object(mod, "get_repo_owner_repo", return_value=("owner", "repo")),
        patch("subprocess.run", side_effect=FileNotFoundError("gh not found")),
        pytest.raises(SystemExit) as exc,
    ):
        mod.main()
    assert exc.value.code == 1
