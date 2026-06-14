from __future__ import annotations

import sqlite3

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.store.results import connect
from ztb.strategies.base import Strategy
from ztb.validation.deflated_sharpe import DeflatedSharpeResult
from ztb.validation.lookahead import LookaheadResult
from ztb.validation.scoring import evaluate_acceptance_criteria
from ztb.validation.store import (
    _ensure_validation_tables,
    _generate_run_id,
    get_validation_run,
    save_validation_run,
)
from ztb.validation.walk_forward import WalkForwardConfig, WalkForwardResult, run_walk_forward


class LongStrat(Strategy):
    name = "long"
    symbols = ["BTCUSDT"]
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(1.0, index=df.index)


def _sample_wf() -> WalkForwardResult:
    np.random.seed(42)
    n = 2000
    df = DataFrame(
        {
            "open": [100.0 + i * 0.05 for i in range(n)],
            "high": [101.0 + i * 0.05 for i in range(n)],
            "low": [99.0 + i * 0.05 for i in range(n)],
            "close": [100.0 + i * 0.05 + np.random.randn() * 0.5 for i in range(n)],
            "volume": [1000.0] * n,
        },
        index=pd.date_range("2020-01-01", periods=n, freq="h"),
    )
    strat = LongStrat()
    return run_walk_forward(strat, df, WalkForwardConfig(n_windows=3, min_trades=1))


@pytest.fixture
def db_path(tmp_path: pytest.TempPathFactory) -> str:
    return str(tmp_path / "test_val.db")


@pytest.fixture
def conn(db_path: str) -> sqlite3.Connection:
    c = connect(db_path)
    yield c
    c.close()


def test_ensure_tables(conn: sqlite3.Connection) -> None:
    _ensure_validation_tables(conn)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [t[0] for t in tables]
    assert "validation_runs" in names
    assert "validation_windows" in names


def test_generate_run_id() -> None:
    rid = _generate_run_id("test", "BTCUSDT")
    assert rid.startswith("val_test_BTCUSDT_")


def test_save_and_get_validation_run(conn: sqlite3.Connection) -> None:
    wf = _sample_wf()
    look = LookaheadResult(passed=True, details=[], bars_checked=100, mode="frame")
    dsr = DeflatedSharpeResult(dsr=0.972, n_trials_equivalent=1, is_significant=True)
    scorecard = evaluate_acceptance_criteria(wf, dsr, look)

    run_id = save_validation_run(
        conn,
        strategy="long",
        symbol="BTCUSDT",
        timeframe="60",
        overall_pass=scorecard["pass"],
        wf_result=wf,
        dsr=dsr.dsr,
        dsr_significant=dsr.is_significant,
        lookahead_pass=look.passed,
    )
    assert run_id.startswith("val_long_BTCUSDT_")

    loaded = get_validation_run(conn, run_id)
    assert loaded is not None
    assert loaded["strategy"] == "long"
    assert loaded["symbol"] == "BTCUSDT"
    assert loaded["deflated_sharpe"] == 0.972
    assert loaded["lookahead_pass"] == 1
    assert loaded["n_windows"] == wf.n_windows_total
    assert loaded["n_windows_credible"] == wf.n_windows_credible


def test_save_validation_run_with_windows(conn: sqlite3.Connection) -> None:
    wf = _sample_wf()
    look = LookaheadResult(passed=True, details=[], bars_checked=100, mode="frame")
    dsr = DeflatedSharpeResult(dsr=0.95, n_trials_equivalent=1, is_significant=True)
    scorecard = evaluate_acceptance_criteria(wf, dsr, look)

    run_id = save_validation_run(
        conn,
        strategy="long",
        symbol="BTCUSDT",
        timeframe="60",
        overall_pass=scorecard["pass"],
        wf_result=wf,
        dsr=dsr.dsr,
        dsr_significant=dsr.is_significant,
        lookahead_pass=look.passed,
    )

    windows = conn.execute(
        "SELECT * FROM validation_windows WHERE run_id = ? ORDER BY window_idx",
        (run_id,),
    ).fetchall()
    assert len(windows) == len(wf.per_window)


def test_get_validation_run_with_windows(conn: sqlite3.Connection) -> None:
    wf = _sample_wf()
    look = LookaheadResult(passed=True, details=[], bars_checked=100, mode="frame")
    dsr = DeflatedSharpeResult(dsr=0.95, n_trials_equivalent=1, is_significant=True)
    scorecard = evaluate_acceptance_criteria(wf, dsr, look)

    run_id = save_validation_run(
        conn,
        strategy="long",
        symbol="BTCUSDT",
        timeframe="60",
        overall_pass=scorecard["pass"],
        wf_result=wf,
        dsr=dsr.dsr,
        dsr_significant=dsr.is_significant,
        lookahead_pass=look.passed,
    )

    loaded = get_validation_run(conn, run_id)
    assert loaded is not None
    assert "windows" in loaded
    assert len(loaded["windows"]) == len(wf.per_window)


def test_save_invalid_rollback(conn: sqlite3.Connection) -> None:
    try:
        save_validation_run(
            conn,
            strategy="test",
            symbol="BTCUSDT",
            timeframe="60",
            overall_pass=True,
            wf_result=None,
            dsr=0.0,
            dsr_significant=False,
            lookahead_pass=True,
        )
        pytest.fail("should have raised")
    except Exception:
        pass


def test_schema_columns_match_spec(conn: sqlite3.Connection) -> None:
    _ensure_validation_tables(conn)
    cols = conn.execute("PRAGMA table_info(validation_runs)").fetchall()
    col_names = {c[1] for c in cols}
    expected = {
        "run_id",
        "strategy",
        "symbol",
        "timeframe",
        "pass",
        "oos_sharpe",
        "deflated_sharpe",
        "dsr_significant",
        "lookahead_pass",
        "n_windows",
        "n_windows_credible",
        "stability",
        "parameters",
        "sha",
        "created_at",
    }
    assert expected.issubset(col_names)
