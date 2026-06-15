from __future__ import annotations

import hashlib
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
            order_link_id TEXT PRIMARY KEY,
            exec_run_id TEXT NOT NULL REFERENCES exec_runs(exec_run_id),
            order_id TEXT NOT NULL DEFAULT '',
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
            order_link_id TEXT NOT NULL,
            exec_run_id TEXT NOT NULL REFERENCES exec_runs(exec_run_id),
            order_id TEXT NOT NULL DEFAULT '',
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
    conn.execute(
        """CREATE TABLE IF NOT EXISTS kill_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            exec_run_id TEXT NOT NULL REFERENCES exec_runs(exec_run_id),
            source TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            value REAL NOT NULL DEFAULT 0.0,
            threshold REAL NOT NULL DEFAULT 0.0,
            timestamp TEXT NOT NULL
        )"""
    )
    with suppress(sqlite3.OperationalError):
        conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (4)")
    with suppress(sqlite3.OperationalError):
        conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (5)")

    # Schema v6: add credible and code_version columns to all four exec tables
    for tbl in ("exec_orders", "exec_fills", "exec_positions_snapshots", "exec_pnl_ledger"):
        with suppress(sqlite3.OperationalError):
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN credible INTEGER NOT NULL DEFAULT 1")
        with suppress(sqlite3.OperationalError):
            conn.execute(f"ALTER TABLE {tbl} ADD COLUMN code_version TEXT DEFAULT NULL")
    # Schema v9: add sufficient_sample columns alongside credible (migration)
    for tbl in ("exec_orders", "exec_fills", "exec_positions_snapshots", "exec_pnl_ledger"):
        with suppress(sqlite3.OperationalError):
            conn.execute(
                f"ALTER TABLE {tbl} ADD COLUMN sufficient_sample INTEGER NOT NULL DEFAULT 1"
            )
        with suppress(sqlite3.OperationalError):
            conn.execute(
                f"UPDATE {tbl} SET sufficient_sample = credible WHERE credible IS NOT NULL"
            )
    with suppress(sqlite3.OperationalError):
        conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (9)")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS killswitch_state (
            exec_run_id TEXT PRIMARY KEY,
            tripped INTEGER NOT NULL DEFAULT 0,
            hwm_equity REAL NOT NULL DEFAULT 0.0,
            last_heartbeat REAL NOT NULL DEFAULT 0.0,
            updated_at TEXT NOT NULL
        )"""
    )
    with suppress(sqlite3.OperationalError):
        conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (6)")
    with suppress(sqlite3.OperationalError):
        conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (7)")
    # Schema v10: remove FK from exec_fills.order_link_id
    existing_v10 = conn.execute(
        "SELECT 1 FROM schema_meta WHERE version = 10"
    ).fetchone()
    if existing_v10 is None:
        with suppress(sqlite3.OperationalError):
            conn.execute("DROP TABLE IF EXISTS exec_fills_v10")
        conn.execute(
            """CREATE TABLE exec_fills_v10 (
                fill_id TEXT PRIMARY KEY,
                order_link_id TEXT NOT NULL,
                exec_run_id TEXT NOT NULL REFERENCES exec_runs(exec_run_id),
                order_id TEXT NOT NULL DEFAULT '',
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                price REAL NOT NULL,
                qty REAL NOT NULL,
                commission REAL NOT NULL DEFAULT 0.0,
                realized_pnl REAL NOT NULL DEFAULT 0.0,
                filled_at TEXT NOT NULL,
                credible INTEGER NOT NULL DEFAULT 1,
                sufficient_sample INTEGER NOT NULL DEFAULT 1,
                code_version TEXT DEFAULT NULL
            )"""
        )
        conn.execute("INSERT INTO exec_fills_v10 SELECT * FROM exec_fills")
        conn.execute("DROP TABLE exec_fills")
        conn.execute("ALTER TABLE exec_fills_v10 RENAME TO exec_fills")
        with suppress(sqlite3.OperationalError):
            conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (10)")
    ensure_audit_table(conn)
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
           (order_link_id, exec_run_id, order_id, symbol, side, order_type,
            price, qty, status, created_at, cum_exec_qty, cum_exec_value, cum_exec_fee,
            sufficient_sample, code_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            order["order_link_id"],
            order["exec_run_id"],
            order.get("order_id", ""),
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
            order.get("sufficient_sample", 1),
            order.get("code_version"),
        ),
    )
    conn.commit()


def update_exec_order(
    conn: sqlite3.Connection, order_link_id: str, status: str, **kwargs: Any
) -> None:
    fields = ["status = ?"]
    values: list[Any] = [status]
    for key, val in kwargs.items():
        if key in ("cum_exec_qty", "cum_exec_value", "cum_exec_fee", "price", "qty"):
            fields.append(f"{key} = ?")
            values.append(val)
    values.append(order_link_id)
    conn.execute(
        f"UPDATE exec_orders SET {', '.join(fields)} WHERE order_link_id = ?",
        tuple(values),
    )
    conn.commit()


def save_exec_fill(conn: sqlite3.Connection, fill: dict[str, Any]) -> None:
    order_link_id = fill.get("order_link_id", "")
    conn.execute(
        """INSERT OR IGNORE INTO exec_fills
           (fill_id, order_link_id, exec_run_id, order_id, symbol, side,
            price, qty, commission, realized_pnl, filled_at,
            sufficient_sample, code_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fill["fill_id"],
            order_link_id,
            fill["exec_run_id"],
            fill.get("order_id", ""),
            fill["symbol"],
            fill["side"],
            fill["price"],
            fill["qty"],
            fill.get("commission", 0.0),
            fill.get("realized_pnl", 0.0),
            fill.get("filled_at", ""),
            fill.get("sufficient_sample", 1),
            fill.get("code_version"),
        ),
    )
    conn.commit()


def save_position_snapshot(conn: sqlite3.Connection, snap: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO exec_positions_snapshots
           (exec_run_id, symbol, timestamp, position, avg_price, unrealized_pnl,
            sufficient_sample, code_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            snap["exec_run_id"],
            snap["symbol"],
            snap["timestamp"],
            snap["position"],
            snap.get("avg_price", 0.0),
            snap.get("unrealized_pnl", 0.0),
            snap.get("sufficient_sample", 1),
            snap.get("code_version"),
        ),
    )
    conn.commit()


def save_pnl_entry(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO exec_pnl_ledger
           (exec_run_id, timestamp, symbol, realized_pnl, unrealized_pnl, total_equity,
            sufficient_sample, code_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry["exec_run_id"],
            entry["timestamp"],
            entry["symbol"],
            entry.get("realized_pnl", 0.0),
            entry.get("unrealized_pnl", 0.0),
            entry.get("total_equity", 0.0),
            entry.get("sufficient_sample", 1),
            entry.get("code_version"),
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


def save_kill_event(conn: sqlite3.Connection, event: dict[str, Any]) -> None:
    conn.execute(
        """INSERT INTO kill_events
           (exec_run_id, source, reason, value, threshold, timestamp)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            event["exec_run_id"],
            event.get("source", ""),
            event.get("reason", ""),
            event.get("value", 0.0),
            event.get("threshold", 0.0),
            event.get("timestamp", ""),
        ),
    )
    conn.commit()


def get_kill_events(conn: sqlite3.Connection, exec_run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM kill_events WHERE exec_run_id = ? ORDER BY event_id", (exec_run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_sufficient_sample_pnl_ledger(
    conn: sqlite3.Connection, exec_run_id: str
) -> list[dict[str, Any]]:
    sql = (
        "SELECT * FROM exec_pnl_ledger"
        " WHERE exec_run_id = ? AND sufficient_sample = 1 ORDER BY entry_id"
    )
    rows = conn.execute(sql, (exec_run_id,)).fetchall()
    return [dict(r) for r in rows]


def quarantine_corrupt_ledger_rows(
    conn: sqlite3.Connection,
    exec_run_id: str,
    initial_cash: float = 100_000.0,
    threshold: float = 0.01,
) -> int:
    rows = conn.execute(
        """SELECT entry_id, realized_pnl, unrealized_pnl, total_equity
           FROM exec_pnl_ledger WHERE exec_run_id = ?""",
        (exec_run_id,),
    ).fetchall()
    corrupt_ids: list[int] = []
    for r in rows:
        expected = initial_cash + r["realized_pnl"] + r["unrealized_pnl"]
        if abs(r["total_equity"] - expected) > threshold:
            corrupt_ids.append(r["entry_id"])
    if corrupt_ids:
        placeholders = ",".join("?" for _ in corrupt_ids)
        sql = (
            "UPDATE exec_pnl_ledger SET sufficient_sample = 0, credible = 0, code_version = '0.7.0'"
            f" WHERE entry_id IN ({placeholders})"
        )
        conn.execute(sql, corrupt_ids)
        conn.commit()
    return len(corrupt_ids)


def count_quarantined_rows(conn: sqlite3.Connection) -> int:
    sql = "SELECT COUNT(*) AS cnt FROM exec_pnl_ledger WHERE sufficient_sample = 0"
    row = conn.execute(sql).fetchone()
    return row["cnt"] if row else 0


def save_killswitch_state(
    conn: sqlite3.Connection,
    exec_run_id: str,
    tripped: bool,
    hwm_equity: float,
    last_heartbeat: float,
) -> None:
    from datetime import UTC, datetime

    conn.execute(
        """INSERT OR REPLACE INTO killswitch_state
           (exec_run_id, tripped, hwm_equity, last_heartbeat, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            exec_run_id,
            1 if tripped else 0,
            hwm_equity,
            last_heartbeat,
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    conn.commit()


def load_killswitch_state(conn: sqlite3.Connection, exec_run_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM killswitch_state WHERE exec_run_id = ?", (exec_run_id,)
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["tripped"] = bool(d["tripped"])
    return d


def get_latest_unresolved_kill_event(conn: sqlite3.Connection) -> dict[str, Any] | None:
    rows = conn.execute(
        """SELECT ke.* FROM kill_events ke
           WHERE ke.exec_run_id NOT IN (
               SELECT exec_run_id FROM kill_events WHERE source = 'manual_reset'
           )
           ORDER BY ke.event_id DESC LIMIT 1"""
    ).fetchall()
    return dict(rows[0]) if rows else None


def ensure_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS audit_log (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            detail TEXT NOT NULL DEFAULT '',
            prev_hash TEXT NOT NULL DEFAULT '',
            content_hash TEXT NOT NULL
        )"""
    )
    with suppress(sqlite3.OperationalError):
        conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (8)")


def _compute_content_hash(
    timestamp: str,
    event_type: str,
    source: str,
    detail: str,
    prev_hash: str,
) -> str:
    raw = f"{timestamp}|{event_type}|{source}|{detail}|{prev_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def log_audit_event(
    conn: sqlite3.Connection,
    event_type: str,
    source: str = "",
    detail: str = "",
    timestamp: str = "",
) -> dict[str, Any]:
    from datetime import UTC, datetime

    ts = timestamp or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    row = conn.execute(
        "SELECT content_hash FROM audit_log ORDER BY entry_id DESC LIMIT 1"
    ).fetchone()
    prev_hash = row["content_hash"] if row else ""
    content_hash = _compute_content_hash(ts, event_type, source, detail, prev_hash)
    conn.execute(
        """INSERT INTO audit_log (timestamp, event_type, source, detail, prev_hash, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (ts, event_type, source, detail, prev_hash, content_hash),
    )
    conn.commit()
    return {
        "timestamp": ts,
        "event_type": event_type,
        "source": source,
        "detail": detail,
        "prev_hash": prev_hash,
        "content_hash": content_hash,
    }


def get_audit_log(
    conn: sqlite3.Connection,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY entry_id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def verify_audit_chain(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM audit_log ORDER BY entry_id ASC").fetchall()
    violations: list[dict[str, Any]] = []
    expected_prev = ""
    for row in rows:
        r = dict(row)
        expected_hash = _compute_content_hash(
            r["timestamp"],
            r["event_type"],
            r["source"],
            r["detail"],
            expected_prev,
        )
        if r["content_hash"] != expected_hash:
            violations.append(
                {
                    "entry_id": r["entry_id"],
                    "expected": expected_hash,
                    "actual": r["content_hash"],
                }
            )
        expected_prev = r["content_hash"]
    return violations
