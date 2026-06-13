from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

_spec = importlib.util.spec_from_file_location(
    "ztb_vr_pass_bridge",
    Path("scripts/ztb-vr-pass-bridge.py"),
)
spec: importlib.machinery.ModuleSpec = _spec  # type: ignore[assignment]
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)

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
        argv = ["script", "--sha", SHA, "--outcome", "PASS", "--owner", "o", "--repo", "r"]
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
        argv = ["script", "--sha", SHA, "--outcome", "PASS", "--owner", "o", "--repo", "r"]
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
        argv = ["script", "--sha", SHA, "--outcome", "PASS", "--owner", "o", "--repo", "r"]
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
        argv = ["script", "--sha", SHA, "--outcome", "FAIL", "--owner", "o", "--repo", "r"]
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
        argv = ["script", "--sha", SHA, "--outcome", "PASS", "--owner", "o", "--repo", "r"]
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
        argv = ["script", "--sha", SHA, "--outcome", "PASS", "--owner", "o", "--repo", "r"]
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
        argv = ["script", "--sha", SHA, "--outcome", "PASS", "--owner", "o", "--repo", "r"]
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
        argv = ["script", "--sha", SHA, "--outcome", "PASS", "--owner", "o", "--repo", "r"]
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
        argv = ["script", "--sha", SHA, "--outcome", "PASS", "--owner", "o", "--repo", "r"]
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
