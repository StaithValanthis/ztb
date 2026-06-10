from click.testing import CliRunner

from ztb.cli import cli


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "ztb" in result.output


def test_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_data_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["data", "--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "fetch" in result.output
    assert "show" in result.output
    assert "verify" in result.output
    assert "instruments" in result.output


def test_data_show_no_cache() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["data", "show", "NONEXISTENT"])
    assert result.exit_code == 1
    assert "No cached data" in result.output


def test_data_verify_no_cache() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["data", "verify", "NONEXISTENT"])
    assert result.exit_code == 1
    assert "No cached data" in result.output


def test_data_fetch_no_symbol_fails() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["data", "fetch"])
    assert result.exit_code != 0


def test_backtest_no_args_fails() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["backtest"])
    assert result.exit_code != 0


def test_data_group_usage() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["data"])
    assert result.exit_code == 0 or result.exit_code == 2


def test_forwardtest_stub() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["forwardtest"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_validate_stub() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["validate"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_run_stub() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["run"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_report_stub() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["report"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_dashboard_stub() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["dashboard"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_list_shows_strategies() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "sma_cross" in result.output
