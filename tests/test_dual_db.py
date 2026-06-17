from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ztb.engine.backtest import BacktestResult
from ztb.engine.metrics import MetricsResult
from ztb.engine.portfolio import PortfolioState
from ztb.store.exec_io import list_exec_runs
from ztb.store.results import (
    connect,
    connect_live,
    list_runs,
    save_run,
)


@pytest.fixture
def test_db(tmp_path: Path) -> str:
    return str(tmp_path / "test_results.db")


@pytest.fixture
def live_db(tmp_path: Path) -> str:
    return str(tmp_path / "live_results.db")


@pytest.fixture
def sample_result() -> BacktestResult:
    return BacktestResult(
        strategy_name="test_strat",
        symbol="BTCUSDT",
        timeframe="60",
        full=MetricsResult(
            total_return=0.15,
            sharpe=1.5,
            sortino=2.0,
            max_drawdown=-0.05,
            max_drawdown_duration=3,
            num_trades=50,
            profit_factor=2.0,
            win_rate=0.55,
            turnover=100.0,
            exposure_time=200.0,
            sufficient_sample=True,
        ),
        is_=MetricsResult(
            total_return=0.20,
            sharpe=2.0,
            sortino=2.5,
            max_drawdown=-0.03,
            max_drawdown_duration=2,
            num_trades=35,
            profit_factor=2.5,
            win_rate=0.60,
            turnover=70.0,
            exposure_time=140.0,
            sufficient_sample=True,
        ),
        oos=MetricsResult(
            total_return=0.10,
            sharpe=1.0,
            sortino=1.5,
            max_drawdown=-0.05,
            max_drawdown_duration=3,
            num_trades=15,
            profit_factor=1.5,
            win_rate=0.50,
            turnover=30.0,
            exposure_time=60.0,
            sufficient_sample=True,
        ),
        portfolio=PortfolioState(
            cash=50000.0,
            position=1.0,
            equity=[100000.0, 101000.0, 102000.0, 103000.0, 104000.0],
            timestamps=pd.date_range("2020-01-01", periods=5, freq="h").tolist(),
            trades=[
                {
                    "timestamp": pd.Timestamp("2020-01-01 01:00"),
                    "side": "buy",
                    "price": 100.0,
                    "size": 1.0,
                    "pnl": 0.0,
                    "commission": 0.05,
                    "slippage": 0.05,
                },
            ],
        ),
        trades=[
            {
                "timestamp": pd.Timestamp("2020-01-01 01:00"),
                "side": "buy",
                "price": 100.0,
                "size": 1.0,
                "pnl": 0.0,
                "commission": 0.05,
                "slippage": 0.05,
            },
        ],
        splits={"is_end": 70, "n_bars": 100},
        parameters={"fast": 10, "slow": 30},
    )


def test_connect_uses_test_db_by_default(test_db: str, live_db: str, monkeypatch) -> None:
    monkeypatch.setenv("ZTB_TEST_STORE_PATH", test_db)
    monkeypatch.setenv("ZTB_LIVE_STORE_PATH", live_db)
    conn = connect()
    db_file = conn.execute("PRAGMA database_list").fetchone()[2]
    assert db_file == test_db
    conn.close()


def test_connect_live_uses_live_db_by_default(test_db: str, live_db: str, monkeypatch) -> None:
    monkeypatch.setenv("ZTB_TEST_STORE_PATH", test_db)
    monkeypatch.setenv("ZTB_LIVE_STORE_PATH", live_db)
    conn = connect_live()
    db_file = conn.execute("PRAGMA database_list").fetchone()[2]
    assert db_file == live_db
    conn.close()


def test_connect_creates_all_tables(test_db: str) -> None:
    conn = connect(test_db)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "runs" in tables
    assert "metrics" in tables
    assert "trades" in tables
    assert "equity_curve" in tables
    assert "risk_decisions" in tables
    assert "schema_meta" in tables
    assert "exec_runs" in tables
    assert "exec_orders" in tables
    assert "exec_fills" in tables
    conn.close()


def test_connect_live_creates_all_tables(live_db: str) -> None:
    conn = connect_live(live_db)
    tables = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert "runs" in tables
    assert "metrics" in tables
    assert "exec_runs" in tables
    assert "exec_fills" in tables
    conn.close()


def test_test_db_has_no_exec_data_rows(
    test_db: str, live_db: str, sample_result, monkeypatch
) -> None:
    monkeypatch.setenv("ZTB_TEST_STORE_PATH", test_db)
    monkeypatch.setenv("ZTB_LIVE_STORE_PATH", live_db)
    test_conn = connect()
    save_run(test_conn, sample_result)
    test_conn.close()
    live_conn = connect_live()
    assert len(list_exec_runs(live_conn)) == 0
    live_conn.close()


def test_live_db_has_no_runs_data_rows(test_db: str, live_db: str, monkeypatch) -> None:
    monkeypatch.setenv("ZTB_TEST_STORE_PATH", test_db)
    monkeypatch.setenv("ZTB_LIVE_STORE_PATH", live_db)
    live_conn = connect_live()
    live_conn.execute(
        "INSERT INTO exec_runs (exec_run_id, run_id, strategy_name, symbol, "
        "timeframe, mode, started_at) "
        "VALUES ('er1', 'r1', 'strat', 'BTCUSDT', '60', 'demo', '2024-01-01')"
    )
    live_conn.commit()
    live_conn.close()
    test_conn = connect()
    assert len(list_runs(test_conn)) == 0
    test_conn.close()


def test_explicit_db_arg_overrides_default(test_db: str, live_db: str) -> None:
    explicit = str(Path(test_db).parent / "explicit.db")
    conn = connect(explicit)
    db_file = conn.execute("PRAGMA database_list").fetchone()[2]
    assert db_file == explicit
    conn.close()


def test_legacy_env_var_fallback(monkeypatch, tmp_path: Path) -> None:
    legacy = str(tmp_path / "legacy.db")
    monkeypatch.setenv("ZTB_STORE_PATH", legacy)
    test_conn = connect()
    assert test_conn.execute("PRAGMA database_list").fetchone()[2] == legacy
    test_conn.close()
    live_conn = connect_live()
    assert live_conn.execute("PRAGMA database_list").fetchone()[2] == legacy
    live_conn.close()


def test_dual_db_independence(test_db: str, live_db: str, sample_result, monkeypatch) -> None:
    monkeypatch.setenv("ZTB_TEST_STORE_PATH", test_db)
    monkeypatch.setenv("ZTB_LIVE_STORE_PATH", live_db)
    test_conn = connect()
    save_run(test_conn, sample_result)
    test_conn.close()
    live_conn = connect_live()
    assert len(list_runs(live_conn)) == 0
    live_conn.execute(
        "INSERT INTO exec_runs (exec_run_id, run_id, strategy_name, symbol, "
        "timeframe, mode, started_at) "
        "VALUES ('er2', 'r2', 'strat', 'ETHUSDT', '60', 'demo', '2024-01-01')"
    )
    live_conn.commit()
    live_conn.close()
    test_conn2 = connect()
    exec_runs_in_test = test_conn2.execute("SELECT COUNT(*) FROM exec_runs").fetchone()[0]
    assert exec_runs_in_test == 0
    test_conn2.close()
