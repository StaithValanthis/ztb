from __future__ import annotations

import sqlite3
from contextlib import suppress
from typing import Any


def ensure_exec_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS exec_runs (
            exec_run_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            strategy_name TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'demo',
            started_at TEXT NOT NULL,
            bars_processed INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'running'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS exec_orders (
            order_id TEXT PRIMARY KEY,
            exec_run_id TEXT NOT NULL REFERENCES exec_runs(exec_run_id),
            order_link_id TEXT NOT NULL DEFAULT '',
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            price REAL NOT NULL DEFAULT 0.0,
            qty REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'Created',
            created_at TEXT NOT NULL,
            cum_exec_qty REAL NOT NULL DEFAULT 0.0,
            cum_exec_value REAL NOT NULL DEFAULT 0.0,
            cum_exec_fee REAL NOT NULL DEFAULT 0.0
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS exec_fills (
            fill_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES exec_orders(order_id),
            exec_run_id TEXT NOT NULL REFERENCES exec_runs(exec_run_id),
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            price REAL NOT NULL,
            qty REAL NOT NULL,
            commission REAL NOT NULL DEFAULT 0.0,
            realized_pnl REAL NOT NULL DEFAULT 0.0,
            filled_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS exec_positions_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            exec_run_id TEXT NOT NULL REFERENCES exec_runs(exec_run_id),
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            position REAL NOT NULL,
            avg_price REAL NOT NULL DEFAULT 0.0,
            unrealized_pnl REAL NOT NULL DEFAULT 0.0
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS exec_pnl_ledger (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            exec_run_id TEXT NOT NULL REFERENCES exec_runs(exec_run_id),
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            realized_pnl REAL NOT NULL DEFAULT 0.0,
            unrealized_pnl REAL NOT NULL DEFAULT 0.0,
            total_equity REAL NOT NULL DEFAULT 0.0
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS exec_errors (
            error_id INTEGER PRIMARY KEY AUTOINCREMENT,
            exec_run_id TEXT NOT NULL REFERENCES exec_runs(exec_run_id),
            timestamp TEXT NOT NULL,
            error_type TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT ''
        )"""
    )
    with suppress(sqlite3.OperationalError):
        conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (4)")
    conn.commit()


def create_exec_run(
    conn: sqlite3.Connection,
    exec_run_id: str,
    run_id: str,
    strategy_name: str,
    symbol: str,
    timeframe: str,
    mode: str = "demo",
    started_at: str = "",
) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO exec_runs
           (exec_run_id, run_id, strategy_name, symbol, timeframe, mode, started_at, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'running')""",
        (exec_run_id, run_id, strategy_name, symbol, timeframe, mode, started_at),
    )
    conn.commit()


def update_exec_run_status(
    conn: sqlite3.Connection,
    exec_run_id: str,
    status: str,
    bars_processed: int = 0,
) -> None:
    conn.execute(
        "UPDATE exec_runs SET status = ?, bars_processed = ? WHERE exec_run_id = ?",
        (status, bars_processed, exec_run_id),
    )
    conn.commit()


def save_exec_order(conn: sqlite3.Connection, order: dict[str, Any]) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO exec_orders
           (order_id, exec_run_id, order_link_id, symbol, side, order_type,
            price, qty, status, created_at, cum_exec_qty, cum_exec_value, cum_exec_fee)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            order["order_id"],
            order["exec_run_id"],
            order.get("order_link_id", ""),
            order["symbol"],
            order["side"],
            order["order_type"],
            order.get("price", 0.0),
            order.get("qty", 0.0),
            order.get("status", "Created"),
            order.get("created_at", ""),
            order.get("cum_exec_qty", 0.0),
            order.get("cum_exec_value", 0.0),
            order.get("cum_exec_fee", 0.0),
        ),
    )
    conn.commit()


def update_exec_order(conn: sqlite3.Connection, order_id: str, status: str, **kwargs: Any) -> None:
    fields = ["status = ?"]
    values: list[Any] = [status]
    for key, val in kwargs.items():
        if key in ("cum_exec_qty", "cum_exec_value", "cum_exec_fee", "price", "qty"):
            fields.append(f"{key} = ?")
            values.append(val)
    values.append(order_id)
    conn.execute(f"UPDATE exec_orders SET {', '.join(fields)} WHERE order_id = ?", tuple(values))
    conn.commit()


def save_exec_fill(conn: sqlite3.Connection, fill: dict[str, Any]) -> None:
    conn.execute(
        """INSERT OR IGNORE INTO exec_fills
           (fill_id, order_id, exec_run_id, symbol, side,
            price, qty, commission, realized_pnl, filled_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fill["fill_id"],
            fill["order_id"],
            fill["exec_run_id"],
            fill["symbol"],
            fill["side"],
            fill["price"],
            fill["qty"],
            fill.get("commission", 0.0),
            fill.get("realized_pnl", 0.0),
            fill.get("filled_at", ""),
        ),
    )
    conn.commit()


def save_position_snapshot(conn: sqlite3.Connection, snap: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO exec_positions_snapshots
           (exec_run_id, symbol, timestamp, position, avg_price, unrealized_pnl)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            snap["exec_run_id"],
            snap["symbol"],
            snap["timestamp"],
            snap["position"],
            snap.get("avg_price", 0.0),
            snap.get("unrealized_pnl", 0.0),
        ),
    )
    conn.commit()


def save_pnl_entry(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO exec_pnl_ledger
           (exec_run_id, timestamp, symbol, realized_pnl, unrealized_pnl, total_equity)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            entry["exec_run_id"],
            entry["timestamp"],
            entry["symbol"],
            entry.get("realized_pnl", 0.0),
            entry.get("unrealized_pnl", 0.0),
            entry.get("total_equity", 0.0),
        ),
    )
    conn.commit()


def save_exec_error(conn: sqlite3.Connection, error: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO exec_errors
           (exec_run_id, timestamp, error_type, message)
           VALUES (?, ?, ?, ?)""",
        (
            error["exec_run_id"],
            error["timestamp"],
            error.get("error_type", "unknown"),
            error.get("message", ""),
        ),
    )
    conn.commit()


def get_exec_run(conn: sqlite3.Connection, exec_run_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM exec_runs WHERE exec_run_id = ?", (exec_run_id,)).fetchone()
    return dict(row) if row else None


def list_exec_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM exec_runs ORDER BY started_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_exec_orders(conn: sqlite3.Connection, exec_run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM exec_orders WHERE exec_run_id = ? ORDER BY created_at", (exec_run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_exec_fills(conn: sqlite3.Connection, exec_run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM exec_fills WHERE exec_run_id = ? ORDER BY filled_at", (exec_run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_pnl_ledger(conn: sqlite3.Connection, exec_run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM exec_pnl_ledger WHERE exec_run_id = ? ORDER BY entry_id", (exec_run_id,)
    ).fetchall()
    return [dict(r) for r in rows]
