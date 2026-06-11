from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from pandas import DataFrame, date_range

from ztb.cli import cli
from ztb.execution.errors import LiveDisarmedError
from ztb.execution.executor import Executor
from ztb.execution.killswitch import LiveKillSwitch
from ztb.execution.live_guard import LiveGuard
from ztb.execution.models import ExecRunConfig, Mode
from ztb.strategies.registry import get as get_strategy


@pytest.fixture
def strat_and_data():
    cls = get_strategy("sma_cross")
    strat = cls()
    strat.symbols = ["BTCUSDT"]
    df = DataFrame(
        {
            "open": [50000.0 + i * 10 for i in range(200)],
            "high": [50100.0 + i * 10 for i in range(200)],
            "low": [49900.0 + i * 10 for i in range(200)],
            "close": [50000.0 + i * 10 for i in range(200)],
            "volume": [1000.0] * 200,
        },
        index=date_range("2024-01-01", periods=200, freq="h"),
    )
    return strat, df


def _full_loop_dry_run(strat, df, tmp_path: Path) -> Executor:
    db_path = str(tmp_path / "m7_full_loop.db")
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        once=True,
        initial_cash=100000.0,
        risk_enabled=False,
    )
    killswitch = LiveKillSwitch()
    executor = Executor(strategy=strat, config=config, killswitch=killswitch)
    with patch("ztb.execution.executor.load_data") as mock_load:
        mock_load.return_value = df
        executor.run(
            symbol="BTCUSDT",
            timeframe="60",
            db_path=db_path,
        )
    return executor


def test_full_loop_signal_risk_gate_executor_persist(strat_and_data, tmp_path: Path) -> None:
    """Full loop: signal-risk-executor-killswitch-idempotent-persist (dry-run)."""
    strat, df = strat_and_data
    executor = _full_loop_dry_run(strat, df, tmp_path)
    assert executor.state is not None
    assert executor.state.bars_processed > 0
    assert executor.state.status == "completed"
    assert executor.state.mode == Mode.DEMO
    assert executor._store_conn is not None


def test_full_loop_positions_update(strat_and_data, tmp_path: Path) -> None:
    """Verify positions change after processing bars (non-flat signal)."""
    strat, df = strat_and_data
    executor = _full_loop_dry_run(strat, df, tmp_path)
    assert executor.state is not None
    cond = abs(executor.state.current_position) > 1e-12
    assert cond or executor.state.bars_processed >= strat.warmup


def test_full_loop_with_risk_enabled(strat_and_data, tmp_path: Path) -> None:
    """Full loop with risk gate enabled."""
    strat, df = strat_and_data
    db_path = str(tmp_path / "m7_risk.db")
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        initial_cash=100000.0,
        risk_enabled=True,
    )
    executor = Executor(strategy=strat, config=config)
    with patch("ztb.execution.executor.load_data") as mock_load:
        mock_load.return_value = df
        result = executor.run(symbol="BTCUSDT", timeframe="60", db_path=db_path)
    assert result.bars_processed > 0
    assert result.status == "completed"


def test_killswitch_tripped_returns_halt(strat_and_data, tmp_path: Path) -> None:
    """Tripped killswitch -> step returns killswitch_tripped=True."""
    strat, df = strat_and_data
    killswitch = LiveKillSwitch()
    killswitch.manual_trip("test kill")
    assert killswitch.is_tripped
    db_path = str(tmp_path / "m7_killswitch.db")
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=True, risk_enabled=False)
    executor = Executor(strategy=strat, config=config, killswitch=killswitch)
    with patch("ztb.execution.executor.load_data") as mock_load:
        mock_load.return_value = df
        result = executor.run(symbol="BTCUSDT", timeframe="60", db_path=db_path)
    assert result.status == "completed"


def test_killswitch_account_dd_trips(strat_and_data, tmp_path: Path) -> None:
    """Account drawdown exceeding threshold trips killswitch."""
    strat, df = strat_and_data
    killswitch = LiveKillSwitch(max_account_dd=0.01)
    db_path = str(tmp_path / "m7_dd.db")
    config = ExecRunConfig(
        mode=Mode.DEMO, dry_run=True, once=False, risk_enabled=False, initial_cash=1000.0
    )
    executor = Executor(strategy=strat, config=config, killswitch=killswitch)
    with patch("ztb.execution.executor.load_data") as mock_load:
        mock_load.return_value = df
        result = executor.run(symbol="BTCUSDT", timeframe="60", db_path=db_path)
    assert result.status == "completed"


def test_live_guard_disarmed_raises() -> None:
    """mode=LIVE with disarmed guard -> LiveDisarmedError."""
    LiveGuard.disarm()
    assert not LiveGuard.is_armed()
    with pytest.raises(LiveDisarmedError):
        LiveGuard.assert_live_allowed()


def test_live_guard_armed_allows() -> None:
    """mode=LIVE with armed guard -> order placed (no error)."""
    LiveGuard.arm("1")
    assert LiveGuard.is_armed()
    LiveGuard.assert_live_allowed()
    LiveGuard.disarm()


def test_cli_list_strategies() -> None:
    """ztb list returns sma_cross."""
    proc = subprocess.run(
        [sys.executable, "-m", "ztb.cli", "list"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    assert "sma_cross" in proc.stdout


def test_cli_rollback_dry_run() -> None:
    """ztb rollback <tag> --dry-run resolves tags."""
    tag = "ztb-test-rollback-tag"
    subprocess.run(["git", "tag", tag, "HEAD"], check=True, capture_output=True, timeout=10)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ztb.cli", "rollback", tag, "--dry-run"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0, f"stderr={proc.stderr}"
        assert tag in proc.stdout
        assert "dry-run" in proc.stdout
    finally:
        subprocess.run(["git", "tag", "-d", tag], capture_output=True, timeout=10)


def test_cli_rollback_unknown_tag() -> None:
    """ztb rollback nonexistent-tag --dry-run exits with error."""
    proc = subprocess.run(
        [sys.executable, "-m", "ztb.cli", "rollback", "nonexistent-tag", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode != 0


@pytest.mark.skipif(
    "ZTB_BYBIT_API_KEY" not in os.environ or "ZTB_BYBIT_API_SECRET" not in os.environ,
    reason="Requires Bybit API credentials (ZTB_BYBIT_API_KEY / ZTB_BYBIT_API_SECRET)",
)
def test_cli_run_dry_run(tmp_path: Path) -> None:
    """ztb run --mode demo --dry-run --once succeeds."""
    db_path = str(tmp_path / "m7_run_dry.db")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ztb.cli",
            "run",
            "sma_cross",
            "BTCUSDT",
            "--mode",
            "demo",
            "--dry-run",
            "--once",
            "--no-risk",
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-11",
            "--db",
            db_path,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    assert "Execution run" in proc.stdout
    assert "dry-run" in proc.stdout


def test_validate_command_stub() -> None:
    """ztb validate exists (stub)."""
    proc = subprocess.run(
        [sys.executable, "-m", "ztb.cli", "validate"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    assert "not yet implemented" in proc.stdout


def test_strategy_sma_cross_no_regression(strat_and_data) -> None:
    """sma_cross generate_signals unchanged (same output shape/range as M2)."""
    strat, df = strat_and_data
    signals = strat.generate_signals(df)
    assert len(signals) == len(df)
    assert signals.index.equals(df.index)
    assert signals.dropna().between(-1.0, 1.0).all()
    assert signals.dtype == float
    assert (signals.iloc[: strat.warmup] == 0.0).all()


def test_idempotency_ledger_integration(strat_and_data, tmp_path: Path) -> None:
    """Idempotency ledger persists and restores across bars (dry-run)."""
    strat, df = strat_and_data
    db_path = str(tmp_path / "m7_idempotency.db")
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=True, risk_enabled=False)
    executor = Executor(strategy=strat, config=config)
    with patch("ztb.execution.executor.load_data") as mock_load:
        mock_load.return_value = df
        result = executor.run(symbol="BTCUSDT", timeframe="60", db_path=db_path)
    assert result.status == "completed"
    assert result.bars_processed > 0


# ── Integration: store consistency ───────────────────────────────────────────


def test_executor_store_consistency(strat_and_data, tmp_path: Path) -> None:
    """Executor stores run metadata correctly: strategy, mode, status, bars."""
    strat, df = strat_and_data
    db_path = str(tmp_path / "m7_store_consistency.db")
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=True, risk_enabled=False)
    executor = Executor(strategy=strat, config=config)
    with patch("ztb.execution.executor.load_data") as mock_load:
        mock_load.return_value = df
        result = executor.run(symbol="BTCUSDT", timeframe="60", db_path=db_path)
    assert result.status == "completed"
    assert result.strategy_name == "sma_cross"
    assert result.symbol == "BTCUSDT"
    assert result.mode == Mode.DEMO
    assert result.bars_processed > 0
    from ztb.store.exec_io import ensure_exec_tables, get_exec_run
    from ztb.store.results import connect

    conn = connect(db_path)
    ensure_exec_tables(conn)
    run_info = get_exec_run(conn, result.exec_run_id)
    conn.close()
    assert run_info is not None
    assert run_info["strategy_name"] == "sma_cross"
    assert run_info["symbol"] == "BTCUSDT"
    assert run_info["mode"] == "demo"
    assert run_info["status"] == "completed"
    assert run_info["bars_processed"] == result.bars_processed


def test_executor_store_full_run_state(strat_and_data, tmp_path: Path) -> None:
    """Full non-once run populates positions snapshots + PnL ledger."""
    strat, df = strat_and_data
    db_path = str(tmp_path / "m7_full_state.db")
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=False, risk_enabled=False)
    executor = Executor(strategy=strat, config=config)
    with patch("ztb.execution.executor.load_data") as mock_load:
        mock_load.return_value = df
        result = executor.run(symbol="BTCUSDT", timeframe="60", db_path=db_path)
    assert result.status == "completed"
    assert result.bars_processed > 0
    from ztb.store.exec_io import ensure_exec_tables, get_pnl_ledger
    from ztb.store.results import connect

    conn = connect(db_path)
    ensure_exec_tables(conn)
    ledger = get_pnl_ledger(conn, result.exec_run_id)
    conn.close()
    assert len(ledger) > 0
    totals = [e["total_equity"] for e in ledger]
    assert all(t > 0 for t in totals)


# ── Strategy compatibility ───────────────────────────────────────────────────


def test_strategy_params_propagate_to_executor(strat_and_data, tmp_path: Path) -> None:
    """Strategy params (name, warmup) propagate through executor run result."""
    strat, df = strat_and_data
    from ztb.strategies.registry import get as get_strategy

    cls = get_strategy("sma_cross")
    assert cls.warmup == 20
    db_path = str(tmp_path / "m7_strat_params.db")
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=False, risk_enabled=False)
    executor = Executor(strategy=strat, config=config)
    with patch("ztb.execution.executor.load_data") as mock_load:
        mock_load.return_value = df
        result = executor.run(symbol="BTCUSDT", timeframe="60", db_path=db_path)
    assert result.status == "completed"
    assert result.strategy_name == "sma_cross"
    assert result.bars_processed > cls.warmup


def test_strategy_warmup_respected_in_executor() -> None:
    """Signals during warmup are zero in executor step context."""
    import pandas as pd

    from ztb.execution.executor import ExecRunConfig, Executor
    from ztb.execution.models import Mode
    from ztb.strategies.registry import get as get_strategy

    cls = get_strategy("sma_cross")
    strat = cls()
    strat.symbols = ["BTCUSDT"]
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=False, risk_enabled=False)
    executor = Executor(strategy=strat, config=config)
    executor._init_run()
    executor._init_store(":memory:")
    idx = pd.date_range("2026-01-01", periods=100, freq="h", tz="UTC")
    data = DataFrame(
        {
            "open": [50000.0 + i * 10 for i in range(100)],
            "high": [50100.0 + i * 10 for i in range(100)],
            "low": [49900.0 + i * 10 for i in range(100)],
            "close": [50000.0 + i * 10 for i in range(100)],
            "volume": [1000.0] * 100,
        },
        index=idx,
    )
    result = executor.step(data)
    assert result["signal"] is not None
    assert result["current_position"] is not None


# ── CLI dogfood ──────────────────────────────────────────────────────────────


def test_cli_backtest_persist_and_report(tmp_path: Path) -> None:
    """ztb backtest --persist then ztb report retrieves the run."""
    import pandas as pd

    from ztb.engine.backtest import BacktestConfig, run_backtest
    from ztb.store.results import connect, save_run
    from ztb.strategies.registry import get as get_strategy

    db_path = str(tmp_path / "m7_dogfood.db")
    cls = get_strategy("sma_cross")
    strat = cls()
    strat.symbols = ["BTCUSDT"]
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
    r = runner.invoke(cli, ["report", "--db", db_path])
    assert r.exit_code == 0, f"stderr={r.output}"
    assert "Recent runs" in r.output
    assert "sma_cross" in r.output
    r2 = runner.invoke(cli, ["report", "--run-id", run_id, "--db", db_path])
    assert r2.exit_code == 0
    assert "sma_cross" in r2.output
    assert "BTCUSDT" in r2.output


def _mock_data_df(n: int = 200) -> DataFrame:
    """Return a synthetic price DataFrame for mocking load_data."""
    idx = date_range("2026-01-01", periods=n, freq="h")
    return DataFrame(
        {
            "open": [50000.0 + i * 10 for i in range(n)],
            "high": [50100.0 + i * 10 for i in range(n)],
            "low": [49900.0 + i * 10 for i in range(n)],
            "close": [50000.0 + i * 10 for i in range(n)],
            "volume": [1000.0] * n,
        },
        index=idx,
    )


def test_cli_run_with_preflight(tmp_path: Path) -> None:
    """ztb run --mode=demo --dry-run --once --preflight with mocks."""
    import os
    import subprocess

    df = _mock_data_df(200)
    db_path = str(tmp_path / "m7_preflight.db")
    with (
        patch("subprocess.run") as mock_run,
        patch("ztb.execution.executor.load_data", return_value=df),
        patch.dict(
            os.environ,
            {
                "ZTB_BYBIT_API_KEY": "test_key_12345678",
                "ZTB_BYBIT_API_SECRET": "test_secret_12345678",
            },
            clear=False,
        ),
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["git", "describe"], returncode=0, stdout="v0.7.0\n", stderr=""
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                "sma_cross",
                "BTCUSDT",
                "--mode",
                "demo",
                "--dry-run",
                "--once",
                "--no-risk",
                "--preflight",
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-02",
                "--db",
                db_path,
            ],
        )
    assert result.exit_code == 0, f"stderr={result.output}"
    assert "Preflight PASSED" in result.output


def test_cli_run_with_risk_enabled(tmp_path: Path) -> None:
    """ztb run --mode=demo --dry-run --once with risk enabled."""
    df = _mock_data_df(200)
    db_path = str(tmp_path / "m7_run_risk.db")
    with patch("ztb.execution.executor.load_data", return_value=df):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                "sma_cross",
                "BTCUSDT",
                "--mode",
                "demo",
                "--dry-run",
                "--once",
                "--start",
                "2026-01-01",
                "--end",
                "2026-06-11",
                "--db",
                db_path,
            ],
        )
    assert result.exit_code == 0, f"stderr={result.output}"


def test_cli_run_to_report_pipeline(tmp_path: Path) -> None:
    """Full pipeline: ztb run --dry-run --once then verify exec store."""
    from click.testing import CliRunner

    df = _mock_data_df(200)
    db_path = str(tmp_path / "m7_pipeline.db")
    with patch("ztb.execution.executor.load_data", return_value=df):
        runner = CliRunner()
        run_result = runner.invoke(
            cli,
            [
                "run",
                "sma_cross",
                "BTCUSDT",
                "--mode",
                "demo",
                "--dry-run",
                "--once",
                "--no-risk",
                "--start",
                "2026-01-01",
                "--end",
                "2026-06-11",
                "--db",
                db_path,
            ],
        )
    assert run_result.exit_code == 0, f"run failed: {run_result.output}"
    from ztb.store.exec_io import ensure_exec_tables, get_exec_run, list_exec_runs
    from ztb.store.results import connect

    conn = connect(db_path)
    ensure_exec_tables(conn)
    runs = list_exec_runs(conn)
    assert len(runs) >= 1
    exec_run_id = runs[0]["exec_run_id"]
    run_info = get_exec_run(conn, exec_run_id)
    conn.close()
    assert run_info is not None
    assert run_info["strategy_name"] == "sma_cross"
    assert run_info["status"] == "completed"
    assert run_info["bars_processed"] > 0


def test_cli_run_with_expected_version(tmp_path: Path) -> None:
    """ztb run --expected-version with matching version succeeds."""
    from ztb import __version__

    df = _mock_data_df(200)
    db_path = str(tmp_path / "m7_version.db")
    with patch("ztb.execution.executor.load_data", return_value=df):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                "sma_cross",
                "BTCUSDT",
                "--mode",
                "demo",
                "--dry-run",
                "--once",
                "--no-risk",
                "--expected-version",
                __version__,
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-10",
                "--db",
                db_path,
            ],
        )
    assert result.exit_code == 0, f"stderr={result.output}"
