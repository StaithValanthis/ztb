from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.engine.forwardtest import (
    ForwardtestConfig,
    ForwardtestResult,
    run_forwardtest,
)
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


class ShortStrat(Strategy):
    name = "short"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(-0.5, index=df.index)


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


def test_forwardtest_returns_forwardtestresult() -> None:
    df = _sample_df()
    strat = FlatStrat()
    result = run_forwardtest(strat, df, ForwardtestConfig(warmup_bars=50))
    assert isinstance(result, ForwardtestResult)


def test_forwardtest_flat_strategy() -> None:
    df = _sample_df()
    strat = FlatStrat()
    result = run_forwardtest(strat, df, ForwardtestConfig(warmup_bars=50))
    assert result.metrics.num_trades == 0
    assert result.metrics.credible is False


def test_forwardtest_long_strategy_has_trades() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.metrics.num_trades >= 1


def test_forwardtest_short_strategy_has_trades() -> None:
    df = _sample_df(200)
    strat = ShortStrat()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.metrics.num_trades >= 1


def test_forwardtest_missing_columns_raises() -> None:
    df = DataFrame({"a": [1, 2, 3]})
    strat = FlatStrat()
    with pytest.raises(ValueError, match="Missing required columns"):
        run_forwardtest(strat, df)


def test_forwardtest_nan_signals_raises() -> None:
    df = _sample_df()
    strat = NaNStrat()
    with pytest.raises(StrategyError, match="NaN"):
        run_forwardtest(strat, df)


def test_forwardtest_strategy_name_in_result() -> None:
    df = _sample_df()
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.strategy_name == "long"


def test_forwardtest_equity_curve_length() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    result = run_forwardtest(strat, df, ForwardtestConfig(warmup_bars=50, min_trades=0))
    assert len(result.portfolio.equity) == 200


def test_forwardtest_trades_list() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    result = run_forwardtest(strat, df, ForwardtestConfig(warmup_bars=50, min_trades=0))
    assert isinstance(result.trades, list)


def test_forwardtest_warmup_bars_respected() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.warmup_bars >= 50


class LongAfterWarmupStrat(Strategy):
    name = "long_after_warmup"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 30

    def generate_signals(self, df: DataFrame) -> Series:
        s = Series(0.0, index=df.index)
        s.iloc[100:] = 1.0
        return s


def test_forwardtest_only_forward_trades_returned() -> None:
    df = _sample_df(200)
    strat = LongAfterWarmupStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert len(result.trades) > 0
    for t in result.trades:
        ts_idx = next(i for i, ts in enumerate(result.portfolio.timestamps) if ts == t["timestamp"])
        assert ts_idx >= 50, f"Trade at idx {ts_idx} is before warmup"


def test_forwardtest_warmup_uses_strategy_warmup() -> None:
    class StratWithWarmup(Strategy):
        name = "warmup_test"
        symbols = []
        timeframe = "60"
        params = {}
        warmup = 30

        def generate_signals(self, df: DataFrame) -> Series:
            return Series(1.0, index=df.index)

    df = _sample_df(200)
    strat = StratWithWarmup()
    config = ForwardtestConfig(warmup_bars=10, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.warmup_bars >= 30


def test_forwardtest_default_config() -> None:
    df = _sample_df()
    strat = FlatStrat()
    result = run_forwardtest(strat, df)
    assert isinstance(result, ForwardtestResult)


def test_forwardtest_custom_config() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(
        initial_cash=50_000.0,
        commission=0.001,
        slippage=0.002,
        warmup_bars=0,
        min_trades=0,
    )
    result = run_forwardtest(strat, df, config)
    assert result.metrics.num_trades >= 1


def test_forwardtest_total_bars() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.total_bars == 200


def test_forwardtest_parameters_in_result() -> None:
    df = _sample_df()
    strat = FlatStrat()
    result = run_forwardtest(strat, df, ForwardtestConfig(warmup_bars=50))
    assert isinstance(result.parameters, dict)


def test_sma_cross_forwardtest() -> None:
    from ztb.strategies.registry import get as get_strat

    cls = get_strat("sma_cross")
    strat = cls()
    strat.symbols = ["TEST"]
    df = _sample_df(200)
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert isinstance(result.metrics.total_return, (float, type(None)))


def test_forwardtest_warmup_half_data_when_too_large() -> None:
    df = _sample_df(20)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=100, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.warmup_bars == 10


def test_forwardtest_metrics_not_credible_with_few_trades() -> None:
    df = _sample_df(50)
    strat = FlatStrat()
    config = ForwardtestConfig(warmup_bars=10, min_trades=5)
    result = run_forwardtest(strat, df, config)
    assert result.metrics.credible is False


def test_forwardtest_equity_positive() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    for eq in result.portfolio.equity:
        assert eq > 0
