from __future__ import annotations

from click.testing import CliRunner

from ztb.cli import cli


def test_validate_command_exists() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--help"])
    assert result.exit_code == 0
    assert "OOS validation gate" in result.output


def test_validate_missing_strategy_exits_2() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "nonexistent_strat", "BTCUSDT"])
    assert result.exit_code == 2
    assert "Error" in result.output


def test_validate_has_all_options() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "--help"])
    assert "--walk-forward-windows" in result.output
    assert "--train-ratio" in result.output
    assert "--persist" in result.output
    assert "--db" in result.output
    assert "--cash" in result.output
    assert "--commission" in result.output
    assert "--slippage" in result.output
    assert "--timeframe" in result.output
    assert "--category" in result.output


def test_validate_requires_strategy_and_symbol() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate"])
    assert result.exit_code != 0
    assert "Missing argument" in result.output


def test_validate_requires_symbol() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate", "sma_cross"])
    assert result.exit_code != 0
    assert "Missing argument" in result.output
