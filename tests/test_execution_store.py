from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from ztb.store.exec_io import (
    count_quarantined_rows,
    create_exec_run,
    ensure_audit_table,
    ensure_exec_tables,
    get_audit_log,
    get_exec_fills,
    get_exec_orders,
    get_exec_run,
    get_pnl_ledger,
    get_sufficient_sample_pnl_ledger,
    list_exec_runs,
    log_audit_event,
    quarantine_corrupt_ledger_rows,
    save_exec_error,
    save_exec_fill,
    save_exec_order,
    save_pnl_entry,
    save_position_snapshot,
    update_exec_order,
    update_exec_run_status,
    verify_audit_chain,
)
from ztb.store.results import connect


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
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
    assert "audit_log" in table_names
    assert "idempotency" not in table_names  # separate table


def test_schema_v6_columns_exist(conn: sqlite3.Connection) -> None:
    ensure_exec_tables(conn)
    for tbl in ("exec_orders", "exec_fills", "exec_positions_snapshots", "exec_pnl_ledger"):
        cols = conn.execute(f"PRAGMA table_info({tbl})").fetchall()
        col_names = [c["name"] for c in cols]
        assert "sufficient_sample" in col_names, f"{tbl} missing sufficient_sample"
        assert "sufficient_sample" in col_names, f"{tbl} missing sufficient_sample"
        assert "code_version" in col_names, f"{tbl} missing code_version"


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
    assert orders[0]["sufficient_sample"] == 1
    assert orders[0]["code_version"] is None


def test_save_exec_order_with_sufficient_sample_and_code_version(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    save_exec_order(
        conn,
        {
            "order_id": "oid1",
            "exec_run_id": "exec1",
            "order_link_id": "olid1",
            "symbol": "BTCUSDT",
            "side": "Sell",
            "order_type": "Limit",
            "price": 60000.0,
            "qty": 0.2,
            "status": "New",
            "created_at": "2026-01-01T00:00:00Z",
            "cum_exec_qty": 0.0,
            "cum_exec_value": 0.0,
            "cum_exec_fee": 0.0,
            "sufficient_sample": 0,
            "code_version": "0.7.0",
        },
    )
    orders = get_exec_orders(conn, "exec1")
    assert len(orders) == 1
    assert orders[0]["sufficient_sample"] == 0
    assert orders[0]["code_version"] == "0.7.0"


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
    assert fills[0]["sufficient_sample"] == 1
    assert fills[0]["code_version"] is None


def test_save_exec_fill_with_sufficient_sample(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec2", "run2", "s", "BTCUSDT", "60")
    save_exec_order(
        conn,
        {
            "order_id": "oid2",
            "exec_run_id": "exec2",
            "order_link_id": "olid2",
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
            "fill_id": "fill2",
            "order_link_id": "olid2",
            "order_id": "oid2",
            "exec_run_id": "exec2",
            "symbol": "BTCUSDT",
            "side": "Sell",
            "price": 51000.0,
            "qty": 0.1,
            "commission": 2.5,
            "realized_pnl": 100.0,
            "filled_at": "2026-01-01T00:00:05Z",
            "sufficient_sample": 0,
            "code_version": "0.7.0",
        },
    )
    fills = get_exec_fills(conn, "exec2")
    assert len(fills) == 1
    assert fills[0]["sufficient_sample"] == 0
    assert fills[0]["code_version"] == "0.7.0"


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
    assert rows[0]["sufficient_sample"] == 1
    assert rows[0]["code_version"] is None


def test_save_position_snapshot_with_sufficient_sample(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    save_position_snapshot(
        conn,
        {
            "exec_run_id": "exec1",
            "symbol": "BTCUSDT",
            "timestamp": "2026-01-01T00:01:00Z",
            "position": 1.0,
            "avg_price": 60000.0,
            "unrealized_pnl": 0.0,
            "sufficient_sample": 0,
            "code_version": "0.7.0",
        },
    )
    rows = conn.execute(
        "SELECT * FROM exec_positions_snapshots WHERE exec_run_id = ?", ("exec1",)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["sufficient_sample"] == 0
    assert rows[0]["code_version"] == "0.7.0"


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
    assert ledger[0]["sufficient_sample"] == 1
    assert ledger[0]["code_version"] is None


def test_save_pnl_entry_with_sufficient_sample(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec1", "run1", "s", "BTCUSDT", "60")
    save_pnl_entry(
        conn,
        {
            "exec_run_id": "exec1",
            "timestamp": "2026-01-01T00:00:00Z",
            "symbol": "BTCUSDT",
            "realized_pnl": -50.0,
            "unrealized_pnl": 25.0,
            "total_equity": 99975.0,
            "sufficient_sample": 0,
            "code_version": "0.7.0",
        },
    )
    ledger = get_pnl_ledger(conn, "exec1")
    assert len(ledger) == 1
    assert ledger[0]["sufficient_sample"] == 0
    assert ledger[0]["code_version"] == "0.7.0"


def test_get_sufficient_sample_pnl_ledger(conn: sqlite3.Connection) -> None:
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
            "sufficient_sample": 1,
        },
    )
    save_pnl_entry(
        conn,
        {
            "exec_run_id": "exec1",
            "timestamp": "2026-01-01T00:01:00Z",
            "symbol": "BTCUSDT",
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_equity": 5000.0,
            "sufficient_sample": 0,
            "code_version": "0.7.0",
        },
    )
    full = get_pnl_ledger(conn, "exec1")
    assert len(full) == 2
    sufficient_sample = get_sufficient_sample_pnl_ledger(conn, "exec1")
    assert len(sufficient_sample) == 1
    assert sufficient_sample[0]["realized_pnl"] == 10.0


def test_quarantine_corrupt_ledger_rows(conn: sqlite3.Connection) -> None:
    create_exec_run(conn, "exec_corrupt", "run_c", "s", "BTCUSDT", "60")
    save_pnl_entry(
        conn,
        {
            "exec_run_id": "exec_corrupt",
            "timestamp": "2026-01-01T00:00:00Z",
            "symbol": "BTCUSDT",
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_equity": 100_000.0,
        },
    )
    save_pnl_entry(
        conn,
        {
            "exec_run_id": "exec_corrupt",
            "timestamp": "2026-01-01T00:01:00Z",
            "symbol": "BTCUSDT",
            "realized_pnl": 0.0,
            "unrealized_pnl": 5.0,
            "total_equity": 100_005.0,
        },
    )
    save_pnl_entry(
        conn,
        {
            "exec_run_id": "exec_corrupt",
            "timestamp": "2026-01-01T00:02:00Z",
            "symbol": "BTCUSDT",
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "total_equity": 5000.0,
        },
    )
    save_pnl_entry(
        conn,
        {
            "exec_run_id": "exec_corrupt",
            "timestamp": "2026-01-01T00:03:00Z",
            "symbol": "BTCUSDT",
            "realized_pnl": -50.0,
            "unrealized_pnl": 25.0,
            "total_equity": 99975.0,
        },
    )
    count_before = count_quarantined_rows(conn)
    assert count_before == 0
    n = quarantine_corrupt_ledger_rows(conn, "exec_corrupt", initial_cash=100_000.0, threshold=0.01)
    assert n == 1
    assert count_quarantined_rows(conn) == 1


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


def test_ensure_audit_table(conn: sqlite3.Connection) -> None:
    ensure_audit_table(conn)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [r["name"] for r in tables]
    assert "audit_log" in table_names


def test_log_and_get_audit_event(conn: sqlite3.Connection) -> None:
    result = log_audit_event(
        conn,
        event_type="arm",
        source="preflight",
        detail="Live armed via signed token",
        timestamp="2026-06-12T10:00:00Z",
    )
    assert result["event_type"] == "arm"
    assert result["source"] == "preflight"
    assert result["detail"] == "Live armed via signed token"
    assert result["timestamp"] == "2026-06-12T10:00:00Z"
    assert result["prev_hash"] == ""
    assert len(result["content_hash"]) == 64

    events = get_audit_log(conn)
    assert len(events) == 1
    assert events[0]["event_type"] == "arm"


def test_audit_log_hash_chain(conn: sqlite3.Connection) -> None:
    e1 = log_audit_event(
        conn, event_type="arm", source="preflight", timestamp="2026-06-12T10:00:00Z"
    )
    e2 = log_audit_event(
        conn, event_type="kill", source="killswitch", timestamp="2026-06-12T10:01:00Z"
    )
    e3 = log_audit_event(
        conn, event_type="disarm", source="manual", timestamp="2026-06-12T10:02:00Z"
    )

    assert e1["prev_hash"] == ""
    assert e2["prev_hash"] == e1["content_hash"]
    assert e3["prev_hash"] == e2["content_hash"]

    violations = verify_audit_chain(conn)
    assert violations == []


def test_verify_audit_chain_detects_tamper(conn: sqlite3.Connection) -> None:
    log_audit_event(conn, event_type="arm", source="preflight", timestamp="2026-06-12T10:00:00Z")
    log_audit_event(conn, event_type="kill", source="killswitch", timestamp="2026-06-12T10:01:00Z")

    conn.execute("UPDATE audit_log SET detail = 'tampered' WHERE entry_id = 1")
    conn.commit()

    violations = verify_audit_chain(conn)
    assert len(violations) >= 1


def test_get_audit_log_ordering(conn: sqlite3.Connection) -> None:
    log_audit_event(conn, event_type="a", timestamp="2026-01-01T00:00:00Z")
    log_audit_event(conn, event_type="b", timestamp="2026-01-01T00:01:00Z")
    log_audit_event(conn, event_type="c", timestamp="2026-01-01T00:02:00Z")

    events = get_audit_log(conn, limit=2)
    assert len(events) == 2
    assert events[0]["event_type"] == "c"
    assert events[1]["event_type"] == "b"

    events_all = get_audit_log(conn, limit=10)
    assert len(events_all) == 3


def test_schema_meta_version_8(conn: sqlite3.Connection) -> None:
    ensure_audit_table(conn)
    row = conn.execute("SELECT version FROM schema_meta WHERE version = 8").fetchone()
    assert row is not None
    assert row["version"] == 8


def test_schema_meta_version_9(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT version FROM schema_meta WHERE version = 9").fetchone()
    assert row is not None
    assert row["version"] == 9
