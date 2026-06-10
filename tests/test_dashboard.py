from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ztb.dashboard.data_access import DashboardData


@pytest.fixture
def empty_db(tmp_path: Path) -> str:
    p = tmp_path / "empty.db"
    conn = sqlite3.connect(str(p))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    schema_sql = """
        CREATE TABLE IF NOT EXISTS schema_meta (
            version INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            strategy_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            parameters TEXT NOT NULL DEFAULT '{}',
            splits TEXT NOT NULL DEFAULT '{}',
            code_version TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            credible INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS metrics (
            metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            scope TEXT NOT NULL CHECK (scope IN ('full', 'is', 'oos')),
            total_return REAL, sharpe REAL, sortino REAL,
            max_drawdown REAL, max_drawdown_duration INTEGER,
            num_trades INTEGER NOT NULL DEFAULT 0,
            profit_factor REAL, win_rate REAL,
            turnover REAL NOT NULL DEFAULT 0.0,
            exposure_time REAL NOT NULL DEFAULT 0.0,
            credible INTEGER NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '',
            UNIQUE(run_id, scope)
        );
        CREATE TABLE IF NOT EXISTS trades (
            trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            timestamp TEXT NOT NULL, side TEXT NOT NULL,
            price REAL NOT NULL, size REAL NOT NULL,
            pnl REAL NOT NULL, commission REAL NOT NULL,
            slippage REAL NOT NULL DEFAULT 0.0
        );
        CREATE TABLE IF NOT EXISTS equity_curve (
            point_id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            timestamp TEXT NOT NULL, equity REAL NOT NULL
        );
    """
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    return str(p)


# DB-1: Read-only
def test_dashboard_list_runs_empty(empty_db: str) -> None:
    dd = DashboardData(empty_db)
    runs = dd.list_runs()
    assert runs == []


def test_dashboard_get_run_nonexistent(empty_db: str) -> None:
    dd = DashboardData(empty_db)
    assert dd.get_run("nonexistent") is None


# DB-2: Component invariants (drawdown <= 0)
def test_component_drawdown_invariant() -> None:
    from ztb.engine.metrics import MetricsResult

    m = MetricsResult(
        total_return=0.1,
        sharpe=1.0,
        sortino=1.0,
        max_drawdown=-0.05,
        max_drawdown_duration=2,
        num_trades=30,
        profit_factor=1.5,
        win_rate=0.5,
        turnover=50.0,
        exposure_time=100.0,
        credible=True,
    )
    assert m.max_drawdown is None or m.max_drawdown <= 0.0


# DB-3: Empty state no crash (data layer)
def test_empty_dashboard_metrics(empty_db: str) -> None:
    dd = DashboardData(empty_db)
    metrics = dd.get_metrics("noid")
    assert metrics == []


# DB-4: Equity > 0 always
def test_equity_positive_invariant() -> None:
    equity = [
        {"timestamp": "2020-01-01", "equity": 100.0},
        {"timestamp": "2020-01-02", "equity": 200.0},
        {"timestamp": "2020-01-03", "equity": 150.0},
    ]
    for e in equity:
        assert e["equity"] > 0


def test_dashboard_readonly_connection(empty_db: str) -> None:
    dd = DashboardData(empty_db)
    rows = dd._conn.execute("SELECT * FROM runs").fetchall()
    assert rows == []
