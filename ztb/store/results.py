from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ztb import __version__
from ztb.engine.backtest import BacktestResult
from ztb.engine.forwardtest import ForwardtestResult

_MIGRATION_LOCK_TIMEOUT = 60.0
_RETRY_MAX = 3
_RETRY_DELAY = 0.5


@contextmanager
def _migration_lock(db_path: Path, timeout: float = _MIGRATION_LOCK_TIMEOUT):
    import fcntl

    lock_path = db_path.with_name(f".{db_path.name}.migrate.lock")
    lock_file: int | None = None
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    os.close(lock_fd)
                    raise RuntimeError(
                        f"Migration lock timeout after {timeout}s for {db_path}"
                    ) from None
                time.sleep(0.1)
        lock_file = lock_fd
        yield
    finally:
        if lock_file is not None:
            with suppress(OSError):
                fcntl.flock(lock_file, fcntl.LOCK_UN)
            os.close(lock_file)


def _get_db_path_from_conn(conn: sqlite3.Connection) -> Path:
    row = conn.execute("PRAGMA database_list").fetchone()
    return Path(row[2])


def execute_with_retry(
    conn: sqlite3.Connection,
    sql: str,
    params: tuple[Any, ...] | None = None,
    max_retries: int = _RETRY_MAX,
    delay: float = _RETRY_DELAY,
) -> sqlite3.Cursor:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            if params is not None:
                return conn.execute(sql, params)
            return conn.execute(sql)
        except sqlite3.OperationalError as e:
            err_str = str(e).lower()
            if "database is locked" not in err_str and "database is busy" not in err_str:
                raise
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(delay * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise sqlite3.OperationalError("execute_with_retry exhausted retries")

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
    conn.row_factory = sqlite3.Row
    with _migration_lock(path):
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _ensure_schema(conn)
        _run_migrations(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    schema_path = Path(__file__).parent / "schema.sql"
    conn.executescript(schema_path.read_text())
    conn.commit()


def _run_migrations(conn: sqlite3.Connection) -> None:
    from contextlib import suppress

    try:
        conn.execute("SELECT run_type FROM runs LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE runs ADD COLUMN run_type TEXT NOT NULL DEFAULT 'backtest'")
    with suppress(sqlite3.OperationalError):
        conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (2)")

    for col in ("risk_aware", "max_portfolio_dd_realized", "kill_count", "mean_gross_leverage"):
        with suppress(sqlite3.OperationalError):
            conn.execute(f"ALTER TABLE runs ADD COLUMN {col} TEXT")
    with suppress(sqlite3.OperationalError):
        conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (3)")

    # Schema v4: add sufficient_sample column (replaces credible)
    try:
        conn.execute("SELECT sufficient_sample FROM runs LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE runs ADD COLUMN sufficient_sample INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE runs SET sufficient_sample = credible WHERE credible IS NOT NULL")
    try:
        conn.execute("SELECT sufficient_sample FROM metrics LIMIT 0")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE metrics ADD COLUMN sufficient_sample INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE metrics SET sufficient_sample = credible WHERE credible IS NOT NULL")
    try:
        conn.execute("SELECT val_type FROM validation_runs LIMIT 0")
    except sqlite3.OperationalError:
        schema_path = Path(__file__).parent / "schema.sql"
        conn.executescript(schema_path.read_text())
    with suppress(sqlite3.OperationalError):
        conn.execute("INSERT OR IGNORE INTO schema_meta (version) VALUES (5)")
    conn.commit()


def _generate_run_id(strategy_name: str, symbol: str) -> str:
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"{strategy_name}_{symbol}_{now}"


def save_run(conn: sqlite3.Connection, result: BacktestResult) -> str:
    run_id = _generate_run_id(result.strategy_name, result.symbol)
    conn.execute("BEGIN")

    try:
        conn.execute(
            """INSERT OR IGNORE INTO runs
               (run_id, strategy_name, symbol, timeframe, run_type, parameters,
                splits, code_version, sufficient_sample,
                risk_aware, max_portfolio_dd_realized, kill_count, mean_gross_leverage)
               VALUES (?, ?, ?, ?, 'backtest', ?, ?, ?, ?,
                ?, ?, ?, ?)""",
            (
                run_id,
                result.strategy_name,
                result.symbol,
                result.timeframe,
                json.dumps(result.parameters),
                json.dumps(result.splits),
                __version__,
                1 if result.full.sufficient_sample else 0,
                1 if result.risk_aware else 0,
                result.max_portfolio_dd_realized,
                result.kill_count,
                result.mean_gross_leverage,
            ),
        )

        for scope, m in [("full", result.full), ("is", result.is_), ("oos", result.oos)]:
            conn.execute(
                """INSERT OR IGNORE INTO metrics
                   (run_id, scope, total_return, sharpe, sortino, max_drawdown,
                    max_drawdown_duration, num_trades, profit_factor, win_rate,
                    turnover, exposure_time, sufficient_sample, reason)
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
                    1 if m.sufficient_sample else 0,
                    m.reason,
                ),
            )

        for trade in result.trades:
            conn.execute(
                """INSERT INTO trades
                   (run_id, timestamp, side, price, size, pnl, commission, slippage)
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
        for ts, eq in zip(timestamps, equity, strict=True):
            conn.execute(
                "INSERT INTO equity_curve (run_id, timestamp, equity) VALUES (?, ?, ?)",
                (run_id, str(ts), float(eq)),
            )

        for d in result.risk_decisions:
            with suppress(sqlite3.OperationalError):
                conn.execute(
                    """INSERT OR IGNORE INTO risk_decisions
                       (run_id, timestamp, symbol, action, reason, max_pos_size,
                        max_leverage, max_notional, current_dd, current_heat, hwm)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        d.get("timestamp", ""),
                        d.get("symbol", ""),
                        d.get("action", ""),
                        d.get("reason", ""),
                        d.get("max_pos_size", 0.0),
                        d.get("max_leverage", 0.0),
                        d.get("max_notional", 0.0),
                        d.get("current_dd"),
                        d.get("current_heat"),
                        d.get("hwm"),
                    ),
                )

        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    return run_id


def save_forward_run(conn: sqlite3.Connection, result: ForwardtestResult) -> str:
    run_id = _generate_run_id(result.strategy_name, result.symbol)
    conn.execute("BEGIN")

    try:
        splits: dict[str, Any] = {
            "warmup_bars": result.warmup_bars,
            "total_bars": result.total_bars,
        }
        if result.decay_score is not None:
            splits["decay_score"] = result.decay_score
        if result.decay_alarm is not None:
            splits["decay_alarm"] = {
                "triggered": result.decay_alarm[0],
                "reason": result.decay_alarm[1],
            }
        if result.baseline_run_id is not None:
            splits["baseline_run_id"] = result.baseline_run_id
        conn.execute(
            """INSERT OR IGNORE INTO runs
               (run_id, strategy_name, symbol, timeframe, run_type, parameters,
                splits, code_version, sufficient_sample,
                risk_aware, max_portfolio_dd_realized, kill_count, mean_gross_leverage)
               VALUES (?, ?, ?, ?, 'forward', ?, ?, ?, ?,
                ?, ?, ?, ?)""",
            (
                run_id,
                result.strategy_name,
                result.symbol,
                result.timeframe,
                json.dumps(result.parameters),
                json.dumps(splits),
                __version__,
                1 if result.metrics.sufficient_sample else 0,
                1 if result.risk_aware else 0,
                result.max_portfolio_dd_realized,
                result.kill_count,
                result.mean_gross_leverage,
            ),
        )

        m = result.metrics
        conn.execute(
            """INSERT OR IGNORE INTO metrics
               (run_id, scope, total_return, sharpe, sortino, max_drawdown,
                max_drawdown_duration, num_trades, profit_factor, win_rate,
                 turnover, exposure_time, sufficient_sample, reason)
                VALUES (?, 'full', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
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
                1 if m.sufficient_sample else 0,
                m.reason,
            ),
        )

        for trade in result.trades:
            conn.execute(
                """INSERT INTO trades
                   (run_id, timestamp, side, price, size, pnl, commission, slippage)
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
        for ts, eq in zip(timestamps, equity, strict=True):
            conn.execute(
                "INSERT INTO equity_curve (run_id, timestamp, equity) VALUES (?, ?, ?)",
                (run_id, str(ts), float(eq)),
            )

        for d in result.risk_decisions:
            with suppress(sqlite3.OperationalError):
                conn.execute(
                    """INSERT OR IGNORE INTO risk_decisions
                       (run_id, timestamp, symbol, action, reason, max_pos_size,
                        max_leverage, max_notional, current_dd, current_heat, hwm)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run_id,
                        d.get("timestamp", ""),
                        d.get("symbol", ""),
                        d.get("action", ""),
                        d.get("reason", ""),
                        d.get("max_pos_size", 0.0),
                        d.get("max_leverage", 0.0),
                        d.get("max_notional", 0.0),
                        d.get("current_dd"),
                        d.get("current_heat"),
                        d.get("hwm"),
                    ),
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


_RUN_COLS = (
    "run_id, strategy_name, symbol, timeframe,"
    " run_type, code_version, created_at, sufficient_sample"
)


def list_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(f"SELECT {_RUN_COLS} FROM runs ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def list_forward_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {_RUN_COLS} FROM runs WHERE run_type = 'forward' ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def latest_run(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(f"SELECT {_RUN_COLS} FROM runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return dict(row)


def best_runs(
    conn: sqlite3.Connection,
    metric: str = "sharpe",
    scope: str = "oos",
    limit: int = 10,
) -> list[dict[str, Any]]:
    if scope not in ("full", "is", "oos", "forward"):
        scope = "oos"
    if metric not in _METRIC_NAMES:
        metric = "sharpe"
    rows = conn.execute(
        f"""SELECT r.run_id, r.strategy_name, r.symbol, r.timeframe,
                   r.created_at, m.{metric} AS metric_value
            FROM runs r
            JOIN metrics m ON m.run_id = r.run_id
            WHERE m.scope = ? AND r.sufficient_sample = 1 AND m.{metric} IS NOT NULL
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
    val = row[0]
    return float(val) if val is not None else None


def get_oos_sharpe(conn: sqlite3.Connection, run_id: str) -> float | None:
    return get_oos_metric(conn, run_id, "sharpe")


def save_risk_decisions(
    conn: sqlite3.Connection,
    run_id: str,
    decisions: list[dict[str, Any]],
    risk_aware: bool = False,
    max_portfolio_dd_realized: float | None = None,
    kill_count: int = 0,
    mean_gross_leverage: float | None = None,
) -> None:
    for d in decisions:
        conn.execute(
            """INSERT OR IGNORE INTO risk_decisions
               (run_id, timestamp, symbol, action, reason, max_pos_size,
                max_leverage, max_notional, current_dd, current_heat, hwm)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                d.get("timestamp", ""),
                d.get("symbol", ""),
                d.get("action", ""),
                d.get("reason", ""),
                d.get("max_pos_size", 0.0),
                d.get("max_leverage", 0.0),
                d.get("max_notional", 0.0),
                d.get("current_dd"),
                d.get("current_heat"),
                d.get("hwm"),
            ),
        )
    with suppress(sqlite3.OperationalError):
        conn.execute(
            """UPDATE runs SET
               risk_aware = ?,
               max_portfolio_dd_realized = ?,
               kill_count = ?,
               mean_gross_leverage = ?
               WHERE run_id = ?""",
            (
                1 if risk_aware else 0,
                max_portfolio_dd_realized,
                kill_count,
                mean_gross_leverage,
                run_id,
            ),
        )
    conn.commit()


def get_risk_decisions(conn: sqlite3.Connection, run_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM risk_decisions WHERE run_id = ? ORDER BY decision_id", (run_id,)
    ).fetchall()
    return [dict(r) for r in rows]
