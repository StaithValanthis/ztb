from __future__ import annotations

import pandas as pd
from pandas import DataFrame, Series

from ztb.engine.backtest import BacktestConfig, BacktestResult, run_backtest
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


def test_backtest_risk_enabled_flag() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = BacktestConfig(risk_enabled=True, min_trades=0)
    result = run_backtest(strat, df, config)
    assert isinstance(result, BacktestResult)
    assert result.risk_aware is True


def test_backtest_risk_disabled_default() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = BacktestConfig(min_trades=0)
    result = run_backtest(strat, df, config)
    assert result.risk_aware is False


def test_backtest_risk_tracks_decisions() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = BacktestConfig(risk_enabled=True, min_trades=0)
    result = run_backtest(strat, df, config)
    assert len(result.risk_decisions) > 0


def test_backtest_risk_kill_count() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = BacktestConfig(risk_enabled=True, min_trades=0)
    result = run_backtest(strat, df, config)
    assert result.kill_count >= 0


def test_backtest_risk_mean_gross_leverage() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = BacktestConfig(risk_enabled=True, min_trades=0)
    result = run_backtest(strat, df, config)
    if result.mean_gross_leverage is not None:
        assert result.mean_gross_leverage >= 0


def test_backtest_risk_enabled_does_not_crash() -> None:
    df = _sample_df(200)
    strat = FlatStrat()
    config = BacktestConfig(risk_enabled=True, min_trades=0)
    result = run_backtest(strat, df, config)
    assert result.full.num_trades == 0


def test_backtest_risk_equity_positive() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = BacktestConfig(risk_enabled=True, min_trades=0)
    result = run_backtest(strat, df, config)
    for eq in result.portfolio.equity:
        assert eq > 0


def test_backtest_risk_parity_without_risk() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config_no_risk = BacktestConfig(risk_enabled=False, min_trades=0)
    config_risk = BacktestConfig(risk_enabled=True, min_trades=0)
    result_no_risk = run_backtest(strat, df, config_no_risk)
    result_risk = run_backtest(strat, df, config_risk)
    assert result_no_risk.full.num_trades == result_risk.full.num_trades


def test_backtest_risk_idempotency() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    config = BacktestConfig(risk_enabled=True, min_trades=0)
    r1 = run_backtest(strat, df, config)
    r2 = run_backtest(strat, df, config)
    assert r1.full.num_trades == r2.full.num_trades
    if r1.full.total_return is not None and r2.full.total_return is not None:
        assert abs(r1.full.total_return - r2.full.total_return) < 1e-9
    if r1.full.sharpe is not None and r2.full.sharpe is not None:
        assert abs(r1.full.sharpe - r2.full.sharpe) < 1e-9
