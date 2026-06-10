from __future__ import annotations

import pandas as pd
from pandas import DataFrame, Series

from ztb.engine.backtest import BacktestConfig, BacktestResult, run_backtest
from ztb.engine.forwardtest import ForwardtestConfig, run_forwardtest
from ztb.risk.models import RiskConfig
from ztb.strategies.base import Strategy


class LongStrat(Strategy):
    name = "long"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(1.0, index=df.index)


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


def _gap_down_df(
    n: int = 200, gap_idx: int = 100, gap_pct: float = -0.50
) -> DataFrame:
    prices = [100.0 + i * 0.1 for i in range(n)]
    for j in range(gap_idx, n):
        prices[j] = prices[gap_idx - 1] * (1.0 + gap_pct)
    return DataFrame(
        {
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": [1000.0] * n,
        },
        index=pd.date_range("2020-01-01", periods=n, freq="h"),
    )


def test_integration_risk_enabled_flag() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    cfg_no = BacktestConfig(risk_enabled=False, min_trades=0)
    cfg_yes = BacktestConfig(risk_enabled=True, min_trades=0)
    r_no = run_backtest(strat, df, cfg_no)
    r_yes = run_backtest(strat, df, cfg_yes)
    assert r_no.risk_aware is False
    assert r_yes.risk_aware is True
    assert len(r_yes.risk_decisions) > 0


def test_integration_idempotency() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    rc = RiskConfig(account_killswitch_dd=0.30)
    cfg = BacktestConfig(risk_enabled=True, risk_config=rc, min_trades=0)
    r1 = run_backtest(strat, df, cfg)
    r2 = run_backtest(strat, df, cfg)
    assert r1.full.num_trades == r2.full.num_trades
    if r1.full.total_return is not None and r2.full.total_return is not None:
        assert abs(r1.full.total_return - r2.full.total_return) < 1e-9
    assert len(r1.risk_decisions) == len(r2.risk_decisions)
    for d1, d2 in zip(r1.risk_decisions, r2.risk_decisions, strict=True):
        assert d1["action"] == d2["action"]


def test_integration_wide_thresholds_match_no_risk() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    rc = RiskConfig(
        max_portfolio_dd=1.0,
        account_killswitch_dd=1.0,
        max_leverage=100.0,
        max_position_pct=1.0,
        max_heat=100.0,
    )
    cfg_no = BacktestConfig(risk_enabled=False, min_trades=0)
    cfg_yes = BacktestConfig(risk_enabled=True, risk_config=rc, min_trades=0)
    r_no = run_backtest(strat, df, cfg_no)
    r_yes = run_backtest(strat, df, cfg_yes)
    assert abs(r_no.full.total_return - r_yes.full.total_return) < 1e-9
    assert r_no.full.num_trades == r_yes.full.num_trades


def test_integration_risk_decisions_fields() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    cfg = BacktestConfig(risk_enabled=True, min_trades=0)
    result = run_backtest(strat, df, cfg)
    assert len(result.risk_decisions) > 0
    decision = result.risk_decisions[0]
    assert "action" in decision
    assert "reason" in decision
    assert "timestamp" in decision
    assert "current_dd" in decision
    assert "current_heat" in decision


def test_integration_mean_gross_leverage_non_negative() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    cfg = BacktestConfig(risk_enabled=True, min_trades=0)
    result = run_backtest(strat, df, cfg)
    if result.mean_gross_leverage is not None:
        assert result.mean_gross_leverage >= 0.0


def test_integration_kill_switch_triggers_on_massive_drop() -> None:
    n = 200
    prices = [100.0 + i * 0.2 for i in range(n // 2)]
    crash_price = prices[-1] * 0.05
    prices.extend([crash_price] * (n - len(prices)))
    df = DataFrame(
        {
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": [1000.0] * n,
        },
        index=pd.date_range("2020-01-01", periods=n, freq="h"),
    )
    strat = LongStrat()
    rc = RiskConfig(account_killswitch_dd=0.05, max_portfolio_dd=0.50)
    cfg = BacktestConfig(
        risk_enabled=True, risk_config=rc, min_trades=0, initial_cash=200.0
    )
    result = run_backtest(strat, df, cfg)
    assert result.risk_aware
    halt_actions = [d for d in result.risk_decisions if d["action"] == "halt"]
    assert len(halt_actions) > 0


def test_integration_backtest_forwardtest_risk_parity() -> None:
    df = _sample_df(200)
    strat = LongStrat()
    bt = run_backtest(strat, df, BacktestConfig(risk_enabled=True, min_trades=0))
    ft = run_forwardtest(
        strat, df, ForwardtestConfig(warmup_bars=0, min_trades=0)
    )
    assert bt.risk_aware
    assert ft.risk_aware
    assert bt.full.num_trades == ft.metrics.num_trades


def test_integration_adversarial_gap_down_does_not_crash() -> None:
    df = _gap_down_df(500, gap_idx=200, gap_pct=-0.60)
    strat = LongStrat()
    rc = RiskConfig(account_killswitch_dd=0.15)
    cfg = BacktestConfig(risk_enabled=True, risk_config=rc, min_trades=0)
    result = run_backtest(strat, df, cfg)
    assert isinstance(result, BacktestResult)
    assert result.risk_aware
    assert len(result.risk_decisions) > 0
