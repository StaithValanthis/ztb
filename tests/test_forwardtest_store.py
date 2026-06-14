from __future__ import annotations

import json
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pandas as pd
import pytest

from ztb.engine.forwardtest import ForwardtestResult
from ztb.engine.metrics import MetricsResult
from ztb.engine.portfolio import PortfolioState
from ztb.store.results import (
    connect,
    get_equity_curve,
    get_metrics,
    get_run,
    get_trades,
    list_forward_runs,
    list_runs,
    save_forward_run,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_forward_results.db")


@pytest.fixture
def conn(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def sample_forward_result() -> ForwardtestResult:
    return ForwardtestResult(
        strategy_name="test_forward",
        symbol="BTCUSDT",
        timeframe="60",
        metrics=MetricsResult(
            total_return=0.05,
            sharpe=0.8,
            sortino=1.0,
            max_drawdown=-0.03,
            max_drawdown_duration=2,
            num_trades=10,
            profit_factor=1.2,
            win_rate=0.50,
            turnover=20.0,
            exposure_time=50.0,
            sufficient_sample=True,
        ),
        portfolio=PortfolioState(
            cash=95000.0,
            position=0.5,
            equity=[100000.0, 100500.0, 101000.0, 101500.0, 102000.0],
            timestamps=pd.date_range("2020-01-01", periods=5, freq="h").tolist(),
            trades=[
                {
                    "timestamp": pd.Timestamp("2020-01-01 01:00"),
                    "side": "buy",
                    "price": 100.0,
                    "size": 0.5,
                    "pnl": 0.0,
                    "commission": 0.025,
                    "slippage": 0.025,
                },
            ],
        ),
        trades=[
            {
                "timestamp": pd.Timestamp("2020-01-01 01:00"),
                "side": "buy",
                "price": 100.0,
                "size": 0.5,
                "pnl": 0.0,
                "commission": 0.025,
                "slippage": 0.025,
            },
        ],
        parameters={"fast": 5, "slow": 20},
        warmup_bars=50,
        total_bars=200,
    )


# FT-STORE-1: Round-trip forward run
def test_save_forward_run_round_trip(
    conn: sqlite3.Connection, sample_forward_result: ForwardtestResult
) -> None:
    run_id = save_forward_run(conn, sample_forward_result)
    retrieved = get_run(conn, run_id)
    assert retrieved is not None
    assert retrieved["strategy_name"] == "test_forward"
    assert retrieved["symbol"] == "BTCUSDT"
    assert retrieved["run_type"] == "forward"


# FT-STORE-2: Forward run has run_type='forward'
def test_forward_run_type(
    conn: sqlite3.Connection, sample_forward_result: ForwardtestResult
) -> None:
    run_id = save_forward_run(conn, sample_forward_result)
    retrieved = get_run(conn, run_id)
    assert retrieved is not None
    assert retrieved["run_type"] == "forward"


# FT-STORE-3: Forward run has exactly 1 metric scope
def test_forward_run_metric_scope(
    conn: sqlite3.Connection, sample_forward_result: ForwardtestResult
) -> None:
    run_id = save_forward_run(conn, sample_forward_result)
    metrics = get_metrics(conn, run_id)
    assert len(metrics) == 1


# FT-STORE-4: list_forward_runs returns only forward runs
def test_list_forward_runs(
    conn: sqlite3.Connection, sample_forward_result: ForwardtestResult
) -> None:
    assert list_forward_runs(conn) == []
    save_forward_run(conn, sample_forward_result)
    runs = list_forward_runs(conn)
    assert len(runs) == 1
    assert runs[0]["strategy_name"] == "test_forward"
    assert runs[0]["run_type"] == "forward"


# FT-STORE-5: list_runs includes all run types
def test_list_runs_includes_forward(
    conn: sqlite3.Connection, sample_forward_result: ForwardtestResult
) -> None:
    save_forward_run(conn, sample_forward_result)
    all_runs = list_runs(conn)
    assert len(all_runs) == 1
    assert all_runs[0]["run_type"] == "forward"


# FT-STORE-6: Forward run splits stores warmup info
def test_forward_run_splits(
    conn: sqlite3.Connection, sample_forward_result: ForwardtestResult
) -> None:
    run_id = save_forward_run(conn, sample_forward_result)
    retrieved = get_run(conn, run_id)
    assert retrieved is not None
    splits = json.loads(retrieved["splits"])
    assert splits["warmup_bars"] == 50
    assert splits["total_bars"] == 200


# FT-STORE-7: Forward run saves trades
def test_forward_run_trades(
    conn: sqlite3.Connection, sample_forward_result: ForwardtestResult
) -> None:
    run_id = save_forward_run(conn, sample_forward_result)
    trades = get_trades(conn, run_id)
    assert len(trades) == 1
    assert trades[0]["side"] == "buy"


# FT-STORE-8: Forward run saves equity curve
def test_forward_run_equity(
    conn: sqlite3.Connection, sample_forward_result: ForwardtestResult
) -> None:
    run_id = save_forward_run(conn, sample_forward_result)
    eq = get_equity_curve(conn, run_id)
    assert len(eq) == 5
    assert eq[0]["equity"] == 100000.0
    assert eq[-1]["equity"] == 102000.0


# FT-STORE-9: Migration adds run_type column
def test_migration_adds_run_type(tmp_path: Path) -> None:
    old_db = str(tmp_path / "old_schema.db")
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
            parameters TEXT NOT NULL DEFAULT '{}',
            splits TEXT NOT NULL DEFAULT '{}',
            code_version TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            sufficient_sample INTEGER NOT NULL DEFAULT 0
        );
        INSERT OR IGNORE INTO schema_meta (version) VALUES (1);
    """)
    conn.commit()
    conn.close()

    conn2 = connect(old_db)
    col_info = conn2.execute("PRAGMA table_info(runs)").fetchall()
    col_names = [c[1] for c in col_info]
    assert "run_type" in col_names, f"run_type column missing: {col_names}"
    conn2.close()
