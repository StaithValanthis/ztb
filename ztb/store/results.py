from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ztb.engine.backtest import BacktestResult

_METRIC_NAMES = frozenset(
    {
        "total_return",
        "sharpe",
        "sortino",
        "max_drawdown",
        "max_drawdown_duration",
        "num_trades",
        "profit_factor",
        "win_rate",
        "turnover",
        "exposure_time",
    }
)

DEFAULT_DB_PATH = Path.home() / ".ztb" / "results.db"


def _get_db_path(db_path: str | Path | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    env = __import__("os").environ.get("ZTB_STORE_PATH")
    if env:
        return Path(env)
    return DEFAULT_DB_PATH


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = _get_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    schema_path = Path(__file__).parent / "schema.sql"
    conn.executescript(schema_path.read_text())
    conn.commit()


def _generate_run_id(result: BacktestResult) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{result.strategy_name}_{result.symbol}_{now}"


def save_run(conn: sqlite3.Connection, result: BacktestResult) -> str:
    run_id = _generate_run_id(result)
    conn.execute("BEGIN")

    try:
        conn.execute(
            """INSERT OR IGNORE INTO runs
               (run_id, strategy_name, symbol, timeframe, parameters, splits, code_version, credible)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                result.strategy_name,
                result.symbol,
                result.timeframe,
                json.dumps(result.parameters),
                json.dumps(result.splits),
                "0.4.0",
                1 if result.full.credible else 0,
            ),
        )

        for scope, m in [("full", result.full), ("is", result.is_), ("oos", result.oos)]:
            conn.execute(
                """INSERT OR IGNORE INTO metrics
                   (run_id, scope, total_return, sharpe, sortino, max_drawdown,
                    max_drawdown_duration, num_trades, profit_factor, win_rate,
                    turnover, exposure_time, credible, reason)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    scope,
                    m.total_return,
                    m.sharpe,
                    m.sortino,
                    m.max_drawdown,
                    m.max_drawdown_duration,
                    m.num_trades,
                    m.profit_factor,
                    m.win_rate,
                    m.turnover,
                    m.exposure_time,
                    1 if m.credible else 0,
                    m.reason,
                ),
            )

        for trade in result.trades:
            conn.execute(
                """INSERT INTO trades (run_id, timestamp, side, price, size, pnl, commission, slippage)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    str(trade.get("timestamp", "")),
                    trade.get("side", ""),
                    trade.get("price", 0.0),
                    trade.get("size", 0.0),
                    trade.get("pnl", 0.0),
                    trade.get("commission", 0.0),
                    trade.get("slippage", 0.0),
                ),
            )

        timestamps = result.portfolio.timestamps
        equity = result.portfolio.equity
        for ts, eq in zip(timestamps, equity):
            conn.execute(
                "INSERT INTO equity_curve (run_id, timestamp, equity) VALUES (?, ?, ?)",
                (run_id, str(ts), float(eq)),
            )

        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    return run_id


def get_run(conn: sqlite3.Connection, run_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return dict(row)


def get_metrics(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM metrics WHERE run_id = ? ORDER BY scope", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def list_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT run_id, strategy_name, symbol, timeframe, code_version, created_at, credible "
        "FROM runs ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def latest_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT run_id, strategy_name, symbol, timeframe, code_version, created_at, credible "
        "FROM runs ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def best_runs(
    conn: sqlite3.Connection,
    metric: str = "sharpe",
    scope: str = "oos",
    limit: int = 10,
) -> list[dict[str, Any]]:
    if scope not in ("full", "is", "oos"):
        scope = "oos"
    if metric not in _METRIC_NAMES:
        metric = "sharpe"
    rows = conn.execute(
        f"""SELECT r.run_id, r.strategy_name, r.symbol, r.timeframe,
                   r.created_at, m.{metric} AS metric_value
            FROM runs r
            JOIN metrics m ON m.run_id = r.run_id
            WHERE m.scope = ? AND r.credible = 1 AND m.{metric} IS NOT NULL
            ORDER BY m.{metric} DESC
            LIMIT ?""",
        (scope, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_equity_curve(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM equity_curve WHERE run_id = ? ORDER BY timestamp", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_trades(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM trades WHERE run_id = ? ORDER BY timestamp", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_oos_metric(conn: sqlite3.Connection, run_id: str, name: str) -> float | None:
    if name not in _METRIC_NAMES:
        return None
    row = conn.execute(
        f"SELECT {name} FROM metrics WHERE run_id = ? AND scope = 'oos'", (run_id,)
    ).fetchone()
    if row is None:
        return None
    return row[0]


def get_oos_sharpe(conn: sqlite3.Connection, run_id: str) -> float | None:
    return get_oos_metric(conn, run_id, "sharpe")
