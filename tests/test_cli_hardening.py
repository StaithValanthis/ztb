from __future__ import annotations

import subprocess
from unittest.mock import patch

from click.testing import CliRunner

from ztb.cli import cli


def test_run_help_has_preflight() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "--preflight" in result.output


def test_run_help_has_expected_tag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "--expected-tag" in result.output


def test_rollback_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["rollback", "--help"])
    assert result.exit_code == 0
    assert "Roll back" in result.output


def test_rollback_requires_tag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["rollback"])
    assert result.exit_code != 0
    assert "Missing argument" in result.output or "Error" in result.output


def test_rollback_dry_run_nonexistent_tag() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["rollback", "v999.999.999", "--dry-run"])
    assert result.exit_code != 0
    assert "not found" in result.output


def test_rollback_dry_run_valid_tag() -> None:
    runner = CliRunner()
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "rev-parse"], returncode=0, stdout="deadbeef1234\n", stderr=""
        )
        result = runner.invoke(cli, ["rollback", "v0.7.0", "--dry-run"])
    assert result.exit_code == 0
    assert "dry-run" in result.output


def test_run_help_has_expected_version() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--help"])
    assert result.exit_code == 0
    assert "--expected-version" in result.output
