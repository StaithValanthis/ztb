from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass
class SignalToFillConversion:
    conversion_rate: float
    runs_with_signals: int
    runs_with_real_fills: int
    sufficient_sample: bool


def _parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(p) for p in v.split("."))


def compute_signal_to_fill_conversion(
    store_path: str,
    strategy_name: str | None = None,
    min_signal_runs: int = 5,
    min_code_version: str | None = None,
) -> SignalToFillConversion:
    conn = sqlite3.connect(store_path)
    conn.row_factory = sqlite3.Row
    try:
        base = """SELECT o.exec_run_id, MAX(o.code_version) as code_version
                  FROM exec_orders o
                  JOIN exec_runs r ON o.exec_run_id = r.exec_run_id"""
        params: list[str] = []
        wheres: list[str] = []
        if strategy_name:
            wheres.append("r.strategy_name = ?")
            params.append(strategy_name)
        if wheres:
            base += " WHERE " + " AND ".join(wheres)
        base += " GROUP BY o.exec_run_id"
        rows = conn.execute(base, params).fetchall()
        if min_code_version is not None:
            min_ver = _parse_version(min_code_version)
            signal_run_ids = [
                row["exec_run_id"]
                for row in rows
                if row["code_version"] is not None
                and _parse_version(row["code_version"]) >= min_ver
            ]
        else:
            signal_run_ids = [row["exec_run_id"] for row in rows]
        denom = len(signal_run_ids)
        if denom == 0:
            return SignalToFillConversion(
                conversion_rate=0.0,
                runs_with_signals=0,
                runs_with_real_fills=0,
                sufficient_sample=False,
            )
        placeholders = ",".join("?" * denom)
        fill_run_ids = [
            row["exec_run_id"]
            for row in conn.execute(
                f"""SELECT DISTINCT f.exec_run_id FROM exec_fills f
                    WHERE f.exec_run_id IN ({placeholders})
                    AND f.fill_id NOT LIKE 'synthetic-%'""",
                signal_run_ids,
            ).fetchall()
        ]
        numer = len(fill_run_ids)
        conversion_rate = numer / denom
        sufficient_sample = denom >= min_signal_runs
        return SignalToFillConversion(
            conversion_rate=conversion_rate,
            runs_with_signals=denom,
            runs_with_real_fills=numer,
            sufficient_sample=sufficient_sample,
        )
    finally:
        conn.close()
