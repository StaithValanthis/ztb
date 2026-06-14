from __future__ import annotations

from click.testing import CliRunner

from ztb.cli import cli


def test_validate_group_exists() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate"])
    assert result.exit_code == 0
    assert "Validation commands" in result.output


def test_validate_walkforward_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "walkforward", "--help"])
    assert result.exit_code == 0
    assert "Run walk-forward analysis" in result.output


def test_validate_scorecard_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "scorecard", "--help"])
    assert result.exit_code == 0
    assert "validation scorecard" in result.output


def test_validate_lookahead_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "lookahead", "--help"])
    assert result.exit_code == 0
    assert "look-ahead bias" in result.output.lower()


def test_validate_dsr_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "dsr", "--help"])
    assert result.exit_code == 0
    assert "Deflated Sharpe" in result.output


def test_validate_report_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "report", "--help"])
    assert result.exit_code == 0
    assert "validation results" in result.output


def test_validate_walkforward_no_args_fails() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "walkforward"])
    assert result.exit_code != 0
    assert "Missing argument" in result.output


def test_validate_dsr_no_args_fails() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "dsr"])
    assert result.exit_code != 0
    assert "Missing argument" in result.output


def test_validate_scorecard_no_args_fails() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "scorecard"])
    assert result.exit_code != 0
    assert "Missing argument" in result.output


def test_validate_lookahead_no_args_fails() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "lookahead"])
    assert result.exit_code != 0
    assert "Missing argument" in result.output


def test_validate_report_no_args_defaults() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "report"])
    assert result.exit_code == 0 or result.exit_code == 1
    assert "No validation runs found" in result.output or "validation" in result.output.lower()
