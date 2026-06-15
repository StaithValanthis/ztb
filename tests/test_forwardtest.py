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
    assert result.metrics.sufficient_sample is False


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


def test_forwardtest_metrics_not_sufficient_sample_with_few_trades() -> None:
    df = _sample_df(50)
    strat = FlatStrat()
    config = ForwardtestConfig(warmup_bars=10, min_trades=5)
    result = run_forwardtest(strat, df, config)
    assert result.metrics.sufficient_sample is False


def test_forwardtest_equity_positive() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    for eq in result.portfolio.equity:
        assert eq > 0


def test_forwardtest_idempotency() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    r1 = run_forwardtest(strat, df, config)
    r2 = run_forwardtest(strat, df, config)
    assert r1.metrics.total_return == r2.metrics.total_return
    assert r1.metrics.num_trades == r2.metrics.num_trades
    assert r1.metrics.sharpe == r2.metrics.sharpe


def test_forwardtest_decay_baseline_none() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.decay_score is None
    assert result.decay_alarm is None
    assert result.baseline_run_id is None


def test_forwardtest_decay_with_baseline() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    result2 = run_forwardtest(strat, df, config, baseline_metrics=result.metrics)
    assert result2.decay_score is not None
    assert result2.decay_score >= 0.0
    assert result2.baseline_run_id is None


def test_forwardtest_decay_score_zero_when_identical() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    same_metrics = result.metrics
    result2 = run_forwardtest(strat, df, config, baseline_metrics=same_metrics)
    assert result2.decay_score == 0.0


def test_forwardtest_decay_alarm_triggered() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    from ztb.engine.ft_decay import DecayConfig

    aggressive = DecayConfig(min_sample=0, sharpe_floor_frac=100.0, maxdd_mult=0.01)
    result2 = run_forwardtest(
        strat, df, config, baseline_metrics=result.metrics, decay_cfg=aggressive
    )
    assert result2.decay_alarm is not None
    assert result2.decay_alarm[0] is True


def test_forwardtest_decay_alarm_suppressed() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=50, min_trades=0)
    result = run_forwardtest(strat, df, config)
    from ztb.engine.ft_decay import DecayConfig

    loose = DecayConfig(min_sample=0, sharpe_floor_frac=0.0, maxdd_mult=100.0)
    result2 = run_forwardtest(strat, df, config, baseline_metrics=result.metrics, decay_cfg=loose)
    assert result2.decay_alarm is not None
    assert result2.decay_alarm[0] is False


def test_forwardtest_parity_with_backtest_long() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    from ztb.engine.backtest import BacktestConfig, run_backtest

    bt_config = BacktestConfig(min_trades=0)
    bt_result = run_backtest(strat, df, bt_config)
    ft_config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    ft_result = run_forwardtest(strat, df, ft_config)
    assert abs(ft_result.metrics.num_trades - bt_result.full.num_trades) <= 1
    if ft_result.metrics.total_return is not None and bt_result.full.total_return is not None:
        assert abs(ft_result.metrics.total_return - bt_result.full.total_return) < 1e-9


def test_forwardtest_parity_with_backtest_sma_cross() -> None:
    from ztb.strategies.registry import get as get_strat

    cls = get_strat("sma_cross")
    strat = cls()
    strat.symbols = ["TEST"]
    df = _sample_df(500)
    from ztb.engine.backtest import BacktestConfig, run_backtest

    bt_config = BacktestConfig(min_trades=0)
    bt_result = run_backtest(strat, df, bt_config)
    ft_config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    ft_result = run_forwardtest(strat, df, ft_config)
    assert abs(ft_result.metrics.num_trades - bt_result.full.num_trades) <= 1
    if ft_result.metrics.total_return is not None and bt_result.full.total_return is not None:
        assert abs(ft_result.metrics.total_return - bt_result.full.total_return) < 1e-9


def test_forwardtest_utc_timestamps() -> None:
    df = DataFrame(
        {
            "open": [100.0] * 50,
            "high": [101.0] * 50,
            "low": [99.0] * 50,
            "close": [100.0] * 50,
            "volume": [1000.0] * 50,
        },
        index=pd.date_range("2020-01-01", periods=50, freq="h", tz="UTC"),
    )
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    result = run_forwardtest(strat, df, config)
    for ts in result.portfolio.timestamps:
        assert ts.tz is not None
        assert str(ts.tz) == "UTC"


def _make_loader(pool: DataFrame):
    def loader(symbol: str, timeframe: str, *, start=None, end=None, **kwargs):
        return pool.loc[start:end]
    return loader


def _sma_cross_strategy() -> Strategy:
    from ztb.strategies.registry import get as get_strat

    cls = get_strat("sma_cross")
    strat = cls()
    strat.symbols = ["TEST"]
    return strat


def test_forwardtest_with_start_has_trades() -> None:
    pool = _sample_df(200)
    start = pool.index[156]
    data_slice = pool.loc[start:]
    assert len(data_slice) == 44
    strat = _sma_cross_strategy()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    loader = _make_loader(pool)
    result = run_forwardtest(strat, data_slice, config, loader=loader)
    assert result.metrics.num_trades >= 1



