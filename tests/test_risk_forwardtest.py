from __future__ import annotations

import pandas as pd
from pandas import DataFrame, Series

from ztb.engine.forwardtest import (
    ForwardtestConfig,
    run_forwardtest,
)
from ztb.strategies.base import Strategy


class LongStrat(Strategy):
    name = "long"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(1.0, index=df.index)


class FlatStrat(Strategy):
    name = "flat"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(0.0, index=df.index)


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


def test_forwardtest_risk_enabled_default() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.risk_aware is True


def test_forwardtest_risk_disabled() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(risk_enabled=False, warmup_bars=0, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.risk_aware is False


def test_forwardtest_risk_tracks_decisions() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert len(result.risk_decisions) > 0


def test_forwardtest_risk_kill_count() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.kill_count >= 0


def test_forwardtest_risk_mean_gross_leverage() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    result = run_forwardtest(strat, df, config)
    if result.mean_gross_leverage is not None:
        assert result.mean_gross_leverage >= 0


def test_forwardtest_risk_flat_strategy() -> None:
    df = _sample_df(200)
    strat = FlatStrat()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    result = run_forwardtest(strat, df, config)
    assert result.metrics.num_trades == 0


def test_forwardtest_risk_equity_positive() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    result = run_forwardtest(strat, df, config)
    for eq in result.portfolio.equity:
        assert eq > 0


def test_forwardtest_risk_parity_no_risk() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config_no_risk = ForwardtestConfig(risk_enabled=False, warmup_bars=0, min_trades=0)
    config_risk = ForwardtestConfig(risk_enabled=True, warmup_bars=0, min_trades=0)
    result_no_risk = run_forwardtest(strat, df, config_no_risk)
    result_risk = run_forwardtest(strat, df, config_risk)
    assert result_no_risk.metrics.num_trades == result_risk.metrics.num_trades


def test_forwardtest_risk_idempotency() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = ForwardtestConfig(warmup_bars=0, min_trades=0)
    r1 = run_forwardtest(strat, df, config)
    r2 = run_forwardtest(strat, df, config)
    assert r1.metrics.num_trades == r2.metrics.num_trades
    if r1.metrics.total_return is not None and r2.metrics.total_return is not None:
        assert abs(r1.metrics.total_return - r2.metrics.total_return) < 1e-9


def test_forwardtest_risk_parity_with_backtest() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    from ztb.engine.backtest import BacktestConfig, run_backtest

    bt_config = BacktestConfig(risk_enabled=False, min_trades=0)
    bt_result = run_backtest(strat, df, bt_config)
    ft_config = ForwardtestConfig(risk_enabled=False, warmup_bars=0, min_trades=0)
    ft_result = run_forwardtest(strat, df, ft_config)
    assert ft_result.metrics.num_trades == bt_result.full.num_trades
    if ft_result.metrics.total_return is not None and bt_result.full.total_return is not None:
        assert abs(ft_result.metrics.total_return - bt_result.full.total_return) < 1e-9
