from __future__ import annotations

import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.engine.metrics import MetricsResult
from ztb.strategies.base import Strategy
from ztb.validation.scoring import (
    Scorecard,
    _consistency_score,
    _drawdown_score,
    _sharpe_score,
    _walkforward_score,
    compute_scorecard,
)
from ztb.validation.walkforward import WalkforwardConfig, WalkforwardResult, run_walkforward


class FlatStrat(Strategy):
    name = "flat"
    symbols = []
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


def test_sharpe_score_none() -> None:
    assert _sharpe_score(None) == 0.0


def test_sharpe_score_zero() -> None:
    assert _sharpe_score(0.0) == 0.0


def test_sharpe_score_negative() -> None:
    assert _sharpe_score(-1.0) == 0.0


def test_sharpe_score_positive() -> None:
    assert _sharpe_score(1.5) == 0.5


def test_sharpe_score_capped() -> None:
    assert _sharpe_score(5.0) == 1.0


def test_drawdown_score_none() -> None:
    assert _drawdown_score(None) == 0.0


def test_drawdown_score_no_dd() -> None:
    assert _drawdown_score(0.0) == 0.0


def test_drawdown_score_small() -> None:
    assert _drawdown_score(-0.03) == 1.0


def test_drawdown_score_medium() -> None:
    assert _drawdown_score(-0.15) == 0.5


def test_drawdown_score_large() -> None:
    assert _drawdown_score(-0.50) == 0.0


def test_consistency_score_no_wf() -> None:
    assert _consistency_score(None) == 0.5


def test_consistency_score_one_window() -> None:
    wf = WalkforwardResult(
        strategy_name="test", symbol="BTC", timeframe="60",
        windows=[], n_windows=1, total_bars=100, config=WalkforwardConfig(),
    )
    assert _consistency_score(wf) == 0.5


def test_walkforward_score_none() -> None:
    assert _walkforward_score(None) == 0.0


def test_scorecard_no_metrics() -> None:
    sc = compute_scorecard(oos_metrics=None)
    assert isinstance(sc, Scorecard)
    assert sc.overall_score == 0.075  # consistency defaults to 0.5 * 0.15 weight


def test_scorecard_with_metrics() -> None:
    metrics = MetricsResult(
        total_return=0.1, sharpe=1.5, sortino=2.0,
        max_drawdown=-0.05, max_drawdown_duration=5,
        num_trades=50, profit_factor=1.5, win_rate=0.55,
        turnover=100.0, exposure_time=500.0, sufficient_sample=True,
    )
    returns = pd.Series([0.001] * 500 + [-0.001] * 100)
    sc = compute_scorecard(oos_metrics=metrics, returns_series=returns)
    assert isinstance(sc, Scorecard)
    assert sc.overall_score > 0.0
    assert sc.oos_sharpe_score > 0.0


def test_scorecard_with_walkforward() -> None:
    df = _sample_df(500)
    strat = FlatStrat()
    wf = run_walkforward(strat, df)
    metrics = MetricsResult(
        total_return=0.05, sharpe=0.8, sortino=1.0,
        max_drawdown=-0.03, max_drawdown_duration=2,
        num_trades=20, profit_factor=1.2, win_rate=0.6,
        turnover=50.0, exposure_time=400.0, sufficient_sample=True,
    )
    sc = compute_scorecard(oos_metrics=metrics, walkforward_result=wf)
    assert sc.walkforward_score >= 0.0
    assert sc.consistency_score >= 0.0
    assert sc.overall_score >= 0.0


def test_scorecard_range() -> None:
    metrics = MetricsResult(
        total_return=0.2, sharpe=2.0, sortino=3.0,
        max_drawdown=-0.02, max_drawdown_duration=1,
        num_trades=100, profit_factor=2.0, win_rate=0.65,
        turnover=200.0, exposure_time=1000.0, sufficient_sample=True,
    )
    returns = pd.Series([0.002] * 1000 + [-0.001] * 200)
    sc = compute_scorecard(oos_metrics=metrics, returns_series=returns, num_trials=1)
    assert 0.0 <= sc.overall_score <= 1.0
    for s in [sc.oos_sharpe_score, sc.dsr_score, sc.drawdown_score]:
        assert 0.0 <= s <= 1.0


def test_scorecard_deterministic() -> None:
    metrics = MetricsResult(
        total_return=0.1, sharpe=1.2, sortino=1.8,
        max_drawdown=-0.05, max_drawdown_duration=3,
        num_trades=60, profit_factor=1.4, win_rate=0.58,
        turnover=120.0, exposure_time=600.0, sufficient_sample=True,
    )
    returns = pd.Series([0.001] * 600 + [-0.001] * 100)
    sc1 = compute_scorecard(oos_metrics=metrics, returns_series=returns)
    sc2 = compute_scorecard(oos_metrics=metrics, returns_series=returns)
    assert sc1.overall_score == sc2.overall_score
    assert sc1.dsr_score == sc2.dsr_score
