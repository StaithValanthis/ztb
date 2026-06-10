from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ztb.store.exec_io import (
    create_exec_run,
    ensure_exec_tables,
    get_exec_fills,
    get_exec_orders,
    get_exec_run,
    get_pnl_ledger,
    list_exec_runs,
    save_exec_error,
    save_exec_fill,
    save_exec_order,
    save_pnl_entry,
    save_position_snapshot,
    update_exec_order,
    update_exec_run_status,
)
from ztb.store.results import connect


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db_path = str(tmp_path / "test_exec.db")
    c = connect(db_path)
    ensure_exec_tables(c)
    yield c
    c.close()


def test_ensure_exec_tables(conn: sqlite3.Connection) -> None:
    ensure_exec_tables(conn)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [r["name"] for r in tables]
    assert "exec_runs" in table_names
    assert "exec_orders" in table_names
    assert "exec_fills" in table_names
    assert "exec_positions_snapshots" in table_names
    assert "exec_pnl_ledger" in table_names
    assert "exec_errors" in table_names
    assert "idempotency" not in table_names  # separate table


def test_create_and_get_exec_run(conn: sqlite3.Connection) -> None:
    create_exec_run(
        conn,
        exec_run_id="exec1",
        run_id="run1",
        strategy_name="test_strat",
        symbol="BTCUSDT",
        timeframe="60",
        mode="demo",
        started_at="2026-01-01T00:00:00Z",
    )
    run = get_exec_run(conn, "exec1")
    assert run is not None
    assert run["strategy_name"] == "test_strat"
    assert run["status"] == "running"


def test_create_exec_run_idempotent(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")  # should not fail
    runs = list_exec_runs(conn)
    assert len(runs) == 1


def test_update_exec_run_status(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    update_exec_run_status(conn, "exec1", "completed", bars_processed=200)
    run = get_exec_run(conn, "exec1")
    assert run is not None
    assert run["status"] == "completed"
    assert run["bars_processed"] == 200


def test_list_exec_runs(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s1", "BTCUSDT", "60")
    create_exec_run(conn, "exec2", "run2", "s2", "ETHUSDT", "60")
    runs = list_exec_runs(conn)
    assert len(runs) == 2


def test_save_and_get_exec_order(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    save_exec_order(
        conn,
        {
            "order_id": "oid1",
            "exec_run_id": "exec1",
            "order_link_id": "olid1",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "order_type": "Market",
            "price": 50000.0,
            "qty": 0.1,
            "status": "Filled",
            "created_at": "2026-01-01T00:00:00Z",
            "cum_exec_qty": 0.1,
            "cum_exec_value": 5000.0,
            "cum_exec_fee": 2.5,
        },
    )
    orders = get_exec_orders(conn, "exec1")
    assert len(orders) == 1
    assert orders[0]["order_id"] == "oid1"
    assert orders[0]["side"] == "Buy"


def test_update_exec_order_status(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    save_exec_order(
        conn,
        {
            "order_id": "oid1",
            "exec_run_id": "exec1",
            "order_link_id": "olid1",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "order_type": "Market",
            "price": 50000.0,
            "qty": 0.1,
            "status": "New",
            "created_at": "",
            "cum_exec_qty": 0.0,
            "cum_exec_value": 0.0,
            "cum_exec_fee": 0.0,
        },
    )
    update_exec_order(conn, "olid1", "Cancelled")
    orders = get_exec_orders(conn, "exec1")
    assert orders[0]["status"] == "Cancelled"


def test_save_exec_fill(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    save_exec_order(
        conn,
        {
            "order_id": "oid1",
            "exec_run_id": "exec1",
            "order_link_id": "olid1",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "order_type": "Market",
            "price": 50000.0,
            "qty": 0.1,
            "status": "Filled",
            "created_at": "",
            "cum_exec_qty": 0.1,
            "cum_exec_value": 5000.0,
            "cum_exec_fee": 2.5,
        },
    )
    save_exec_fill(
        conn,
        {
            "fill_id": "fill1",
            "order_link_id": "olid1",
            "order_id": "oid1",
            "exec_run_id": "exec1",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "price": 50000.0,
            "qty": 0.1,
            "commission": 2.5,
            "realized_pnl": 0.0,
            "filled_at": "2026-01-01T00:00:05Z",
        },
    )
    fills = get_exec_fills(conn, "exec1")
    assert len(fills) == 1
    assert fills[0]["fill_id"] == "fill1"


def test_save_position_snapshot(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    save_position_snapshot(
        conn,
        {
            "exec_run_id": "exec1",
            "symbol": "BTCUSDT",
            "timestamp": "2026-01-01T00:00:00Z",
            "position": 0.5,
            "avg_price": 50000.0,
            "unrealized_pnl": 0.0,
        },
    )
    rows = conn.execute(
        "SELECT * FROM exec_positions_snapshots WHERE exec_run_id = ?", ("exec1",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["position"] == 0.5


def test_save_pnl_entry(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    save_pnl_entry(
        conn,
        {
            "exec_run_id": "exec1",
            "timestamp": "2026-01-01T00:00:00Z",
            "symbol": "BTCUSDT",
            "realized_pnl": 10.0,
            "unrealized_pnl": 5.0,
            "total_equity": 100015.0,
        },
    )
    ledger = get_pnl_ledger(conn, "exec1")
    assert len(ledger) == 1
    assert ledger[0]["realized_pnl"] == 10.0


def test_save_exec_error(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    save_exec_error(
        conn,
        {
            "exec_run_id": "exec1",
            "timestamp": "2026-01-01T00:00:00Z",
            "error_type": "client_error",
            "message": "timeout placing order",
        },
    )
    rows = conn.execute("SELECT * FROM exec_errors WHERE exec_run_id = ?", ("exec1",)).fetchall()
    assert len(rows) == 1
    assert rows[0]["error_type"] == "client_error"
