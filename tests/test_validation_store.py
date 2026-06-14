from __future__ import annotations

import sqlite3

import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.engine.metrics import MetricsResult
from ztb.strategies.base import Strategy
from ztb.store.results import connect
from ztb.validation.scoring import Scorecard
from ztb.validation.store import (
    _generate_val_run_id,
    best_validation_runs,
    get_validation_run,
    get_validation_windows,
    list_validation_runs,
    save_walkforward_run,
)
from ztb.validation.walkforward import WalkforwardConfig, WalkforwardResult, WalkforwardWindow, run_walkforward


class FlatStrat(Strategy):
    name = "flat-valid"
    symbols = ["BTCUSDT"]
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(0.0, index=df.index)


def _sample_df(n: int = 500) -> DataFrame:
    return DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [101.0 + i * 0.1 for i in range(n)],
            "low": [99.0 + i * 0.1 for i in range(n)],
            "close": [100.0 + i * 0.1 for i in range(n)],
            "volume": [1000.0] * n,
        },
        index=pd.date_range("2020-01-01", periods=n, freq="h"),
    )


@pytest.fixture
def db_path(tmp_path: pytest.TempPathFactory) -> str:
    return str(tmp_path / "test_validation.db")


@pytest.fixture
def conn(db_path: str) -> sqlite3.Connection:
    c = connect(db_path)
    yield c
    c.close()


@pytest.fixture
def sample_wf_result(conn: sqlite3.Connection) -> WalkforwardResult:
    df = _sample_df(500)
    strat = FlatStrat()
    return run_walkforward(strat, df)


def test_generate_val_run_id() -> None:
    rid = _generate_val_run_id("test", "BTCUSDT")
    assert rid.startswith("val_test_BTCUSDT_")
    assert len(rid) > len("val_test_BTCUSDT_")


def test_save_and_get_walkforward_run(conn: sqlite3.Connection, sample_wf_result: WalkforwardResult) -> None:
    val_run_id = save_walkforward_run(conn, sample_wf_result)
    assert val_run_id.startswith("val_flat-valid_BTCUSDT_")
    assert val_run_id is not None

    loaded = get_validation_run(conn, val_run_id)
    assert loaded is not None
    assert loaded["strategy_name"] == "flat-valid"
    assert loaded["symbol"] == "BTCUSDT"
    assert loaded["n_windows"] == sample_wf_result.n_windows
    assert loaded["val_type"] == "walkforward"


def test_save_with_scorecard(conn: sqlite3.Connection, sample_wf_result: WalkforwardResult) -> None:
    sc = Scorecard(
        overall_score=0.75,
        oos_sharpe_score=0.6,
        dsr_score=0.8,
        walkforward_score=0.7,
        consistency_score=0.65,
        drawdown_score=0.9,
    )
    val_run_id = save_walkforward_run(conn, sample_wf_result, sc)
    loaded = get_validation_run(conn, val_run_id)
    assert loaded["overall_score"] == 0.75
    assert loaded["dsr_score"] == 0.8


def test_get_validation_windows(conn: sqlite3.Connection, sample_wf_result: WalkforwardResult) -> None:
    val_run_id = save_walkforward_run(conn, sample_wf_result)
    windows = get_validation_windows(conn, val_run_id)
    assert len(windows) == sample_wf_result.n_windows
    for w in windows:
        assert w["window_idx"] >= 0
        assert w["val_run_id"] == val_run_id


def test_list_validation_runs(conn: sqlite3.Connection, sample_wf_result: WalkforwardResult) -> None:
    assert list_validation_runs(conn) == []
    save_walkforward_run(conn, sample_wf_result)
    runs = list_validation_runs(conn)
    assert len(runs) == 1
    assert runs[0]["strategy_name"] == "flat-valid"


def test_best_validation_runs(conn: sqlite3.Connection, sample_wf_result: WalkforwardResult) -> None:
    sc = Scorecard(
        overall_score=0.85,
        oos_sharpe_score=0.7,
        dsr_score=0.9,
        walkforward_score=0.8,
        consistency_score=0.75,
        drawdown_score=0.95,
    )
    save_walkforward_run(conn, sample_wf_result, sc)
    best = best_validation_runs(conn, limit=5)
    assert len(best) >= 1
    assert "metric_value" in best[0]


def test_save_walkforward_atomicity(conn: sqlite3.Connection, sample_wf_result: WalkforwardResult) -> None:
    val_run_id = save_walkforward_run(conn, sample_wf_result)
    assert get_validation_run(conn, val_run_id) is not None
    windows = get_validation_windows(conn, val_run_id)
    assert len(windows) > 0


def test_get_nonexistent_run(conn: sqlite3.Connection) -> None:
    assert get_validation_run(conn, "nonexistent") is None
    assert get_validation_windows(conn, "nonexistent") == []


def test_best_validation_runs_default_metric(conn: sqlite3.Connection) -> None:
    from ztb.validation.walkforward import WalkforwardConfig

    sc1 = Scorecard(overall_score=0.9, oos_sharpe_score=0.8, dsr_score=0.9, walkforward_score=0.85, consistency_score=0.8, drawdown_score=0.95)
    sc2 = Scorecard(overall_score=0.7, oos_sharpe_score=0.5, dsr_score=0.6, walkforward_score=0.6, consistency_score=0.5, drawdown_score=0.8)

    df = _sample_df(500)
    strat2 = FlatStrat()
    strat2.name = "flat-valid-2"

    wf1 = run_walkforward(FlatStrat(), df)
    wf2 = run_walkforward(strat2, df)

    save_walkforward_run(conn, wf1, sc1)
    save_walkforward_run(conn, wf2, sc2)

    best = best_validation_runs(conn, limit=10)
    assert len(best) == 2
    assert best[0]["metric_value"] == 0.9
