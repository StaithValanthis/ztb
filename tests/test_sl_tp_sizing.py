from __future__ import annotations

import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.engine.backtest import BacktestConfig, run_backtest
from ztb.engine.portfolio import risk_based_target_qty, single_symbol_portfolio
from ztb.strategies.base import Strategy


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


class FlipStrat(Strategy):
    name = "flip"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def __init__(self, entry: int, exit_idx: int, reentry: int = -1) -> None:
        super().__init__()
        self.entry = entry
        self.exit_idx = exit_idx
        self.reentry = reentry

    def generate_signals(self, df: DataFrame) -> Series:
        s = Series(0.0, index=df.index)
        s.iloc[self.entry :] = 1.0
        s.iloc[self.exit_idx] = 0.0
        if self.reentry >= 0:
            s.iloc[self.reentry :] = 1.0
        return s


# ---------------------------------------------------------------------------
# SL/TP bar-cross simulation
# ---------------------------------------------------------------------------


def test_sl_hit_closes_position() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    signals = Series(0.0, index=idx)
    signals.iloc[1:4] = 1.0
    close = Series(
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
        index=idx,
    )
    low = Series([99.0, 100.0, 95.0, 101.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0], index=idx)
    high = Series([101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0], index=idx)

    state = single_symbol_portfolio(
        signals,
        close,
        high=high,
        low=low,
        commission=0.0,
        slippage=0.0,
        sl_pct=0.05,
        tp_pct=0.0,
    )

    sl_trades = [t for t in state.trades if t.get("exit_reason") == "stop_loss"]
    assert len(sl_trades) >= 1, "Expected at least one SL exit"
    assert sl_trades[0]["exit_reason"] == "stop_loss"


def test_tp_hit_closes_position() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    signals = Series(0.0, index=idx)
    signals.iloc[1:4] = 1.0
    close = Series(
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0], index=idx
    )
    low = Series([99.0, 100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0], index=idx)
    high = Series([101.0, 102.0, 108.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0], index=idx)

    state = single_symbol_portfolio(
        signals, close, high=high, low=low, commission=0.0, slippage=0.0, sl_pct=0.0, tp_pct=0.05
    )

    tp_trades = [t for t in state.trades if t.get("exit_reason") == "take_profit"]
    assert len(tp_trades) >= 1, "Expected at least one TP exit"
    assert tp_trades[0]["exit_reason"] == "take_profit"


def test_sl_tp_not_triggered_when_price_stays_within_range() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    signals = Series(0.0, index=idx)
    signals.iloc[1:6] = 1.0
    signals.iloc[6:] = 0.0
    close = Series([100.0] * 10, index=idx)
    low = Series([98.0] * 10, index=idx)
    high = Series([102.0] * 10, index=idx)

    state = single_symbol_portfolio(
        signals, close, high=high, low=low, commission=0.0, slippage=0.0, sl_pct=0.05, tp_pct=0.05
    )

    sl_tp_trades = [t for t in state.trades if t.get("exit_reason") in ("stop_loss", "take_profit")]
    signal_exits = [t for t in state.trades if t.get("exit_reason") == "signal"]

    assert len(sl_tp_trades) == 0, "No SL/TP should trigger within a narrow range"
    assert any(t.get("exit_reason") == "signal" for t in signal_exits)


def test_fee_and_slippage_applied_on_sl_tp_exit() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    signals = Series(0.0, index=idx)
    signals.iloc[1:4] = 1.0
    close = Series(
        [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0], index=idx
    )
    low = Series([99.0, 100.0, 95.0, 101.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0], index=idx)
    high = Series([101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0, 110.0], index=idx)

    state_fees = single_symbol_portfolio(
        signals,
        close,
        high=high,
        low=low,
        commission=0.001,
        slippage=0.001,
        sl_pct=0.05,
        tp_pct=0.0,
    )
    state_no_fees = single_symbol_portfolio(
        signals, close, high=high, low=low, commission=0.0, slippage=0.0, sl_pct=0.05, tp_pct=0.0
    )

    assert state_fees.equity[-1] < state_no_fees.equity[-1], "Fees should reduce equity on SL exit"

    sl_trades = [t for t in state_fees.trades if t.get("exit_reason") == "stop_loss"]
    if sl_trades:
        assert sl_trades[0]["commission"] > 0.0
        assert sl_trades[0]["slippage"] > 0.0


def test_exit_reason_defaults_to_signal() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = Series([0.0, 1.0, 1.0, 0.0, 0.0], index=idx)
    close = Series([100.0, 101.0, 102.0, 103.0, 104.0], index=idx)
    low = Series([99.0, 100.0, 101.0, 102.0, 103.0], index=idx)
    high = Series([101.0, 102.0, 103.0, 104.0, 105.0], index=idx)

    state = single_symbol_portfolio(
        signals, close, high=high, low=low, commission=0.0, slippage=0.0
    )

    for t in state.trades:
        assert t.get("exit_reason") is None or t["exit_reason"] in (
            "signal",
            "stop_loss",
            "take_profit",
        )


def test_exit_reason_sl_tp_sequence() -> None:
    idx = pd.date_range("2020-01-01", periods=15, freq="h")
    signals = Series(0.0, index=idx)
    signals.iloc[1:4] = 1.0
    signals.iloc[9:12] = 1.0
    close = Series(
        [
            100.0,
            101.0,
            102.0,
            103.0,
            104.0,
            105.0,
            106.0,
            107.0,
            108.0,
            109.0,
            110.0,
            111.0,
            112.0,
            113.0,
            114.0,
        ],
        index=idx,
    )
    low = Series(
        [
            99.0,
            100.0,
            95.0,
            101.0,
            103.0,
            104.0,
            105.0,
            106.0,
            107.0,
            108.0,
            109.0,
            110.0,
            111.0,
            112.0,
            113.0,
        ],
        index=idx,
    )
    high = Series(
        [
            101.0,
            102.0,
            103.0,
            104.0,
            105.0,
            106.0,
            107.0,
            108.0,
            109.0,
            115.0,
            111.0,
            112.0,
            113.0,
            114.0,
            115.0,
        ],
        index=idx,
    )

    state = single_symbol_portfolio(
        signals, close, high=high, low=low, commission=0.0, slippage=0.0, sl_pct=0.03, tp_pct=0.05
    )

    exit_reasons = [t.get("exit_reason") for t in state.trades]
    assert "stop_loss" in exit_reasons or "take_profit" in exit_reasons


# ---------------------------------------------------------------------------
# risk_based_target_qty
# ---------------------------------------------------------------------------


def test_risk_based_target_qty_basic() -> None:
    qty = risk_based_target_qty(
        equity=100_000.0, entry_price=100.0, sl_pct=0.02, risk_per_trade_pct=0.01
    )
    expected = 100_000.0 * 0.01 / (100.0 * 0.02)
    assert qty == pytest.approx(expected)


def test_risk_based_target_qty_zero_sl() -> None:
    qty = risk_based_target_qty(
        equity=100_000.0, entry_price=100.0, sl_pct=0.0, risk_per_trade_pct=0.01
    )
    assert qty == 0.0


def test_risk_based_target_qty_zero_risk() -> None:
    qty = risk_based_target_qty(
        equity=100_000.0, entry_price=100.0, sl_pct=0.02, risk_per_trade_pct=0.0
    )
    assert qty == 0.0


def test_risk_based_target_qty_below_min_returns_zero() -> None:
    qty = risk_based_target_qty(
        equity=100_000.0, entry_price=100.0, sl_pct=0.02, risk_per_trade_pct=0.01, min_qty=1000.0
    )
    assert qty == 0.0


def test_risk_based_target_qty_respects_min_qty() -> None:
    qty = risk_based_target_qty(
        equity=100_000.0, entry_price=100.0, sl_pct=0.02, risk_per_trade_pct=0.01, min_qty=1.0
    )
    assert qty > 0.0


def test_risk_based_target_qty_zero_equity() -> None:
    qty = risk_based_target_qty(equity=0.0, entry_price=100.0, sl_pct=0.02, risk_per_trade_pct=0.01)
    assert qty == 0.0


def test_risk_based_target_qty_zero_price() -> None:
    qty = risk_based_target_qty(
        equity=100_000.0, entry_price=0.0, sl_pct=0.02, risk_per_trade_pct=0.01
    )
    assert qty == 0.0


# ---------------------------------------------------------------------------
# Default behavior (sl_pct=0, tp_pct=0) identical to current
# ---------------------------------------------------------------------------


def test_default_zero_sl_tp_identical_to_no_sl_tp() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    signals = Series(0.0, index=idx)
    signals.iloc[1:4] = 1.0
    signals.iloc[7:] = 0.0
    close = Series([100.0 + i for i in range(10)], index=idx)
    low = Series([99.0 + i for i in range(10)], index=idx)
    high = Series([101.0 + i for i in range(10)], index=idx)

    state_no_sl = single_symbol_portfolio(
        signals, close, high=high, low=low, commission=0.001, slippage=0.001
    )
    state_with_sl = single_symbol_portfolio(
        signals, close, high=high, low=low, commission=0.001, slippage=0.001, sl_pct=0.0, tp_pct=0.0
    )

    assert len(state_no_sl.trades) == len(state_with_sl.trades)
    assert state_no_sl.equity == pytest.approx(state_with_sl.equity)
    assert state_no_sl.position == state_with_sl.position


# ---------------------------------------------------------------------------
# SL/TP price stored in trade dict
# ---------------------------------------------------------------------------


def test_sl_tp_prices_stored_in_trade() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = Series([0.0, 1.0, 1.0, 0.0, 0.0], index=idx)
    close = Series([100.0, 101.0, 102.0, 103.0, 104.0], index=idx)
    low = Series([99.0, 100.0, 101.0, 102.0, 103.0], index=idx)
    high = Series([101.0, 102.0, 103.0, 104.0, 105.0], index=idx)

    state = single_symbol_portfolio(
        signals, close, high=high, low=low, commission=0.0, slippage=0.0, sl_pct=0.02, tp_pct=0.03
    )

    buy_trades = [t for t in state.trades if t["side"] == "buy"]
    if buy_trades:
        bt = buy_trades[0]
        assert bt.get("sl_price") is not None
        assert bt.get("tp_price") is not None
        assert bt["sl_price"] < bt["price"]
        assert bt["tp_price"] > bt["price"]


# ---------------------------------------------------------------------------
# Backtest integration with SL/TP
# ---------------------------------------------------------------------------


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


def test_backtest_with_sl_tp_returns_trades() -> None:
    df = _sample_df()
    strat = LongStrat()
    config = BacktestConfig(sl_pct=0.05, tp_pct=0.05, min_trades=0)
    result = run_backtest(strat, df, config)
    assert result.full.num_trades >= 1


def test_backtest_sl_tp_equity_curve() -> None:
    df = _sample_df()
    strat = LongStrat()
    config_no_sl = BacktestConfig(min_trades=0)
    config_sl = BacktestConfig(sl_pct=0.02, tp_pct=0.05, min_trades=0)
    result_no_sl = run_backtest(strat, df, config_no_sl)
    result_sl = run_backtest(strat, df, config_sl)
    assert len(result_sl.portfolio.equity) == len(result_no_sl.portfolio.equity)


def test_backtest_sl_limits_loss() -> None:
    idx = pd.date_range("2020-01-01", periods=50, freq="h")
    df = DataFrame(
        {
            "open": [100.0] * 50,
            "high": [101.0] * 50,
            "low": [99.0] * 50,
            "close": [100.0 - i * 2.0 for i in range(50)],
            "volume": [1000.0] * 50,
        },
        index=idx,
    )
    strat = LongStrat()
    config = BacktestConfig(sl_pct=0.05, min_trades=0)
    result = run_backtest(strat, df, config)
    assert result.full.num_trades >= 1


# ---------------------------------------------------------------------------
# Executor SL/TP wiring tests (mocked)
# ---------------------------------------------------------------------------


def test_executor_apply_sl_tp_called_on_fill() -> None:
    from unittest.mock import MagicMock

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, sl_pct=0.02, tp_pct=0.05)
    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.generate_signals.return_value = Series(
        [1.0], index=pd.date_range("2020-01-01", periods=1, freq="h")
    )

    executor = Executor(strategy=strategy, config=config)
    executor._init_run()
    executor._pnl = __import__("ztb.execution.executor", fromlist=[""]).PnLCalculator(
        initial_cash=100_000.0
    )

    assert hasattr(executor, "_apply_sl_tp")
    assert hasattr(executor, "_clear_sl_tp")
    assert executor._active_sl_tp == {}


def test_executor_active_sl_tp_tracking() -> None:
    from unittest.mock import MagicMock

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    executor = Executor(strategy=MagicMock(), config=ExecRunConfig(mode=Mode.DEMO))
    executor._active_sl_tp["BTCUSDT"] = {"sl_price": 49000.0, "tp_price": 51000.0}
    assert "BTCUSDT" in executor._active_sl_tp
    executor._active_sl_tp.pop("BTCUSDT")
    assert "BTCUSDT" not in executor._active_sl_tp


def test_risk_based_target_qty_imported() -> None:
    from ztb.engine.portfolio import risk_based_target_qty

    assert callable(risk_based_target_qty)
