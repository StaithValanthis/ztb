from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

from ztb.store.retry import retry_on_lock
from ztb.validation.walk_forward import WalkForwardResult


def _ensure_validation_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS validation_runs (
            run_id TEXT PRIMARY KEY,
            strategy TEXT NOT NULL,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            pass INTEGER NOT NULL,
            oos_sharpe REAL,
            deflated_sharpe REAL,
            dsr_significant INTEGER,
            lookahead_pass INTEGER,
            n_windows INTEGER,
            n_windows_credible INTEGER,
            stability REAL,
            parameters TEXT,
            sha TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS validation_windows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            window_idx INTEGER NOT NULL,
            train_start TEXT,
            train_end TEXT,
            oos_start TEXT,
            oos_end TEXT,
            sharpe REAL,
            total_return REAL,
            max_dd REAL,
            num_trades INTEGER,
            FOREIGN KEY (run_id) REFERENCES validation_runs(run_id)
        );
    """)
    conn.commit()


def _generate_run_id(strategy: str, symbol: str) -> str:
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"val_{strategy}_{symbol}_{now}"


@retry_on_lock()
def save_validation_run(
    conn: sqlite3.Connection,
    strategy: str,
    symbol: str,
    timeframe: str,
    overall_pass: bool,
    wf_result: WalkForwardResult,
    dsr: float,
    dsr_significant: bool,
    lookahead_pass: bool,
    sha: str | None = None,
) -> str:
    _ensure_validation_tables(conn)

    run_id = _generate_run_id(strategy, symbol)

    conn.execute("BEGIN")
    try:
        agg = wf_result.aggregate
        conn.execute(
            """INSERT INTO validation_runs
               (run_id, strategy, symbol, timeframe, pass,
                oos_sharpe, deflated_sharpe, dsr_significant,
                lookahead_pass, n_windows, n_windows_credible,
                stability, parameters, sha)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                strategy,
                symbol,
                timeframe,
                1 if overall_pass else 0,
                agg.sharpe,
                dsr,
                1 if dsr_significant else 0,
                1 if lookahead_pass else 0,
                wf_result.n_windows_total,
                wf_result.n_windows_credible,
                wf_result.stability,
                "{}",
                sha or "",
            ),
        )

        for idx, w in enumerate(wf_result.per_window):
            conn.execute(
                """INSERT INTO validation_windows
                   (run_id, window_idx, sharpe, total_return, max_dd, num_trades)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    idx,
                    w.sharpe,
                    w.total_return,
                    w.max_drawdown,
                    w.num_trades,
                ),
            )

        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    return run_id


def get_validation_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    _ensure_validation_tables(conn)
    row = conn.execute("SELECT * FROM validation_runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None

    result = dict(row)
    windows = conn.execute(
        "SELECT * FROM validation_windows WHERE run_id = ? ORDER BY window_idx",
        (run_id,),
    ).fetchall()
    result["windows"] = [dict(w) for w in windows]
    return result
