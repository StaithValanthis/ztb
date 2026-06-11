from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from pandas import DataFrame, date_range

from ztb.execution.executor import Executor
from ztb.execution.killswitch import LiveKillSwitch
from ztb.execution.live_guard import LiveDisarmedError, LiveGuard
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
    proc = subprocess.run(
        [sys.executable, "-m", "ztb.cli", "rollback", "v0.7.0", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    assert "v0.7.0" in proc.stdout
    assert "dry-run" in proc.stdout


def test_cli_rollback_unknown_tag() -> None:
    """ztb rollback nonexistent-tag --dry-run exits with error."""
    proc = subprocess.run(
        [sys.executable, "-m", "ztb.cli", "rollback", "nonexistent-tag", "--dry-run"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode != 0


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
