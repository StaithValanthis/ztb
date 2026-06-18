"""Tests for scripts/ztb-vr-pass-bridge.py — T1–T12 + notify mode."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any
from unittest.mock import patch

import pytest
import ztb_vr_pass_bridge as mod

SHA = "abcdef1234567890abcdef1234567890abcdef12"


def _cp(
    *, stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess[str](
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _check_runs(conclusions: list[str]) -> str:
    runs = [{"name": f"job-{i}", "conclusion": c} for i, c in enumerate(conclusions)]
    return json.dumps({"check_runs": runs})


class TestMainFlow:
    """Main-flow: PASS/FAIL outcomes with various CI states (T1–T4, T11)."""

    @patch.object(mod.subprocess, "run")
    def test_t1_pass_ci_green(
        self,
        mock_run: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """V&R PASS + CI green -> success posted."""
        mock_run.side_effect = [
            _cp(stdout=_check_runs(["success", "success"])),
            _cp(stdout="{}"),
        ]
        argv = [
            "script",
            "--sha",
            SHA,
            "--outcome",
            "PASS",
            "--owner",
            "o",
            "--repo",
            "r",
        ]
        with patch.object(sys, "argv", argv):
            mod.main()
        out, _ = capsys.readouterr()
        assert "success" in out
        assert "V&R PASS + CI green" in out

    @patch.object(mod.subprocess, "run")
    def test_t2_pass_ci_red(
        self,
        mock_run: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """V&R PASS + CI red -> failure posted (PASS voided)."""
        mock_run.side_effect = [
            _cp(stdout=_check_runs(["success", "failure"])),
            _cp(stdout="{}"),
        ]
        argv = [
            "script",
            "--sha",
            SHA,
            "--outcome",
            "PASS",
            "--owner",
            "o",
            "--repo",
            "r",
        ]
        with patch.object(sys, "argv", argv):
            mod.main()
        out, _ = capsys.readouterr()
        assert "failure" in out
        assert "voided" in out

    @patch.object(mod.subprocess, "run")
    def test_t3_pass_ci_pending(
        self,
        mock_run: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """V&R PASS + CI pending/queued -> pending posted."""
        mock_run.side_effect = [
            _cp(stdout=_check_runs(["success", "queued"])),
            _cp(stdout="{}"),
        ]
        argv = [
            "script",
            "--sha",
            SHA,
            "--outcome",
            "PASS",
            "--owner",
            "o",
            "--repo",
            "r",
        ]
        with patch.object(sys, "argv", argv):
            mod.main()
        out, _ = capsys.readouterr()
        assert "pending" in out

    @patch.object(mod.subprocess, "run")
    def test_t4_vr_fail(
        self,
        mock_run: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """V&R FAIL -> failure posted (no CI check)."""
        mock_run.return_value = _cp(stdout="{}")
        argv = [
            "script",
            "--sha",
            SHA,
            "--outcome",
            "FAIL",
            "--owner",
            "o",
            "--repo",
            "r",
        ]
        with patch.object(sys, "argv", argv):
            mod.main()
        out, _ = capsys.readouterr()
        assert "failure" in out
        assert "V&R FAIL" in out

    @patch.object(mod.subprocess, "run")
    def test_t11_no_ci_check_runs(
        self,
        mock_run: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """No CI check-runs -> warning to stderr, pending posted."""
        mock_run.side_effect = [
            _cp(stdout=json.dumps({"check_runs": []})),
            _cp(stdout="{}"),
        ]
        argv = [
            "script",
            "--sha",
            SHA,
            "--outcome",
            "PASS",
            "--owner",
            "o",
            "--repo",
            "r",
        ]
        with patch.object(sys, "argv", argv):
            mod.main()
        out, err = capsys.readouterr()
        assert "pending" in out
        assert "No CI check runs" in err


class TestGhErrors:
    """Error-handling: gh CLI failures (T5–T7, T12)."""

    @patch.object(mod.subprocess, "run")
    def test_t5_gh_not_found(
        self,
        mock_run: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """gh CLI not found -> stderr error, exit 1."""
        mock_run.side_effect = FileNotFoundError()
        argv = [
            "script",
            "--sha",
            SHA,
            "--outcome",
            "PASS",
            "--owner",
            "o",
            "--repo",
            "r",
        ]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit):
            mod.main()
        _, err = capsys.readouterr()
        assert "gh CLI not found" in err

    @patch.object(mod.subprocess, "run")
    def test_t6_gh_error(
        self,
        mock_run: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """gh returns non-zero exit -> stderr error, exit 1."""
        mock_run.return_value = _cp(returncode=1, stderr="Not Found")
        argv = [
            "script",
            "--sha",
            SHA,
            "--outcome",
            "PASS",
            "--owner",
            "o",
            "--repo",
            "r",
        ]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit):
            mod.main()
        _, err = capsys.readouterr()
        assert "gh API call failed" in err

    @patch.object(mod.subprocess, "run")
    def test_t7_gh_non_json(
        self,
        mock_run: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """gh returns non-JSON stdout -> stderr error, exit 1."""
        mock_run.return_value = _cp(stdout="not json at all")
        argv = [
            "script",
            "--sha",
            SHA,
            "--outcome",
            "PASS",
            "--owner",
            "o",
            "--repo",
            "r",
        ]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit):
            mod.main()
        _, err = capsys.readouterr()
        assert "non-JSON" in err

    @patch.object(mod.subprocess, "run")
    def test_t12_gh_timeout(
        self,
        mock_run: Any,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """gh CLI timeout -> stderr error, exit 1."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["gh"], timeout=30)
        argv = [
            "script",
            "--sha",
            SHA,
            "--outcome",
            "PASS",
            "--owner",
            "o",
            "--repo",
            "r",
        ]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit):
            mod.main()
        _, err = capsys.readouterr()
        assert "timed out" in err


class TestGitRemoteParsing:
    """Git remote URL parsing (T8–T9)."""

    @patch.object(mod.subprocess, "run")
    def test_t8_git_remote_https(self, mock_run: Any) -> None:
        """HTTPS remote URL -> (owner, repo)."""
        mock_run.return_value = _cp(
            stdout="https://github.com/MyOwner/my-repo.git",
        )
        result = mod.get_repo_owner_repo()
        assert result == ("MyOwner", "my-repo")

    @patch.object(mod.subprocess, "run")
    def test_t9_git_remote_ssh(self, mock_run: Any) -> None:
        """SSH remote URL -> (owner, repo)."""
        mock_run.return_value = _cp(
            stdout="git@github.com:MyOwner/my-repo.git",
        )
        result = mod.get_repo_owner_repo()
        assert result == ("MyOwner", "my-repo")


def test_t10_self_filter() -> None:
    """CI check-run self-filter: ztb/vr-pass excluded from conclusion."""
    runs = [
        {"name": "ztb/vr-pass", "conclusion": "failure"},
        {"name": "CI / test (3.11)", "conclusion": "success"},
    ]
    with patch.object(mod.subprocess, "run") as mock_run:
        mock_run.return_value = _cp(stdout=json.dumps({"check_runs": runs}))
        result = mod.get_ci_conclusion("o", "r", SHA)
    assert result == "success"


# ── Notify-mode tests (from the merged fix) ──────────────────────────────


def test_notify_mode_posts_pending():
    """--mode notify posts ztb/vr-pass = pending with expected description."""
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
    """--outcome PASS still posts success when CI is green (mode=outcome default)."""
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
    sys.argv = ["ztb-vr-pass-bridge.py", "--sha", "deadbeef", "--mode", "notify"]
    with (
        patch.object(mod, "get_repo_owner_repo", return_value=("owner", "repo")),
        patch("subprocess.run", side_effect=FileNotFoundError("gh not found")),
        pytest.raises(SystemExit) as exc,
    ):
        mod.main()
    assert exc.value.code == 1
