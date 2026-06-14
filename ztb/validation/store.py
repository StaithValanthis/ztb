from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from ztb.validation.scoring import Scorecard
from ztb.validation.walkforward import WalkforwardResult


def _generate_val_run_id(strategy_name: str, symbol: str) -> str:
    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    return f"val_{strategy_name}_{symbol}_{now}"


def save_walkforward_run(
    conn: sqlite3.Connection,
    result: WalkforwardResult,
    scorecard: Scorecard | None = None,
) -> str:
    val_run_id = _generate_val_run_id(result.strategy_name, result.symbol)
    conn.execute("BEGIN")
    try:
        conn.execute(
            """INSERT OR IGNORE INTO validation_runs
               (val_run_id, strategy_name, symbol, timeframe, val_type,
                n_windows, avg_oos_sharpe, avg_oos_return, avg_oos_maxdd,
                avg_oos_trades, sharpe_consistency, return_consistency,
                maxdd_consistency, all_windows_valid, overall_score,
                sharpe_score, dsr_score, walkforward_score,
                consistency_score, drawdown_score, parameters, details)
               VALUES (?, ?, ?, ?, 'walkforward',
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?)""",
            (
                val_run_id,
                result.strategy_name,
                result.symbol,
                result.timeframe,
                result.n_windows,
                result.avg_oos_sharpe,
                result.avg_oos_return,
                result.avg_oos_maxdd,
                result.avg_oos_trades,
                result.sharpe_consistency,
                result.return_consistency,
                result.maxdd_consistency,
                1 if result.all_windows_valid else 0,
                scorecard.overall_score if scorecard else None,
                scorecard.oos_sharpe_score if scorecard else None,
                scorecard.dsr_score if scorecard else None,
                scorecard.walkforward_score if scorecard else None,
                scorecard.consistency_score if scorecard else None,
                scorecard.drawdown_score if scorecard else None,
                json.dumps(result.parameters),
                json.dumps(scorecard.details if scorecard else {}),
            ),
        )

        for w in result.windows:
            conn.execute(
                """INSERT OR IGNORE INTO validation_windows
                   (val_run_id, window_idx, train_start, train_end,
                    test_start, test_end, train_duration_bars,
                    test_duration_bars,
                    train_sharpe, train_return, train_maxdd, train_trades,
                    test_sharpe, test_return, test_maxdd, test_trades)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    val_run_id,
                    w.window_idx,
                    w.train_start,
                    w.train_end,
                    w.test_start,
                    w.test_end,
                    w.train_duration_bars,
                    w.test_duration_bars,
                    w.train_result.oos.sharpe if w.train_result.oos else None,
                    w.train_result.oos.total_return if w.train_result.oos else None,
                    w.train_result.oos.max_drawdown if w.train_result.oos else None,
                    w.train_result.oos.num_trades if w.train_result.oos else 0,
                    w.test_result.oos.sharpe if w.test_result.oos else None,
                    w.test_result.oos.total_return if w.test_result.oos else None,
                    w.test_result.oos.max_drawdown if w.test_result.oos else None,
                    w.test_result.oos.num_trades if w.test_result.oos else 0,
                ),
            )

        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise

    return val_run_id


def list_validation_runs(
    conn: sqlite3.Connection,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT val_run_id, strategy_name, symbol, timeframe, val_type,
                  n_windows, avg_oos_sharpe, overall_score, created_at
           FROM validation_runs
           ORDER BY created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_validation_run(
    conn: sqlite3.Connection,
    val_run_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM validation_runs WHERE val_run_id = ?", (val_run_id,)
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def get_validation_windows(
    conn: sqlite3.Connection,
    val_run_id: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM validation_windows WHERE val_run_id = ? ORDER BY window_idx",
        (val_run_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def best_validation_runs(
    conn: sqlite3.Connection,
    metric: str = "overall_score",
    limit: int = 10,
) -> list[dict[str, Any]]:
    allowed = {"overall_score", "avg_oos_sharpe", "avg_oos_return", "dsr_score"}
    if metric not in allowed:
        metric = "overall_score"
    rows = conn.execute(
        f"""SELECT val_run_id, strategy_name, symbol, timeframe,
                   {metric} AS metric_value, created_at
            FROM validation_runs
            WHERE {metric} IS NOT NULL
            ORDER BY {metric} DESC
            LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
