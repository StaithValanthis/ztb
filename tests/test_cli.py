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


def test_backtest_stub() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["backtest"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


def test_data_stub() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["data"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output


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


def test_list_stub() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "not yet implemented" in result.output
