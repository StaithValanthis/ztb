from __future__ import annotations

import hashlib
import sqlite3
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any


def make_order_link_id(
    strategy: str,
    symbol: str,
    bar_ts: str,
    intent_hash: str,
) -> str:
    raw = f"{strategy}:{symbol}:{bar_ts}:{intent_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def make_intent_hash(signal: float, current_position: float) -> str:
    raw = f"sig={signal:.8f}:pos={current_position:.8f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class IdempotencyLedger:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        _ensure_idempotency_table(conn)

    def try_claim(self, order_link_id: str, order_id: str = "") -> bool:
        try:
            self.conn.execute(
                """INSERT INTO idempotency (order_link_id, order_id, status, created_at)
                   VALUES (?, ?, 'pending', ?)""",
                (order_link_id, order_id, _now()),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            self.conn.rollback()
            return False

    def resolve(self, order_link_id: str, status: str, order_id: str = "") -> None:
        with suppress(BaseException):
            self.conn.execute(
                """UPDATE idempotency SET status = ?, order_id = ?
                   WHERE order_link_id = ?""",
                (status, order_id, order_link_id),
            )
            self.conn.commit()

    def get(self, order_link_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM idempotency WHERE order_link_id = ?", (order_link_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def lookup_order(self, order_link_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT order_id FROM idempotency"
            " WHERE order_link_id = ? AND status IN ('placed', 'filled')",
            (order_link_id,),
        ).fetchone()
        if row is None:
            return None
        val = row["order_id"]
        return str(val) if val else None

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS cnt FROM idempotency").fetchone()
        return row["cnt"] if row else 0

    def clear_stale(self, ttl_hours: int = 24) -> int:
        cutoff = datetime.now(UTC) - timedelta(hours=ttl_hours)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        deleted = self.conn.execute(
            "DELETE FROM idempotency WHERE status IN ('placed', 'filled') AND created_at < ?",
            (cutoff_str,),
        )
        self.conn.commit()
        return deleted.rowcount

    def clear_pending(self) -> int:
        deleted = self.conn.execute(
            "DELETE FROM idempotency WHERE status = 'pending'"
        )
        self.conn.commit()
        return deleted.rowcount


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_idempotency_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS idempotency (
            idempotency_id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_link_id TEXT NOT NULL UNIQUE,
            order_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        )"""
    )
    with suppress(sqlite3.OperationalError):
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_idempotency_link
               ON idempotency(order_link_id)"""
        )
    with suppress(sqlite3.OperationalError):
        conn.execute(
            """CREATE INDEX IF NOT EXISTS idx_idempotency_stale
               ON idempotency(status, created_at)"""
        )
    conn.commit()
