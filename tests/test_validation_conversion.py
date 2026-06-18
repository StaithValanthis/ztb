from __future__ import annotations

import sqlite3

from ztb.validation.conversion import _parse_version, compute_signal_to_fill_conversion


def _seed_store(
    conn: sqlite3.Connection,
    runs: list[dict],
    orders: list[dict],
    fills: list[dict],
) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS exec_runs (
            exec_run_id TEXT PRIMARY KEY, run_id TEXT, strategy_name TEXT,
            symbol TEXT, timeframe TEXT, mode TEXT, started_at TEXT,
            status TEXT, bars_processed INTEGER DEFAULT 0, last_bar_ts TEXT DEFAULT ''
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS exec_orders (
            order_link_id TEXT PRIMARY KEY, exec_run_id TEXT, order_id TEXT,
            symbol TEXT, side TEXT, order_type TEXT, price REAL DEFAULT 0,
            qty REAL DEFAULT 0, status TEXT, created_at TEXT,
            cum_exec_qty REAL DEFAULT 0, cum_exec_value REAL DEFAULT 0,
            cum_exec_fee REAL DEFAULT 0,
            code_version TEXT DEFAULT NULL
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS exec_fills (
            fill_id TEXT PRIMARY KEY, order_link_id TEXT, exec_run_id TEXT,
            order_id TEXT, symbol TEXT, side TEXT, price REAL, qty REAL,
            commission REAL DEFAULT 0, realized_pnl REAL DEFAULT 0, filled_at TEXT
        )"""
    )
    for r in runs:
        conn.execute(
            """INSERT OR IGNORE INTO exec_runs
               (exec_run_id, run_id, strategy_name, symbol, timeframe, mode, started_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                r["exec_run_id"],
                r.get("run_id", ""),
                r.get("strategy_name", "sma_cross"),
                r.get("symbol", "BTCUSDT"),
                r.get("timeframe", "60"),
                r.get("mode", "demo"),
                r.get("started_at", ""),
                r.get("status", "completed"),
            ),
        )
    for o in orders:
        conn.execute(
            """INSERT OR IGNORE INTO exec_orders
               (order_link_id, exec_run_id, order_id, symbol, side, order_type,
                price, qty, status, created_at, code_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                o["order_link_id"],
                o["exec_run_id"],
                o.get("order_id", ""),
                o.get("symbol", "BTCUSDT"),
                o.get("side", "Buy"),
                o.get("order_type", "Market"),
                o.get("price", 0.0),
                o.get("qty", 0.0),
                o.get("status", "Filled"),
                o.get("created_at", ""),
                o.get("code_version"),
            ),
        )
    for f in fills:
        conn.execute(
            """INSERT OR IGNORE INTO exec_fills
               (fill_id, order_link_id, exec_run_id, order_id, symbol, side,
                price, qty, commission, realized_pnl, filled_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f["fill_id"],
                f.get("order_link_id", ""),
                f["exec_run_id"],
                f.get("order_id", ""),
                f.get("symbol", "BTCUSDT"),
                f.get("side", "Buy"),
                f.get("price", 0.0),
                f.get("qty", 0.0),
                f.get("commission", 0.0),
                f.get("realized_pnl", 0.0),
                f.get("filled_at", ""),
            ),
        )
    conn.commit()


def test_conversion_all_real_fills(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    run_ids = [f"run_{i}" for i in range(5)]
    _seed_store(
        conn,
        runs=[{"exec_run_id": rid, "strategy_name": "sma_cross"} for rid in run_ids],
        orders=[{"order_link_id": f"o{i}", "exec_run_id": rid} for i, rid in enumerate(run_ids)],
        fills=[
            {"fill_id": f"f{i}", "exec_run_id": rid, "order_link_id": f"o{i}"}
            for i, rid in enumerate(run_ids)
        ],
    )
    conn.close()
    result = compute_signal_to_fill_conversion(str(db))
    assert result.conversion_rate == 1.0
    assert result.runs_with_signals == 5
    assert result.runs_with_real_fills == 5
    assert result.sufficient_sample is True


def test_conversion_mixed_fills(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    run_ids = [f"run_{i}" for i in range(5)]
    real_run_ids = run_ids[:3]
    _seed_store(
        conn,
        runs=[{"exec_run_id": rid} for rid in run_ids],
        orders=[{"order_link_id": f"o{i}", "exec_run_id": rid} for i, rid in enumerate(run_ids)],
        fills=[
            {"fill_id": f"f{i}", "exec_run_id": rid, "order_link_id": f"o{i}"}
            for i, rid in enumerate(real_run_ids)
        ],
    )
    conn.close()
    result = compute_signal_to_fill_conversion(str(db))
    assert result.conversion_rate == 0.6
    assert result.runs_with_signals == 5
    assert result.runs_with_real_fills == 3
    assert result.sufficient_sample is True


def test_conversion_no_runs(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    _seed_store(conn, [], [], [])
    conn.close()
    result = compute_signal_to_fill_conversion(str(db))
    assert result.conversion_rate == 0.0
    assert result.runs_with_signals == 0
    assert result.runs_with_real_fills == 0
    assert result.sufficient_sample is False


def test_conversion_no_signal_runs(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    _seed_store(
        conn,
        runs=[{"exec_run_id": "run_0"}],
        orders=[],
        fills=[],
    )
    conn.close()
    result = compute_signal_to_fill_conversion(str(db))
    assert result.conversion_rate == 0.0
    assert result.runs_with_signals == 0
    assert result.runs_with_real_fills == 0
    assert result.sufficient_sample is False


def test_conversion_below_min_sample(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    run_ids = [f"run_{i}" for i in range(3)]
    _seed_store(
        conn,
        runs=[{"exec_run_id": rid} for rid in run_ids],
        orders=[{"order_link_id": f"o{i}", "exec_run_id": rid} for i, rid in enumerate(run_ids)],
        fills=[
            {"fill_id": f"f{i}", "exec_run_id": rid, "order_link_id": f"o{i}"}
            for i, rid in enumerate(run_ids)
        ],
    )
    conn.close()
    result = compute_signal_to_fill_conversion(str(db))
    assert result.sufficient_sample is False
    assert result.runs_with_signals == 3


def test_conversion_at_min_sample(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    run_ids = [f"run_{i}" for i in range(5)]
    _seed_store(
        conn,
        runs=[{"exec_run_id": rid} for rid in run_ids],
        orders=[{"order_link_id": f"o{i}", "exec_run_id": rid} for i, rid in enumerate(run_ids)],
        fills=[],
    )
    conn.close()
    result = compute_signal_to_fill_conversion(str(db))
    assert result.sufficient_sample is True
    assert result.runs_with_signals == 5


def test_conversion_synthetic_fills_excluded(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    run_ids = [f"run_{i}" for i in range(3)]
    _seed_store(
        conn,
        runs=[{"exec_run_id": rid} for rid in run_ids],
        orders=[{"order_link_id": f"o{i}", "exec_run_id": rid} for i, rid in enumerate(run_ids)],
        fills=[
            {"fill_id": f"synthetic-o{i}", "exec_run_id": rid, "order_link_id": f"o{i}"}
            for i, rid in enumerate(run_ids)
        ],
    )
    conn.close()
    result = compute_signal_to_fill_conversion(str(db), min_signal_runs=3)
    assert result.conversion_rate == 0.0
    assert result.runs_with_real_fills == 0
    assert result.sufficient_sample is True


def test_conversion_filter_by_strategy(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    _seed_store(
        conn,
        runs=[
            {"exec_run_id": "r1", "strategy_name": "strat_a"},
            {"exec_run_id": "r2", "strategy_name": "strat_a"},
            {"exec_run_id": "r3", "strategy_name": "strat_b"},
            {"exec_run_id": "r4", "strategy_name": "strat_b"},
        ],
        orders=[
            {"order_link_id": "o1", "exec_run_id": "r1"},
            {"order_link_id": "o2", "exec_run_id": "r2"},
            {"order_link_id": "o3", "exec_run_id": "r3"},
            {"order_link_id": "o4", "exec_run_id": "r4"},
        ],
        fills=[
            {"fill_id": "f1", "exec_run_id": "r1", "order_link_id": "o1"},
            {"fill_id": "f3", "exec_run_id": "r3", "order_link_id": "o3"},
        ],
    )
    conn.close()
    result_a = compute_signal_to_fill_conversion(str(db), strategy_name="strat_a")
    assert result_a.runs_with_signals == 2
    assert result_a.runs_with_real_fills == 1
    assert result_a.conversion_rate == 0.5

    result_b = compute_signal_to_fill_conversion(str(db), strategy_name="strat_b")
    assert result_b.runs_with_signals == 2
    assert result_b.runs_with_real_fills == 1
    assert result_b.conversion_rate == 0.5


def test_conversion_no_fills_at_all(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    run_ids = [f"run_{i}" for i in range(5)]
    _seed_store(
        conn,
        runs=[{"exec_run_id": rid} for rid in run_ids],
        orders=[{"order_link_id": f"o{i}", "exec_run_id": rid} for i, rid in enumerate(run_ids)],
        fills=[],
    )
    conn.close()
    result = compute_signal_to_fill_conversion(str(db))
    assert result.conversion_rate == 0.0
    assert result.runs_with_signals == 5
    assert result.runs_with_real_fills == 0
    assert result.sufficient_sample is True


def test_conversion_min_code_version_filter(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    _seed_store(
        conn,
        runs=[
            {"exec_run_id": "r1"},
            {"exec_run_id": "r2"},
            {"exec_run_id": "r3"},
        ],
        orders=[
            {"order_link_id": "o1", "exec_run_id": "r1", "code_version": "1.1.50"},
            {"order_link_id": "o2", "exec_run_id": "r2", "code_version": "1.1.53"},
            {"order_link_id": "o3", "exec_run_id": "r3", "code_version": "1.1.55"},
        ],
        fills=[
            {"fill_id": "f1", "exec_run_id": "r1", "order_link_id": "o1"},
            {"fill_id": "f2", "exec_run_id": "r2", "order_link_id": "o2"},
        ],
    )
    conn.close()
    result = compute_signal_to_fill_conversion(str(db), min_code_version="1.1.53")
    assert result.runs_with_signals == 2
    assert result.runs_with_real_fills == 1
    assert result.conversion_rate == 0.5
    assert result.sufficient_sample is False


def test_conversion_min_code_version_all_excluded(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    _seed_store(
        conn,
        runs=[{"exec_run_id": "r1"}],
        orders=[
            {"order_link_id": "o1", "exec_run_id": "r1", "code_version": "1.1.50"},
        ],
        fills=[
            {"fill_id": "f1", "exec_run_id": "r1", "order_link_id": "o1"},
        ],
    )
    conn.close()
    result = compute_signal_to_fill_conversion(str(db), min_code_version="1.1.53")
    assert result.runs_with_signals == 0
    assert result.runs_with_real_fills == 0
    assert result.conversion_rate == 0.0
    assert result.sufficient_sample is False


def test_conversion_min_code_version_with_null_versions(tmp_path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    _seed_store(
        conn,
        runs=[
            {"exec_run_id": "r1"},
            {"exec_run_id": "r2"},
        ],
        orders=[
            {"order_link_id": "o1", "exec_run_id": "r1"},
            {"order_link_id": "o2", "exec_run_id": "r2", "code_version": "1.1.55"},
        ],
        fills=[
            {"fill_id": "f2", "exec_run_id": "r2", "order_link_id": "o2"},
        ],
    )
    conn.close()
    result = compute_signal_to_fill_conversion(str(db), min_code_version="1.1.53")
    assert result.runs_with_signals == 1
    assert result.runs_with_real_fills == 1
    assert result.conversion_rate == 1.0


def test_parse_version() -> None:
    assert _parse_version("1.1.53") == (1, 1, 53)
    assert _parse_version("0.7.0") == (0, 7, 0)
    assert _parse_version("1.0.0") == (1, 0, 0)
