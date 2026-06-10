from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

import pandas as pd
import pytest

from ztb.engine.backtest import BacktestResult
from ztb.engine.metrics import MetricsResult
from ztb.engine.portfolio import PortfolioState
from ztb.store.results import (
    connect,
    get_risk_decisions,
    get_run,
    save_risk_decisions,
    save_run,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_risk_results.db")


@pytest.fixture
def conn(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def sample_result() -> BacktestResult:
    return BacktestResult(
        strategy_name="risk_test",
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
            credible=True,
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
            credible=True,
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
            credible=True,
        ),
        portfolio=PortfolioState(
            cash=50000.0,
            position=1.0,
            equity=[100000.0, 101000.0],
            timestamps=pd.date_range("2020-01-01", periods=2, freq="h").tolist(),
            trades=[],
        ),
        trades=[],
        splits={"is_end": 70, "n_bars": 100},
        risk_aware=True,
        risk_decisions=[
            {
                "timestamp": "2020-01-01 00:00",
                "symbol": "BTCUSDT",
                "action": "proceed",
                "reason": "",
                "max_pos_size": 0.0,
                "max_leverage": 3.0,
                "max_notional": 300000.0,
                "current_dd": 0.0,
                "current_heat": None,
                "hwm": 100000.0,
            },
        ],
        kill_count=0,
        mean_gross_leverage=1.5,
        max_portfolio_dd_realized=0.05,
    )


# RS-1: risk_decisions table exists
def test_risk_decisions_table_exists(conn: sqlite3.Connection) -> None:
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {t[0] for t in tables}
    assert "risk_decisions" in table_names


# RS-2: schema_meta has version 3
def test_schema_meta_version_3(conn: sqlite3.Connection) -> None:
    versions = conn.execute("SELECT version FROM schema_meta ORDER BY version").fetchall()
    v3 = {v[0] for v in versions}
    assert 3 in v3


# RS-3: runs table has risk columns
def test_runs_risk_columns(conn: sqlite3.Connection) -> None:
    col_info = conn.execute("PRAGMA table_info(runs)").fetchall()
    col_names = [c[1] for c in col_info]
    assert "risk_aware" in col_names
    assert "max_portfolio_dd_realized" in col_names
    assert "kill_count" in col_names
    assert "mean_gross_leverage" in col_names


# RS-4: Save run with risk data round-trips
def test_save_run_risk_data(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    run_id = save_run(conn, sample_result)
    retrieved = get_run(conn, run_id)
    assert retrieved is not None
    assert retrieved["risk_aware"] == "1"
    assert retrieved["max_portfolio_dd_realized"] == "0.05"
    assert retrieved["kill_count"] == "0"
    assert retrieved["mean_gross_leverage"] == "1.5"


# RS-5: Save run persists risk_decisions
def test_save_run_risk_decisions(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    run_id = save_run(conn, sample_result)
    decisions = get_risk_decisions(conn, run_id)
    assert len(decisions) == 1
    assert decisions[0]["action"] == "proceed"
    assert decisions[0]["current_dd"] == 0.0


# RS-6: save_risk_decisions directly
def test_save_risk_decisions_direct(conn: sqlite3.Connection) -> None:
    run_id = "test_direct_risk"
    conn.execute(
        """INSERT INTO runs (run_id, strategy_name, symbol, timeframe, run_type)
           VALUES (?, 'test', 'BTC', '60', 'backtest')""",
        (run_id,),
    )
    conn.commit()

    decisions = [
        {
            "timestamp": "2020-01-01 00:00",
            "symbol": "BTC",
            "action": "halt",
            "reason": "kill switch tripped",
            "max_pos_size": 0.0,
            "max_leverage": 0.0,
            "max_notional": 0.0,
            "current_dd": 0.3,
            "current_heat": None,
            "hwm": 100000.0,
        },
    ]
    save_risk_decisions(conn, run_id, decisions, risk_aware=True, kill_count=1)

    retrieved = get_run(conn, run_id)
    assert retrieved is not None
    assert retrieved["risk_aware"] == "1"
    assert retrieved["kill_count"] == "1"

    stored = get_risk_decisions(conn, run_id)
    assert len(stored) == 1
    assert stored[0]["action"] == "halt"
    assert stored[0]["reason"] == "kill switch tripped"


# RS-7: get_risk_decisions returns empty for run with none
def test_get_risk_decisions_empty(conn: sqlite3.Connection) -> None:
    run_id = "no_risk_run"
    conn.execute(
        """INSERT INTO runs (run_id, strategy_name, symbol, timeframe, run_type)
           VALUES (?, 'test', 'BTC', '60', 'backtest')""",
        (run_id,),
    )
    conn.commit()
    decisions = get_risk_decisions(conn, run_id)
    assert decisions == []


# RS-8: Migration adds risk columns to existing db
def test_risk_migration_from_v2(tmp_path: Path) -> None:
    old_db = str(tmp_path / "v2_schema.db")
    conn = sqlite3.connect(old_db)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS schema_meta (
            version INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            strategy_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            run_type TEXT NOT NULL DEFAULT 'backtest',
            parameters TEXT NOT NULL DEFAULT '{}',
            splits TEXT NOT NULL DEFAULT '{}',
            code_version TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            credible INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO schema_meta (version) VALUES (1);
        INSERT OR IGNORE INTO schema_meta (version) VALUES (2);
    """)
    conn.commit()
    conn.close()

    conn2 = connect(old_db)
    col_info = conn2.execute("PRAGMA table_info(runs)").fetchall()
    col_names = [c[1] for c in col_info]
    assert "risk_aware" in col_names
    assert "max_portfolio_dd_realized" in col_names
    assert "kill_count" in col_names
    assert "mean_gross_leverage" in col_names

    tables = conn2.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {t[0] for t in tables}
    assert "risk_decisions" in table_names

    versions = conn2.execute("SELECT version FROM schema_meta ORDER BY version").fetchall()
    assert 3 in {v[0] for v in versions}
    conn2.close()


# RS-9: Risk_decisions FK enforced
def test_risk_decisions_fk(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO risk_decisions
               (run_id, timestamp, symbol, action)
               VALUES ('nonexistent', '2020-01-01', 'BTC', 'proceed')"""
        )
        conn.commit()
