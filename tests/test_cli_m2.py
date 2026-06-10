from __future__ import annotations

from click.testing import CliRunner

from ztb.cli import cli


def test_list_command() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "sma_cross" in result.output


def test_list_verbose() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["list", "--verbose"])
    assert result.exit_code == 0
    assert "sma_cross" in result.output
    assert "params" in result.output


def test_backtest_missing_strategy() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["backtest", "nonexistent", "BTCUSDT"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_backtest_no_data_returns_error() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["backtest", "sma_cross", "NONEXISTENT"])
    assert result.exit_code == 1
    assert "Error" in result.output or "No cached" in result.output or "No data" in result.output


def test_backtest_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["backtest", "--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_list_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["list", "--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
