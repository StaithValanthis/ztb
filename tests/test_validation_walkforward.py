from __future__ import annotations

import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.strategies.base import Strategy
from ztb.validation.walkforward import (
    WalkforwardConfig,
    WalkforwardResult,
    WalkforwardWindow,
    _make_windows,
    run_walkforward,
)


class FlatStrat(Strategy):
    name = "flat"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(0.0, index=df.index)


class LongStrat(Strategy):
    name = "long"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(1.0, index=df.index)


class ShortStrat(Strategy):
    name = "short"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(-0.5, index=df.index)


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


def test_make_windows_returns_list() -> None:
    windows = _make_windows(1000, WalkforwardConfig())
    assert isinstance(windows, list)
    assert len(windows) > 0
    for w in windows:
        assert "train_start" in w
        assert "train_end" in w
        assert "test_start" in w
        assert "test_end" in w


def test_make_windows_min_bars() -> None:
    windows = _make_windows(50, WalkforwardConfig(min_train_bars=100, min_test_bars=30))
    assert len(windows) >= 0


def test_walkforward_returns_result() -> None:
    df = _sample_df(500)
    strat = FlatStrat()
    result = run_walkforward(strat, df)
    assert isinstance(result, WalkforwardResult)


def test_walkforward_flat_strategy() -> None:
    df = _sample_df(500)
    strat = FlatStrat()
    result = run_walkforward(strat, df)
    assert result.n_windows > 0
    for w in result.windows:
        assert w.test_result.oos.num_trades == 0


def test_walkforward_long_strategy() -> None:
    df = _sample_df(1000)
    strat = LongStrat()
    cfg = WalkforwardConfig(n_windows=2, min_trades=0, min_test_bars=50, train_ratio=0.5)
    result = run_walkforward(strat, df, cfg)
    assert result.n_windows > 0
    assert result.avg_oos_sharpe is not None


def test_walkforward_missing_columns() -> None:
    df = DataFrame({"close": [100.0] * 100}, index=pd.date_range("2020-01-01", periods=100, freq="h"))
    strat = FlatStrat()
    with pytest.raises(ValueError, match="Missing required columns"):
        run_walkforward(strat, df)


def test_walkforward_consistency() -> None:
    df = _sample_df(500)
    strat = FlatStrat()
    result1 = run_walkforward(strat, df)
    result2 = run_walkforward(strat, df)
    assert result1.n_windows == result2.n_windows
    assert result1.avg_oos_sharpe == result2.avg_oos_sharpe


def test_walkforward_result_properties() -> None:
    df = _sample_df(500)
    strat = LongStrat()
    result = run_walkforward(strat, df)
    assert result.strategy_name == "long"
    assert result.symbol == ""
    assert result.timeframe == "60"
    assert result.total_bars == 500
    assert 0.0 <= result.sharpe_consistency
    assert 0.0 <= result.return_consistency
    assert isinstance(result.all_windows_valid, bool)


def test_walkforward_window_dataclass() -> None:
    w = WalkforwardWindow(
        window_idx=0,
        train_start=0,
        train_end=100,
        test_start=100,
        test_end=200,
        train_result=None,
        test_result=None,
        train_duration_bars=100,
        test_duration_bars=100,
    )
    assert w.window_idx == 0
    assert w.train_duration_bars == 100
    assert w.test_duration_bars == 100


def test_walkforward_with_risk() -> None:
    df = _sample_df(500)
    strat = LongStrat()
    cfg = WalkforwardConfig(risk_enabled=True, n_windows=2)
    result = run_walkforward(strat, df, cfg)
    assert result.n_windows > 0


def test_walkforward_custom_n_windows() -> None:
    df = _sample_df(500)
    strat = FlatStrat()
    cfg = WalkforwardConfig(n_windows=3)
    result = run_walkforward(strat, df, cfg)
    assert result.n_windows <= 3


def test_walkforward_short_strategy() -> None:
    df = _sample_df(500)
    strat = ShortStrat()
    result = run_walkforward(strat, df)
    assert result.n_windows > 0
    for w in result.windows:
        assert w.test_result.oos.num_trades > 0
