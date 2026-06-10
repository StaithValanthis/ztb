from __future__ import annotations

from pathlib import Path

import pytest

from ztb.engine.backtest import BacktestConfig, run_backtest
from ztb.reporting.scorecard import build_scorecard
from ztb.store.results import (
    connect,
    get_equity_curve,
    get_metrics,
    get_run,
    get_trades,
    list_runs,
    save_run,
)
from ztb.strategies.registry import get as get_strategy


@pytest.fixture
def strat_and_data():
    from pandas import DataFrame, date_range

    cls = get_strategy("sma_cross")
    strat = cls()
    strat.symbols = ["TEST"]
    df = DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(200)],
            "high": [101.0 + i * 0.1 for i in range(200)],
            "low": [99.0 + i * 0.1 for i in range(200)],
            "close": [100.0 + i * 0.1 for i in range(200)],
            "volume": [1000.0] * 200,
        },
        index=date_range("2020-01-01", periods=200, freq="h"),
    )
    return strat, df


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "integration_results.db")


# INT-1: test_run_to_store
def test_run_to_store(strat_and_data, db_path: str) -> None:
    strat, df = strat_and_data
    config = BacktestConfig(min_trades=0)
    result = run_backtest(strat, df, config)

    conn = connect(db_path)
    run_id = save_run(conn, result)
    _ = get_run(conn, run_id)

    metrics = get_metrics(conn, run_id)
    assert len(metrics) == 3

    trades = get_trades(conn, run_id)
    assert len(trades) >= 1

    equity = get_equity_curve(conn, run_id)
    assert len(equity) >= 1

    runs = list_runs(conn)
    assert len(runs) >= 1
    conn.close()


# INT-2: Scorecard has OOS Sharpe
def test_scorecard_has_oos_sharpe(strat_and_data, db_path: str) -> None:
    strat, df = strat_and_data
    config = BacktestConfig(min_trades=0)
    result = run_backtest(strat, df, config)

    conn = connect(db_path)
    run_id = save_run(conn, result)
    run_info = get_run(conn, run_id)
    metrics = get_metrics(conn, run_id)
    trades = get_trades(conn, run_id)
    equity = get_equity_curve(conn, run_id)
    conn.close()

    sc = build_scorecard(run_info, metrics, trades, equity)
    assert "oos" in sc["metrics"]
    assert sc["metrics"]["oos"]["sharpe"] is not None


# INT-3: Stored == engine metrics
def test_stored_equals_engine(strat_and_data, db_path: str) -> None:
    strat, df = strat_and_data
    config = BacktestConfig(min_trades=0)
    result = run_backtest(strat, df, config)

    conn = connect(db_path)
    run_id = save_run(conn, result)
    metrics = get_metrics(conn, run_id)
    conn.close()

    engine_metrics = {"full": result.full, "is": result.is_, "oos": result.oos}
    for scope in ("full", "is", "oos"):
        stored = next(m for m in metrics if m["scope"] == scope)
        engine = engine_metrics[scope]
        assert stored["sharpe"] == pytest.approx(engine.sharpe, abs=1e-9)
        assert stored["total_return"] == pytest.approx(engine.total_return, abs=1e-9)
        assert stored["num_trades"] == engine.num_trades


# INT-4: CLI report produces output
def test_cli_report_output(strat_and_data, db_path: str) -> None:
    import subprocess
    import sys

    strat, df = strat_and_data
    config = BacktestConfig(min_trades=0)
    result = run_backtest(strat, df, config)

    conn = connect(db_path)
    _ = save_run(conn, result)
    conn.close()

    proc = subprocess.run(
        [sys.executable, "-m", "ztb.cli", "report", "--db", db_path],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr}"
    assert "sma_cross" in proc.stdout, f"stdout={proc.stdout}"


# INT-5: CLI dashboard launches (process test — verify it imports cleanly)
def test_dashboard_imports() -> None:
    import ztb.dashboard.app  # noqa: F401
