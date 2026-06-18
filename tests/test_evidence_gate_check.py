"""Tests for scripts/ztb-evidence-gate-check.py."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any
from unittest.mock import patch

import pytest
import ztb_evidence_gate_check as mod

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
