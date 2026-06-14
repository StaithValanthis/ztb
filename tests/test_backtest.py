from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.engine.backtest import BacktestConfig, BacktestResult, run_backtest
from ztb.strategies.base import Strategy, StrategyError


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


class WarmupViolationStrat(Strategy):
    name = "warmup_violation"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 10

    def generate_signals(self, df: DataFrame) -> Series:
        s = Series(0.0, index=df.index)
        s.iloc[5] = 1.0
        return s


class NaNStrat(Strategy):
    name = "nan"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        s = Series(0.0, index=df.index)
        s.iloc[5] = np.nan
        return s


class ShortStrat(Strategy):
    name = "short"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(-0.5, index=df.index)


def _sample_df(n: int = 200) -> DataFrame:
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


def test_backtest_returns_backtestresult() -> None:
    df = _sample_df()
    strat = FlatStrat()
    result = run_backtest(strat, df)
    assert isinstance(result, BacktestResult)


def test_flat_strategy() -> None:
    df = _sample_df()
    strat = FlatStrat()
    result = run_backtest(strat, df)
    assert result.full.num_trades == 0
    assert result.full.sufficient_sample is False


def test_long_strategy_has_trades() -> None:
    df = _sample_df()
    strat = LongStrat()
    config = BacktestConfig(min_trades=0)
    result = run_backtest(strat, df, config)
    assert result.full.num_trades >= 1
    assert result.full.total_return is not None and result.full.total_return > 0


def test_short_strategy_has_trades() -> None:
    df = _sample_df()
    strat = ShortStrat()
    config = BacktestConfig(min_trades=0)
    result = run_backtest(strat, df, config)
    assert result.full.num_trades >= 1


def test_missing_columns_raises() -> None:
    df = DataFrame({"a": [1, 2, 3]})
    strat = FlatStrat()
    with pytest.raises(ValueError, match="Missing required columns"):
        run_backtest(strat, df)


def test_nan_signals_raises() -> None:
    df = _sample_df()
    strat = NaNStrat()
    with pytest.raises(StrategyError, match="NaN"):
        run_backtest(strat, df)


def test_warmup_violation_raises() -> None:
    df = _sample_df()
    strat = WarmupViolationStrat()
    with pytest.raises(StrategyError, match="warmup"):
        run_backtest(strat, df)


def test_min_bars_below_threshold() -> None:
    df = _sample_df(10)
    strat = FlatStrat()
    config = BacktestConfig(min_bars=10)
    result = run_backtest(strat, df, config)
    assert isinstance(result, BacktestResult)


def test_custom_config() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = BacktestConfig(initial_cash=50_000.0, commission=0.001, slippage=0.002)
    result = run_backtest(strat, df, config)
    assert result.full.num_trades >= 1


def test_is_oos_split() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = BacktestConfig(min_trades=0)
    result = run_backtest(strat, df, config)
    assert result.is_ is not None
    assert result.oos is not None


def test_strategy_name_in_result() -> None:
    df = _sample_df()
    strat = LongStrat()
    config = BacktestConfig(min_trades=0)
    result = run_backtest(strat, df, config)
    assert result.strategy_name == "long"


def test_equity_curve_length() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    result = run_backtest(strat, df)
    assert len(result.portfolio.equity) == 200


def test_trades_list() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    result = run_backtest(strat, df)
    assert isinstance(result.trades, list)


def test_sma_cross_backtest() -> None:
    from ztb.strategies.registry import get as get_strat

    cls = get_strat("sma_cross")
    strat = cls()
    strat.symbols = ["TEST"]
    df = _sample_df(200)
    config = BacktestConfig(min_trades=0)
    result = run_backtest(strat, df, config)
    assert isinstance(result.full.total_return, (float, type(None)))
