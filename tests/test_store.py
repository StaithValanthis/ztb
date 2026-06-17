from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from ztb.engine.backtest import BacktestResult
from ztb.engine.metrics import MetricsResult
from ztb.engine.portfolio import PortfolioState
from ztb.store.results import (
    best_runs,
    connect,
    get_equity_curve,
    get_metrics,
    get_oos_metric,
    get_oos_sharpe,
    get_run,
    get_trades,
    latest_run,
    list_runs,
    save_run,
)


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "test_results.db")


@pytest.fixture
def conn(db_path: str) -> sqlite3.Connection:
    c = connect(db_path)
    yield c
    c.close()


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


# ST-1: Round-trip
def test_save_run_round_trip(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    run_id = save_run(conn, sample_result)
    retrieved = get_run(conn, run_id)
    assert retrieved is not None
    assert retrieved["strategy_name"] == "test_strat"
    assert retrieved["symbol"] == "BTCUSDT"
    assert retrieved["timeframe"] == "60"
    params = json.loads(retrieved["parameters"])
    assert params == {"fast": 10, "slow": 30}


# ST-2: Atomicity — injected failure rolls back
def test_save_run_atomicity(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    orig = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    try:
        conn.execute("INSERT INTO metrics (run_id, scope, num_trades) VALUES ('bad', 'full', 0)")
        conn.commit()
    except Exception:
        conn.rollback()
    after = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert after == orig, "orphan row after failed save"


# ST-3: FK enforcement
def test_fk_enforcement(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO metrics (run_id, scope, num_trades) VALUES ('nonexistent', 'full', 0)",
        )
        conn.commit()


# ST-4: Exactly 3 scopes per run
def test_three_scopes(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    run_id = save_run(conn, sample_result)
    metrics = get_metrics(conn, run_id)
    scopes = {m["scope"] for m in metrics}
    assert scopes == {"full", "is", "oos"}
    assert len(metrics) == 3


# ST-5: Leaderboard
def test_best_runs(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    save_run(conn, sample_result)
    top = best_runs(conn, metric="sharpe", scope="oos", limit=5)
    assert len(top) >= 1
    assert top[0]["strategy_name"] == "test_strat"
    assert "metric_value" in top[0]


# ST-6: Determinism
def test_determinism(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    r1 = save_run(conn, sample_result)
    m1 = get_metrics(conn, r1)
    r2 = save_run(conn, sample_result)
    m2 = get_metrics(conn, r2)
    for i in range(3):
        assert m1[i]["sharpe"] == m2[i]["sharpe"]
        assert m1[i]["total_return"] == m2[i]["total_return"]
        assert m1[i]["num_trades"] == m2[i]["num_trades"]


# ST-7: get_oos_metric named accessor
def test_get_oos_metric(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    run_id = save_run(conn, sample_result)
    assert get_oos_metric(conn, run_id, "sharpe") == 1.0
    assert get_oos_metric(conn, run_id, "total_return") == 0.10
    assert get_oos_metric(conn, run_id, "nonexistent") is None


def test_get_oos_sharpe(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    run_id = save_run(conn, sample_result)
    assert get_oos_sharpe(conn, run_id) == 1.0


# ST-8: Idempotent init
def test_idempotent_init(conn: sqlite3.Connection) -> None:
    conn2 = connect(conn.execute("PRAGMA database_list").fetchone()[2])
    conn2.close()
    conn3 = connect(conn.execute("PRAGMA database_list").fetchone()[2])
    conn3.close()


def test_list_runs(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    assert list_runs(conn) == []
    save_run(conn, sample_result)
    runs = list_runs(conn)
    assert len(runs) == 1
    assert runs[0]["strategy_name"] == "test_strat"


def test_latest_run(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    assert latest_run(conn) is None
    save_run(conn, sample_result)
    lr = latest_run(conn)
    assert lr is not None
    assert lr["strategy_name"] == "test_strat"


def test_get_trades(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    run_id = save_run(conn, sample_result)
    trades = get_trades(conn, run_id)
    assert len(trades) == 1
    assert trades[0]["side"] == "buy"


def test_trades_sl_tp_columns_exist(
    conn: sqlite3.Connection, sample_result: BacktestResult
) -> None:
    cols = [c[1] for c in conn.execute("PRAGMA table_info(trades)").fetchall()]
    assert "sl_price" in cols
    assert "tp_price" in cols
    assert "exit_reason" in cols


def test_trades_sl_tp_columns_nullable(
    conn: sqlite3.Connection, sample_result: BacktestResult
) -> None:
    run_id = save_run(conn, sample_result)
    trades = get_trades(conn, run_id)
    assert trades[0]["sl_price"] is None
    assert trades[0]["tp_price"] is None
    assert trades[0]["exit_reason"] is None


def test_get_equity_curve(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    run_id = save_run(conn, sample_result)
    eq = get_equity_curve(conn, run_id)
    assert len(eq) == 5
    assert eq[0]["equity"] == 100000.0
    assert eq[-1]["equity"] == 104000.0


# ST-9: ZTB_STORE_PATH env var
def test_store_path_env_var(monkeypatch, tmp_path) -> None:
    import os

    from ztb.store.results import connect, list_runs

    db_path = str(tmp_path / "env_test.db")
    monkeypatch.setenv("ZTB_STORE_PATH", db_path)
    conn = connect()
    assert list_runs(conn) == []
    conn.close()
    assert os.path.exists(db_path)


# ST-10: get_run returns None for missing run
def test_get_run_missing(conn: sqlite3.Connection) -> None:
    assert get_run(conn, "nonexistent") is None


# ST-11: get_oos_metric returns None for missing run
def test_get_oos_metric_missing(conn: sqlite3.Connection) -> None:
    assert get_oos_metric(conn, "nonexistent", "sharpe") is None


# ST-12: best_runs with invalid scope/metric defaults
def test_best_runs_invalid_args(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    save_run(conn, sample_result)
    result = best_runs(conn, metric="invalid_metric", scope="bad_scope", limit=5)
    assert len(result) >= 1
    assert "metric_value" in result[0]


# ST-13: save_run atomicity — rollback on failure
def test_save_run_rollback(conn: sqlite3.Connection, sample_result: BacktestResult) -> None:
    from contextlib import suppress

    orig_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    with suppress(Exception):
        conn.execute("DROP TABLE equity_curve")
    with suppress(Exception):
        save_run(conn, sample_result)
    final_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert final_count == orig_count, "rollback should keep run count unchanged"
