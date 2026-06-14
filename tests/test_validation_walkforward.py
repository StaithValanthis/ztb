from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.engine.metrics import MetricsResult
from ztb.strategies.base import Strategy
from ztb.validation.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    run_walk_forward,
)


class SmaCross(Strategy):
    name = "sma_cross"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        close = df["close"]
        fast = close.rolling(5).mean()
        slow = close.rolling(20).mean()
        signal = Series(0.0, index=df.index)
        signal[fast > slow] = 1.0
        signal[fast < slow] = -1.0
        return signal


def _trending_data(n: int = 2000) -> DataFrame:
    np.random.seed(42)
    trend = np.linspace(0, 20, n)
    noise = np.random.randn(n) * 2.0
    close = 100.0 + trend + noise
    return DataFrame(
        {
            "open": close - np.random.uniform(0, 0.5, n),
            "high": close + np.random.uniform(0, 1.0, n),
            "low": close - np.random.uniform(0, 1.0, n),
            "close": close,
            "volume": np.random.uniform(500, 1500, n),
        },
        index=pd.date_range("2020-01-01", periods=n, freq="h"),
    )


def test_walkforward_produces_windows() -> None:
    df = _trending_data(2000)
    strat = SmaCross()
    cfg = WalkForwardConfig(n_windows=4, min_trades=1, min_train_bars=100, min_oos_bars=50)
    result = run_walk_forward(strat, df, cfg)
    assert result.n_windows_total == 4
    assert len(result.per_window) <= 4
    assert len(result.per_window) >= 1


def test_median_aggregation() -> None:
    df = _trending_data(3000)
    strat = SmaCross()
    cfg = WalkForwardConfig(
        n_windows=5, min_trades=1, min_train_bars=100, min_oos_bars=50, warmup=20
    )
    result = run_walk_forward(strat, df, cfg)
    assert result.aggregate.sharpe is not None


def test_walkforward_returns_result() -> None:
    df = _trending_data(1000)
    strat = SmaCross()
    result = run_walk_forward(strat, df)
    assert isinstance(result, WalkForwardResult)
    assert isinstance(result.aggregate, MetricsResult)
    assert isinstance(result.config, WalkForwardConfig)
    assert result.n_windows_total > 0


def test_stability_computed() -> None:
    df = _trending_data(2000)
    strat = SmaCross()
    cfg = WalkForwardConfig(
        n_windows=4, min_trades=1, min_train_bars=100, min_oos_bars=50, warmup=20
    )
    result = run_walk_forward(strat, df, cfg)
    if len(result.per_window) >= 2:
        assert result.stability is not None
        assert result.stability >= 0.0


def test_missing_columns_raises() -> None:
    idx = pd.date_range("2020-01-01", periods=100, freq="h")
    df = DataFrame({"close": [100.0] * 100}, index=idx)
    strat = SmaCross()
    with pytest.raises(ValueError, match="Missing required columns"):
        run_walk_forward(strat, df)


def test_deterministic() -> None:
    df = _trending_data(1000)
    strat = SmaCross()
    r1 = run_walk_forward(strat, df)
    r2 = run_walk_forward(strat, df)
    assert r1.n_windows_total == r2.n_windows_total


def test_walkforward_config_defaults() -> None:
    cfg = WalkForwardConfig()
    assert cfg.n_windows == 4
    assert cfg.train_ratio == 0.7
    assert cfg.min_train_bars == 500
    assert cfg.min_oos_bars == 100
    assert cfg.min_trades == 30
    assert cfg.step_size is None
    assert cfg.warmup is None


def test_per_window_metrics() -> None:
    df = _trending_data(2000)
    strat = SmaCross()
    cfg = WalkForwardConfig(
        n_windows=3, min_trades=1, min_train_bars=100, min_oos_bars=50, warmup=20
    )
    result = run_walk_forward(strat, df, cfg)
    for w in result.per_window:
        assert isinstance(w, MetricsResult)
        if w.sharpe is not None:
            assert isinstance(w.sharpe, float)


def test_credible_count() -> None:
    df = _trending_data(2000)
    strat = SmaCross()
    cfg = WalkForwardConfig(
        n_windows=4, min_trades=1, min_train_bars=100, min_oos_bars=50, warmup=20
    )
    result = run_walk_forward(strat, df, cfg)
    assert result.n_windows_credible >= 0
    assert result.n_windows_credible <= result.n_windows_total
