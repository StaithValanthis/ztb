from unittest.mock import patch

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


def test_report_no_args() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["report"])
    assert result.exit_code == 1
    assert "No runs found" in result.output


def test_report_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_dashboard_help() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["dashboard", "--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_list_shows_strategies() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "sma_cross" in result.output


def test_report_with_run_id_not_found(tmp_path) -> None:
    runner = CliRunner()
    db_path = str(tmp_path / "test.db")
    result = runner.invoke(cli, ["report", "--run-id", "nonexistent", "--db", db_path])
    assert result.exit_code == 1
    assert "Run not found" in result.output


def test_report_list_with_data(tmp_path) -> None:
    import pandas as pd

    from ztb.engine.backtest import BacktestConfig, run_backtest
    from ztb.store.results import connect, save_run
    from ztb.strategies.registry import get as get_strategy

    db_path = str(tmp_path / "test.db")
    cls = get_strategy("sma_cross")
    strat = cls()
    strat.symbols = ["TEST"]
    df = pd.DataFrame(
        {
            "open": [100.0] * 200,
            "high": [101.0] * 200,
            "low": [99.0] * 200,
            "close": [100.0 + i * 0.1 for i in range(200)],
            "volume": [1000.0] * 200,
        },
        index=pd.date_range("2020-01-01", periods=200, freq="h"),
    )
    result = run_backtest(strat, df, BacktestConfig(min_trades=0))
    conn = connect(db_path)
    run_id = save_run(conn, result)
    conn.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--db", db_path])
    assert result.exit_code == 0
    assert "Recent runs" in result.output
    assert "sma_cross" in result.output

    result = runner.invoke(cli, ["report", "--run-id", run_id, "--db", db_path])
    assert result.exit_code == 0
    assert "sma_cross" in result.output
    assert "TEST" in result.output


def test_report_with_scorecard(tmp_path) -> None:
    import pandas as pd

    from ztb.engine.backtest import BacktestConfig, run_backtest
    from ztb.store.results import connect, save_run
    from ztb.strategies.registry import get as get_strategy

    db_path = str(tmp_path / "test.db")
    cls = get_strategy("sma_cross")
    strat = cls()
    strat.symbols = ["TEST"]
    df = pd.DataFrame(
        {
            "open": [100.0] * 200,
            "high": [101.0] * 200,
            "low": [99.0] * 200,
            "close": [100.0 + i * 0.1 for i in range(200)],
            "volume": [1000.0] * 200,
        },
        index=pd.date_range("2020-01-01", periods=200, freq="h"),
    )
    result = run_backtest(strat, df, BacktestConfig(min_trades=0))
    conn = connect(db_path)
    run_id = save_run(conn, result)
    conn.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["report", "--run-id", run_id, "--db", db_path, "--scorecard"])
    assert result.exit_code == 0
    assert "Scorecard" in result.output
    assert "credible=True" in result.output


def test_backtest_persist(tmp_path) -> None:

    db_path = str(tmp_path / "test.db")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "backtest",
            "sma_cross",
            "NONEXISTENT",
            "--db",
            db_path,
            "--persist",
        ],
    )
    assert result.exit_code == 1


def test_dashboard_no_streamlit(tmp_path) -> None:
    runner = CliRunner()
    with patch("subprocess.run", side_effect=FileNotFoundError):
        result = runner.invoke(cli, ["dashboard", "--db", str(tmp_path / "none.db")])
    assert result.exit_code == 1
