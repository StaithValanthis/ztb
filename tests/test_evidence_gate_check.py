"""Tests for scripts/ztb-evidence-gate-check.py + bridge --context extension."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any
from unittest.mock import patch

import pytest
import ztb_evidence_gate_check as mod
import ztb_vr_pass_bridge as bridge_mod

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


def _status_response(state: str) -> str:
    return json.dumps([{"context": mod.EVIDENCE_CONTEXT, "state": state}])


class TestStrategyDetection:
    """is_strategy_pr detection logic."""

    @patch.object(mod.subprocess, "run")
    def test_strategy_diff_detected(self, mock_run: Any) -> None:
        mock_run.return_value = _cp(stdout="ztb/strategies/sma_cross.py\nztb/execution/executor.py")
        assert mod.is_strategy_pr() is True

    @patch.object(mod.subprocess, "run")
    def test_non_strategy_diff(self, mock_run: Any) -> None:
        mock_run.return_value = _cp(stdout="ztb/execution/executor.py\nENGINEERING.md")
        assert mod.is_strategy_pr() is False

    @patch.object(mod.subprocess, "run")
    def test_empty_diff(self, mock_run: Any) -> None:
        mock_run.return_value = _cp(stdout="")
        assert mod.is_strategy_pr() is False

    @patch.object(mod.subprocess, "run")
    def test_3dot_diff_fails_fallback_succeeds(self, mock_run: Any) -> None:
        mock_run.side_effect = [
            _cp(returncode=128, stderr="no common ancestor"),
            _cp(stdout="ztb/strategies/new_strat.py"),
        ]
        assert mod.is_strategy_pr() is True

    @patch.object(mod.subprocess, "run")
    def test_3dot_diff_fails_fallback_no_strategy(self, mock_run: Any) -> None:
        mock_run.side_effect = [
            _cp(returncode=128, stderr="no common ancestor"),
            _cp(stdout="README.md"),
        ]
        assert mod.is_strategy_pr() is False


class TestEvidenceGateCheck:
    """Evidence-gate main flow."""

    @patch.object(mod.subprocess, "run")
    def test_non_strategy_pr_passes(
        self, mock_run: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_run.side_effect = [
            _cp(stdout="README.md"),
            _cp(stdout="{}"),
        ]
        argv = ["script", "--sha", SHA, "--owner", "o", "--repo", "r"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "trivially passed" in out

    @patch.object(mod.subprocess, "run")
    def test_strategy_pr_no_evidence_gate(
        self, mock_run: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_run.side_effect = [
            _cp(stdout="ztb/strategies/sma_cross.py"),
            _cp(stdout=json.dumps([])),
            _cp(stdout="{}"),
        ]
        argv = ["script", "--sha", SHA, "--owner", "o", "--repo", "r"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "not set" in err

    @patch.object(mod.subprocess, "run")
    def test_strategy_pr_evidence_gate_success(
        self, mock_run: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_run.side_effect = [
            _cp(stdout="ztb/strategies/sma_cross.py"),
            _cp(stdout=_status_response("success")),
            _cp(stdout="{}"),
        ]
        argv = ["script", "--sha", SHA, "--owner", "o", "--repo", "r"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 0
        out, _ = capsys.readouterr()
        assert "PASS" in out

    @patch.object(mod.subprocess, "run")
    def test_strategy_pr_evidence_gate_failure(
        self, mock_run: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_run.side_effect = [
            _cp(stdout="ztb/strategies/sma_cross.py"),
            _cp(stdout=_status_response("failure")),
            _cp(stdout="{}"),
        ]
        argv = ["script", "--sha", SHA, "--owner", "o", "--repo", "r"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "FAIL" in err

    @patch.object(mod.subprocess, "run")
    def test_strategy_pr_evidence_gate_pending(
        self, mock_run: Any, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_run.side_effect = [
            _cp(stdout="ztb/strategies/sma_cross.py"),
            _cp(stdout=_status_response("pending")),
            _cp(stdout="{}"),
        ]
        argv = ["script", "--sha", SHA, "--owner", "o", "--repo", "r"]
        with patch.object(sys, "argv", argv), pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1
        _, err = capsys.readouterr()
        assert "pending" in err


class TestBridgeContextExtension:
    """Bridge --context parameter extension."""

    def test_bridge_context_default(self) -> None:
        """Default --context is ztb/vr-pass -> POST body uses ztb/vr-pass."""
        with (
            patch.object(bridge_mod, "get_repo_owner_repo", return_value=("o", "r")),
            patch.object(bridge_mod, "get_ci_conclusion", return_value="success"),
            patch.object(bridge_mod, "post_commit_status") as mock_post,
            patch.object(
                sys,
                "argv",
                [
                    "bridge.py",
                    "--sha",
                    SHA,
                    "--outcome",
                    "PASS",
                    "--owner",
                    "o",
                    "--repo",
                    "r",
                ],
            ),
        ):
            bridge_mod.main()
        call_args = mock_post.call_args[0]
        call_kwargs = mock_post.call_args[1]
        ctx = call_kwargs.get("context", call_args[5] if len(call_args) > 5 else None)
        assert ctx == "ztb/vr-pass", f"Expected default context 'ztb/vr-pass', got {ctx}"

    def test_bridge_custom_context(self) -> None:
        """Custom --context ztb/vr-evidence-gate is passed through."""
        with (
            patch.object(bridge_mod, "get_repo_owner_repo", return_value=("o", "r")),
            patch.object(bridge_mod, "get_ci_conclusion", return_value="success"),
            patch.object(bridge_mod, "post_commit_status") as mock_post,
            patch.object(
                sys,
                "argv",
                [
                    "bridge.py",
                    "--sha",
                    SHA,
                    "--outcome",
                    "PASS",
                    "--owner",
                    "o",
                    "--repo",
                    "r",
                    "--context",
                    "ztb/vr-evidence-gate",
                ],
            ),
        ):
            bridge_mod.main()
        call_args = mock_post.call_args[0]
        call_kwargs = mock_post.call_args[1]
        ctx = call_kwargs.get("context", call_args[5] if len(call_args) > 5 else None)
        assert ctx == "ztb/vr-evidence-gate", f"Expected custom context, got {ctx}"

    def test_bridge_fail_with_custom_context(self) -> None:
        """Bridge --outcome FAIL with custom context."""
        with (
            patch.object(bridge_mod, "get_repo_owner_repo", return_value=("o", "r")),
            patch.object(bridge_mod, "post_commit_status") as mock_post,
            patch.object(
                sys,
                "argv",
                [
                    "bridge.py",
                    "--sha",
                    SHA,
                    "--outcome",
                    "FAIL",
                    "--owner",
                    "o",
                    "--repo",
                    "r",
                    "--context",
                    "ztb/vr-evidence-gate",
                ],
            ),
        ):
            bridge_mod.main()
        call_args = mock_post.call_args[0]
        call_kwargs = mock_post.call_args[1]
        ctx = call_kwargs.get("context", call_args[5] if len(call_args) > 5 else None)
        assert ctx == "ztb/vr-evidence-gate", f"Expected custom context, got {ctx}"

    def test_bridge_notify_with_custom_context(self) -> None:
        """Bridge --mode notify with custom context."""
        with (
            patch.object(bridge_mod, "get_repo_owner_repo", return_value=("o", "r")),
            patch.object(bridge_mod, "post_commit_status") as mock_post,
            patch.object(
                sys,
                "argv",
                [
                    "bridge.py",
                    "--sha",
                    SHA,
                    "--mode",
                    "notify",
                    "--owner",
                    "o",
                    "--repo",
                    "r",
                    "--context",
                    "ztb/vr-evidence-gate",
                ],
            ),
        ):
            bridge_mod.main()
        call_args = mock_post.call_args[0]
        call_kwargs = mock_post.call_args[1]
        ctx = call_kwargs.get("context", call_args[5] if len(call_args) > 5 else None)
        assert ctx == "ztb/vr-evidence-gate", f"Expected custom context, got {ctx}"
