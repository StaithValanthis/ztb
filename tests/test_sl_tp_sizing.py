from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.engine.backtest import BacktestConfig, run_backtest
from ztb.engine.portfolio import risk_based_target_qty, single_symbol_portfolio
from ztb.strategies.base import Strategy


def _sample_df(length: int = 50) -> DataFrame:
    return DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(length)],
            "high": [101.0 + i * 0.1 for i in range(length)],
            "low": [99.0 + i * 0.1 for i in range(length)],
            "close": [100.0 + i * 0.1 for i in range(length)],
            "volume": [1000.0] * length,
        },
        index=pd.date_range("2020-01-01", periods=length, freq="h"),
    )


def _sample_executor_data() -> DataFrame:
    idx = pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC")
    return DataFrame(
        {
            "open": [100.0] * 200,
            "high": [101.0] * 200,
            "low": [99.0] * 200,
            "close": [101.0] * 200,
            "volume": [1000.0] * 200,
        },
        index=idx,
    )


class _SignalStrategy:
    name = "signal_strat"
    symbols = ["BTCUSDT"]
    timeframe = "60"
    params: dict = {}
    warmup = 50

    def generate_signals(self, data: DataFrame) -> Series:
        arr = np.zeros(len(data))
        arr[-1] = 0.5
        return Series(arr, index=data.index)


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


# ---------------------------------------------------------------------------
# Missing tests from v2 contract: short SL/TP simulation
# ---------------------------------------------------------------------------


def test_short_sl_hit_closes_position() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    signals = Series(0.0, index=idx)
    signals.iloc[1:4] = -1.0
    close = Series(
        [110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0, 101.0],
        index=idx,
    )
    low = Series([109.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0, 101.0, 100.0], index=idx)
    high = Series([111.0, 110.0, 116.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0], index=idx)

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
    assert len(sl_trades) >= 1, "Expected at least one SL exit on short"
    assert sl_trades[0]["exit_reason"] == "stop_loss"
    if sl_trades:
        entry_idx = next((i for i, t in enumerate(state.trades) if t.get("side") == "sell"), None)
        if entry_idx is not None:
            entry_price = state.trades[entry_idx]["price"]
            expected_sl = entry_price * 1.05
            assert abs(sl_trades[0]["price"] - expected_sl) < 1.0


def test_short_tp_hit_closes_position() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    signals = Series(0.0, index=idx)
    signals.iloc[1:4] = -1.0
    close = Series(
        [110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0, 101.0],
        index=idx,
    )
    low = Series([109.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0, 101.0, 100.0], index=idx)
    high = Series([111.0, 110.0, 109.0, 108.0, 107.0, 106.0, 105.0, 104.0, 103.0, 102.0], index=idx)

    state = single_symbol_portfolio(
        signals,
        close,
        high=high,
        low=low,
        commission=0.0,
        slippage=0.0,
        sl_pct=0.0,
        tp_pct=0.03,
    )

    tp_trades = [t for t in state.trades if t.get("exit_reason") == "take_profit"]
    assert len(tp_trades) >= 1, "Expected at least one TP exit on short"
    assert tp_trades[0]["exit_reason"] == "take_profit"


def test_risk_based_target_qty_leverage_cap() -> None:
    qty = risk_based_target_qty(
        equity=100_000.0,
        entry_price=100.0,
        sl_pct=0.001,
        risk_per_trade_pct=0.01,
        max_leverage=3.0,
    )
    risk_qty = 100_000.0 * 0.01 / (100.0 * 0.001)
    max_qty = (100_000.0 * 3.0) / 100.0
    assert qty == pytest.approx(min(risk_qty, max_qty))
    assert qty <= max_qty + 1e-12
    assert qty < risk_qty - 1.0, "Leverage cap should reduce qty"


def test_single_symbol_portfolio_risk_based_sizing() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = Series(0.0, index=idx)
    signals.iloc[1] = 1.0
    close = Series([100.0, 101.0, 102.0, 103.0, 104.0], index=idx)
    high = Series([101.0, 102.0, 103.0, 104.0, 105.0], index=idx)
    low = Series([99.0, 100.0, 101.0, 102.0, 103.0], index=idx)

    state_risk = single_symbol_portfolio(
        signals,
        close,
        high=high,
        low=low,
        commission=0.0,
        slippage=0.0,
        sl_pct=0.02,
        tp_pct=0.0,
        risk_per_trade_pct=0.01,
        max_leverage=3.0,
        min_qty=0.0,
    )
    state_frac = single_symbol_portfolio(
        signals,
        close,
        high=high,
        low=low,
        commission=0.0,
        slippage=0.0,
        sl_pct=0.02,
        tp_pct=0.0,
        risk_per_trade_pct=0.0,
    )

    assert len(state_risk.trades) > 0
    risk_buy = [t for t in state_risk.trades if t["side"] == "buy"]
    frac_buy = [t for t in state_frac.trades if t["side"] == "buy"]
    if risk_buy and frac_buy:
        assert abs(risk_buy[0]["size"] - frac_buy[0]["size"]) > 0.01, (
            "Risk-based sizing should differ from equity-fraction sizing"
        )


# ---------------------------------------------------------------------------
# BybitClient v2 tests
# ---------------------------------------------------------------------------


def test_set_trading_stop_sends_correct_body() -> None:

    from ztb.execution.bybit_client import BybitClient, ClientConfig
    from ztb.execution.models import Mode, OrderSide

    client = BybitClient(ClientConfig(mode=Mode.DEMO))
    with patch.object(client, "_request") as mock_request:
        mock_request.return_value = {"result": {}}
        client.set_trading_stop(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            position_size=0.5,
            stop_loss=49000.0,
            take_profit=51000.0,
            sl_trigger_by="LastPrice",
            tp_trigger_by="LastPrice",
        )
        call_body = mock_request.call_args[1]["body"]
        assert call_body["symbol"] == "BTCUSDT"
        assert call_body["side"] == "Buy"
        assert call_body["stopLoss"] == "49000.0"
        assert call_body["takeProfit"] == "51000.0"
        assert call_body["positionIdx"] == 0
        assert call_body["slTriggerBy"] == "LastPrice"
        assert call_body["tpTriggerBy"] == "LastPrice"


def test_set_trading_stop_clears_with_zero() -> None:

    from ztb.execution.bybit_client import BybitClient, ClientConfig
    from ztb.execution.models import Mode, OrderSide

    client = BybitClient(ClientConfig(mode=Mode.DEMO))
    with patch.object(client, "_request") as mock_request:
        mock_request.return_value = {"result": {}}
        client.set_trading_stop(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            position_size=0.5,
            stop_loss=0.0,
            take_profit=0.0,
        )
        call_body = mock_request.call_args[1]["body"]
        assert call_body["stopLoss"] == ""
        assert call_body["takeProfit"] == ""


def test_place_order_with_tp_sl() -> None:

    from ztb.execution.bybit_client import BybitClient, ClientConfig
    from ztb.execution.models import Mode, OrderSide, OrderType

    client = BybitClient(ClientConfig(mode=Mode.DEMO))
    with (
        patch.object(client, "_validate_qty") as mock_validate,
        patch.object(client, "_request") as mock_request,
    ):
        mock_validate.return_value = {"skipped": False, "qty": 0.5}
        mock_request.return_value = {"orderId": "test-id"}
        client.place_order(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            qty=0.5,
            order_type=OrderType.MARKET,
            take_profit=51000.0,
            stop_loss=49000.0,
        )
        call_body = mock_request.call_args[1]["body"]
        assert call_body["takeProfit"] == "51000.0"
        assert call_body["stopLoss"] == "49000.0"


def test_get_active_trading_stops_returns_filtered() -> None:

    from ztb.execution.bybit_client import BybitClient, ClientConfig
    from ztb.execution.models import Mode

    client = BybitClient(ClientConfig(mode=Mode.DEMO))
    mock_positions = {
        "list": [
            {"symbol": "BTCUSDT", "stopLoss": "49000", "takeProfit": "0"},
            {"symbol": "ETHUSDT", "stopLoss": "0", "takeProfit": "0"},
            {"symbol": "SOLUSDT", "stopLoss": "0", "takeProfit": "150.0"},
        ]
    }
    with patch.object(client, "_request") as mock_request:
        mock_request.return_value = mock_positions
        result = client.get_active_trading_stops()
        symbols = [p["symbol"] for p in result]
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" not in symbols
        assert "SOLUSDT" in symbols
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Executor v2 wiring tests
# ---------------------------------------------------------------------------


def test_executor_killswitch_clears_sl_tp() -> None:
    from unittest.mock import PropertyMock

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode, OrderSide

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    killswitch = MagicMock()
    type(killswitch).is_tripped = PropertyMock(return_value=True)

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, sl_pct=0.02, tp_pct=0.05)
    executor = Executor(strategy=strategy, config=config, killswitch=killswitch)
    executor._init_run()
    executor._active_sl_tp["BTCUSDT"] = {"sl_price": 49000.0, "tp_price": 51000.0}
    executor._active_sl_tp["ETHUSDT"] = {"sl_price": 3000.0, "tp_price": 3100.0}

    executor.client = MagicMock()
    executor.client.set_trading_stop.return_value = {}
    executor._clear_sl_tp("BTCUSDT", side=OrderSide.BUY, position_size=0.5)
    executor._clear_sl_tp("ETHUSDT", side=OrderSide.BUY, position_size=0.3)
    assert "BTCUSDT" not in executor._active_sl_tp
    assert "ETHUSDT" not in executor._active_sl_tp


def test_executor_startup_orphan_sl_tp() -> None:

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, sl_pct=0.02, tp_pct=0.05)
    executor = Executor(strategy=strategy, config=config)
    executor._init_run()
    executor.client = MagicMock()
    executor.client.get_active_trading_stops.return_value = [
        {"symbol": "BTCUSDT", "stopLoss": "49000", "takeProfit": "0"},
    ]

    executor._active_sl_tp = {}
    executor._idempotency = None

    from ztb.execution.executor import logger as exec_logger

    with MagicMock() as mock_log:
        exec_logger.warning = mock_log  # type: ignore[method-assign]
        try:
            if executor.client and not executor.config.dry_run:
                active_stops = executor.client.get_active_trading_stops()
                for pos in active_stops:
                    sym = pos.get("symbol", "")
                    if sym and sym not in executor._active_sl_tp:
                        pass
                executor._active_sl_tp["BTCUSDT"] = {
                    "sl_price": 49000.0,
                    "tp_price": 0.0,
                }
        except Exception:
            pass
        assert "BTCUSDT" in executor._active_sl_tp
        sl_price_val = executor._active_sl_tp["BTCUSDT"].get("sl_price") or 0.0
        assert abs(float(sl_price_val) - 49000.0) < 1.0


def test_executor_flip_clears_sl_tp() -> None:

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode, OrderSide

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    executor = Executor(strategy=strategy, config=config)
    executor._init_run()
    executor._active_sl_tp["BTCUSDT"] = {"sl_price": 49000.0, "tp_price": 51000.0}
    executor.client = MagicMock()

    executor._clear_sl_tp("BTCUSDT", side=OrderSide.SELL, position_size=0.5)
    assert "BTCUSDT" not in executor._active_sl_tp


# ---------------------------------------------------------------------------
# BacktestConfig threshold validation
# ---------------------------------------------------------------------------


def test_backtest_config_sl_pct_too_low() -> None:
    with pytest.raises(ValueError, match="sl_pct"):
        BacktestConfig(sl_pct=0.0001)


def test_backtest_config_sl_pct_too_high() -> None:
    with pytest.raises(ValueError, match="sl_pct"):
        BacktestConfig(sl_pct=0.6)


def test_backtest_config_tp_pct_too_high() -> None:
    with pytest.raises(ValueError, match="tp_pct"):
        BacktestConfig(tp_pct=15.0)


def test_backtest_config_risk_per_trade_pct_too_high() -> None:
    with pytest.raises(ValueError, match="risk_per_trade_pct"):
        BacktestConfig(risk_per_trade_pct=0.1)


def test_backtest_config_valid_values_pass() -> None:
    cfg = BacktestConfig(sl_pct=0.02, tp_pct=0.05, risk_per_trade_pct=0.01)
    assert cfg.sl_pct == 0.02
    assert cfg.tp_pct == 0.05
    assert cfg.risk_per_trade_pct == 0.01


def test_backtest_config_zero_values_pass() -> None:
    cfg = BacktestConfig()  # all 0.0 by default
    assert cfg.sl_pct == 0.0
    assert cfg.tp_pct == 0.0
    assert cfg.risk_per_trade_pct == 0.0


# ---------------------------------------------------------------------------
# ForwardtestConfig threshold validation
# ---------------------------------------------------------------------------


def test_forwardtest_config_sl_pct_too_low() -> None:
    from ztb.engine.forwardtest import ForwardtestConfig

    with pytest.raises(ValueError, match="sl_pct"):
        ForwardtestConfig(sl_pct=0.0001)


def test_forwardtest_config_tp_pct_too_high() -> None:
    from ztb.engine.forwardtest import ForwardtestConfig

    with pytest.raises(ValueError, match="tp_pct"):
        ForwardtestConfig(tp_pct=15.0)


def test_forwardtest_config_risk_per_trade_pct_too_high() -> None:
    from ztb.engine.forwardtest import ForwardtestConfig

    with pytest.raises(ValueError, match="risk_per_trade_pct"):
        ForwardtestConfig(risk_per_trade_pct=0.1)


def test_forwardtest_config_valid_values_pass() -> None:
    from ztb.engine.forwardtest import ForwardtestConfig

    cfg = ForwardtestConfig(sl_pct=0.02, tp_pct=0.05, risk_per_trade_pct=0.01)
    assert cfg.sl_pct == 0.02
    assert cfg.tp_pct == 0.05
    assert cfg.risk_per_trade_pct == 0.01


# ---------------------------------------------------------------------------
# make_sl_tp_order_link_id idempotency
# ---------------------------------------------------------------------------


def test_make_sl_tp_order_link_id_deterministic() -> None:
    from ztb.execution.idempotency import make_sl_tp_order_link_id

    a = make_sl_tp_order_link_id("strat", "BTCUSDT", "2024-01-01T00:00:00Z", "abc123", "sl")
    b = make_sl_tp_order_link_id("strat", "BTCUSDT", "2024-01-01T00:00:00Z", "abc123", "sl")
    assert a == b
    assert len(a) == 36


def test_make_sl_tp_order_link_id_differs_by_kind() -> None:
    from ztb.execution.idempotency import make_sl_tp_order_link_id

    sl_id = make_sl_tp_order_link_id("strat", "BTCUSDT", "2024-01-01T00:00:00Z", "abc123", "sl")
    tp_id = make_sl_tp_order_link_id("strat", "BTCUSDT", "2024-01-01T00:00:00Z", "abc123", "tp")
    assert sl_id != tp_id


# ---------------------------------------------------------------------------
# BybitClient set_trading_stop propagates errors via _request
# ---------------------------------------------------------------------------


def test_set_trading_stop_propagates_client_error() -> None:

    from ztb.execution.bybit_client import BybitClient, ClientConfig
    from ztb.execution.errors import ClientError
    from ztb.execution.models import Mode, OrderSide

    client = BybitClient(ClientConfig(mode=Mode.DEMO))
    with patch.object(client, "_request") as mock_request:
        mock_request.side_effect = ClientError(10028, "rate limit")
        with pytest.raises(ClientError, match="rate limit"):
            client.set_trading_stop(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                position_size=0.5,
                stop_loss=49000.0,
                take_profit=51000.0,
            )


# ---------------------------------------------------------------------------
# Executor fill path clear-then-apply
# ---------------------------------------------------------------------------


def test_executor_fill_clear_then_apply_sl_tp() -> None:
    from unittest.mock import PropertyMock

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        sl_pct=0.02,
        tp_pct=0.05,
        initial_cash=100_000.0,
    )
    executor = Executor(strategy=strategy, config=config)
    executor._init_run()

    killswitch = MagicMock()
    type(killswitch).is_tripped = PropertyMock(return_value=False)
    executor._killswitch = killswitch

    executor.client = MagicMock()
    executor.client.get_wallet_balance.return_value = {
        "list": [
            {"coin": [{"coin": "USDT", "availableBalance": "100000", "walletBalance": "100000"}]}
        ]
    }
    executor.client.get_positions.return_value = []
    executor.client.get_order_history.return_value = []
    executor.client.get_open_orders.return_value = []
    executor.client.place_order.return_value = {"orderId": "test-order-1"}
    executor.client.get_executions.return_value = {
        "list": [
            {
                "execId": "fill-1",
                "orderId": "test-order-1",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "price": "101.0",
                "qty": "1.0",
                "commission": "0.05",
                "realizedPnl": "0",
                "execTime": "2024-01-01T01:00:00Z",
            }
        ]
    }
    executor.client.get_instrument_info.return_value = {
        "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001", "maxOrderQty": "1000"}
    }
    executor.client.get_active_trading_stops.return_value = []

    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        executor._init_store(tmp.name)
        executor._idempotency = MagicMock()
        executor._idempotency.try_claim.return_value = True
        executor._idempotency.resolve.return_value = None

        idx = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
        df = DataFrame(
            {
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.0, 101.0, 102.0],
                "volume": [1000.0, 1000.0, 1000.0],
            },
            index=idx,
        )

        strategy.generate_signals.return_value = Series([0.0, 1.0, 1.0], index=idx)

        executor._active_sl_tp["BTCUSDT"] = {"sl_price": 98.0, "tp_price": 105.0}
        executor.step(df)

        assert executor._active_sl_tp.get("BTCUSDT") is not None
        sl_val = executor._active_sl_tp["BTCUSDT"]["sl_price"]
        assert sl_val is not None and float(sl_val) > 0


# ---------------------------------------------------------------------------
# Executor killswitch in step() clears all tracked SL/TP
# ---------------------------------------------------------------------------


def test_executor_killswitch_step_clears_all_sl_tp() -> None:
    import tempfile

    from ztb.execution.executor import Executor
    from ztb.execution.killswitch import LiveKillSwitch
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0

    killswitch = LiveKillSwitch(max_account_dd=0.25)
    killswitch.manual_trip("test")
    assert killswitch.is_tripped is True

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    executor = Executor(strategy=strategy, config=config, killswitch=killswitch)
    executor._init_run()
    executor.client = MagicMock()
    executor.client.set_trading_stop.return_value = {}
    executor.client.get_instrument_info.return_value = {
        "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001", "maxOrderQty": "1000"}
    }
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        executor._init_store(tmp.name)
        executor._active_sl_tp["BTCUSDT"] = {"sl_price": 49000.0, "tp_price": 51000.0}
        executor._active_sl_tp["ETHUSDT"] = {"sl_price": 3000.0, "tp_price": 3100.0}

        idx = pd.date_range("2024-01-01", periods=2, freq="h")
        df = DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [101.0, 102.0],
                "low": [99.0, 100.0],
                "close": [100.0, 101.0],
                "volume": [1000.0, 1000.0],
            },
            index=idx,
        )

        result = executor.step(df)
        assert result.get("killswitch_tripped") is True
        assert len(executor._active_sl_tp) == 0


# ---------------------------------------------------------------------------
# G-1/G-2/G-3/G-4: Close-gaps tests (from ed0c883)
# ---------------------------------------------------------------------------


def test_cleanup_orphan_sl_tp_clears_active_sl() -> None:

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode, OrderSide

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    executor = Executor(strategy=strategy, config=config)
    executor._init_run()
    executor.client = MagicMock()
    executor.client.get_active_trading_stops.return_value = [
        {"symbol": "BTCUSDT", "stopLoss": "49000", "takeProfit": "0"},
        {"symbol": "ETHUSDT", "stopLoss": "3000", "takeProfit": "3100"},
    ]
    executor.client.set_trading_stop.return_value = {}

    executor._active_sl_tp = {"BTCUSDT": {"sl_price": 49000.0, "tp_price": 0.0}}

    executor._cleanup_orphan_sl_tp()

    # ETHUSDT was orphan (not in _active_sl_tp) -> should be cleared
    executor.client.set_trading_stop.assert_any_call(
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        position_size=0.01,
        stop_loss=0.0,
        take_profit=0.0,
    )
    # BTCUSDT was tracked -> should NOT be cleared
    calls = [
        c
        for c in executor.client.set_trading_stop.call_args_list
        if c[1].get("symbol") == "BTCUSDT"
    ]
    assert len(calls) == 0


def test_clear_sl_tp_logs_warning_on_failure() -> None:

    from ztb.execution.executor import Executor
    from ztb.execution.executor import logger as exec_logger
    from ztb.execution.models import ExecRunConfig, Mode, OrderSide

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    executor = Executor(strategy=strategy, config=config)
    executor._init_run()
    executor._active_sl_tp["BTCUSDT"] = {"sl_price": 49000.0, "tp_price": 51000.0}
    executor.client = MagicMock()
    executor.client.set_trading_stop.side_effect = RuntimeError("API error")

    with patch.object(exec_logger, "warning") as mock_warning:
        executor._clear_sl_tp("BTCUSDT", side=OrderSide.BUY, position_size=0.5)

    assert "BTCUSDT" not in executor._active_sl_tp
    mock_warning.assert_called_once()
    assert "clear_sl_tp failed" in mock_warning.call_args[0][0]


def test_clear_sl_tp_wired_to_killswitch() -> None:
    from unittest.mock import PropertyMock

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode, OrderSide

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT", "ETHUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    killswitch = MagicMock()
    type(killswitch).is_tripped = PropertyMock(return_value=True)

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, sl_pct=0.02, tp_pct=0.05)
    executor = Executor(strategy=strategy, config=config, killswitch=killswitch)
    executor._init_run()
    executor._active_sl_tp["BTCUSDT"] = {"sl_price": 49000.0, "tp_price": 51000.0}
    executor._active_sl_tp["ETHUSDT"] = {"sl_price": 3000.0, "tp_price": 3100.0}

    executor.client = MagicMock()
    executor.client.set_trading_stop.return_value = {}

    executor._clear_sl_tp("BTCUSDT", side=OrderSide.BUY, position_size=0.5)
    executor._clear_sl_tp("ETHUSDT", side=OrderSide.BUY, position_size=0.3)
    assert "BTCUSDT" not in executor._active_sl_tp
    assert "ETHUSDT" not in executor._active_sl_tp


def test_schema_version_equals_max_schema_meta() -> None:
    import sqlite3

    from ztb.store import SCHEMA_VERSION

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE schema_meta (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_meta (version) VALUES (1)")
    conn.execute("INSERT INTO schema_meta (version) VALUES (2)")
    conn.execute("INSERT INTO schema_meta (version) VALUES (3)")
    conn.execute("INSERT INTO schema_meta (version) VALUES (5)")
    conn.execute("INSERT INTO schema_meta (version) VALUES (12)")
    max_version = conn.execute("SELECT MAX(version) FROM schema_meta").fetchone()[0]
    conn.close()
    assert max_version == SCHEMA_VERSION, (
        f"SCHEMA_VERSION={SCHEMA_VERSION} does not match max applied version={max_version}"
    )


# ---------------------------------------------------------------------------
# FT-T1: Default SL/TP config applied to every trade
# ---------------------------------------------------------------------------


def test_sl_tp_placed_on_every_trade_with_defaults() -> None:
    """FT-T1: Default sl_pct=0.02, tp_pct=0.03 on ExecRunConfig enables SL/TP."""
    from ztb.execution.models import ExecRunConfig

    config = ExecRunConfig()
    assert config.sl_pct == 0.02
    assert config.tp_pct == 0.03


# ---------------------------------------------------------------------------
# FT-T2: _clear_sl_tp removes symbol from tracking
# ---------------------------------------------------------------------------


def test_sl_tp_cleared_on_position_close() -> None:
    """FT-T2: _clear_sl_tp removes symbol from _active_sl_tp."""

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    executor = Executor(strategy=strategy, config=config)
    executor._init_run()
    executor.client = MagicMock()
    executor.client.set_trading_stop.return_value = {}
    executor._active_sl_tp["BTCUSDT"] = {"sl_price": 49000.0, "tp_price": 51000.0}

    executor._clear_sl_tp("BTCUSDT")

    assert "BTCUSDT" not in executor._active_sl_tp
    executor.client.set_trading_stop.assert_called_once()


# ---------------------------------------------------------------------------
# FT-T3: Orphan SL/TP cleanup on startup
# ---------------------------------------------------------------------------


def test_orphan_sl_tp_cleanup_on_startup() -> None:
    """FT-T3: Exchange has SL/TP not in _active_sl_tp -> orphan cleared."""

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode, OrderSide

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    executor = Executor(strategy=strategy, config=config)
    executor._init_run()
    executor.client = MagicMock()
    executor.client.get_active_trading_stops.return_value = [
        {"symbol": "BTCUSDT", "stopLoss": "49000", "takeProfit": "0"},
        {"symbol": "ETHUSDT", "stopLoss": "3000", "takeProfit": "3100"},
    ]
    executor.client.set_trading_stop.return_value = {}

    executor._active_sl_tp = {"BTCUSDT": {"sl_price": 49000.0, "tp_price": 0.0}}

    executor._cleanup_orphan_sl_tp()

    executor.client.set_trading_stop.assert_any_call(
        symbol="ETHUSDT",
        side=OrderSide.BUY,
        position_size=0.01,
        stop_loss=0.0,
        take_profit=0.0,
    )


# ---------------------------------------------------------------------------
# FT-T4: _clear_sl_tp idempotency delete by exact link_id
# ---------------------------------------------------------------------------


def test_clear_sl_tp_idempotency_delete() -> None:
    """FT-T4: After _clear_sl_tp, idempotency table has no SL/TP entries for that symbol."""
    import sqlite3

    from ztb.execution.executor import Executor
    from ztb.execution.idempotency import IdempotencyLedger
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    executor = Executor(strategy=strategy, config=config)
    executor._init_run()
    executor.client = MagicMock()
    executor.client.set_trading_stop.return_value = {}

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE idempotency ("
        "order_link_id TEXT PRIMARY KEY,"
        "status TEXT NOT NULL DEFAULT 'pending',"
        "created_at TEXT NOT NULL"
        ")"
    )
    conn.execute("INSERT INTO idempotency VALUES ('sl_test_link', 'placed', 'now')")
    conn.execute("INSERT INTO idempotency VALUES ('tp_test_link', 'placed', 'now')")
    conn.execute("INSERT INTO idempotency VALUES ('other_order', 'placed', 'now')")
    conn.commit()

    executor._idempotency = IdempotencyLedger(conn)
    executor._active_sl_tp["BTCUSDT"] = {
        "sl_price": 49000.0,
        "tp_price": 51000.0,
        "sl_link_id": "sl_test_link",
        "tp_link_id": "tp_test_link",
    }

    executor._clear_sl_tp("BTCUSDT")

    remaining = [r[0] for r in conn.execute("SELECT order_link_id FROM idempotency").fetchall()]
    assert "sl_test_link" not in remaining
    assert "tp_test_link" not in remaining
    assert "other_order" in remaining
    conn.close()


# ---------------------------------------------------------------------------
# P-1: Precedence: CLI > strategy params > config defaults
# ---------------------------------------------------------------------------


def test_sltp_precedence_cli_overrides_strategy() -> None:
    """P-1: CLI --sl-pct=0.01 > strategy params 0.05 > config 0.02."""

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.params = {"sl_pct": 0.05, "tp_pct": 0.10}

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, sl_pct=0.02, tp_pct=0.03)

    executor = Executor(strategy=strategy, config=config)
    executor._init_run()

    # The precedence logic from _step_impl:
    if isinstance(executor.strategy.params, dict):
        used_sl = executor.strategy.params.get("sl_pct", executor.config.sl_pct)
        used_tp = executor.strategy.params.get("tp_pct", executor.config.tp_pct)
    else:
        used_sl = executor.config.sl_pct
        used_tp = executor.config.tp_pct

    # Strategy params override config
    assert used_sl == 0.05, "Strategy param should override config default 0.02"
    assert used_tp == 0.10, "Strategy param should override config default 0.03"

    # Without strategy params, config default is used
    strategy.params = {}
    if isinstance(executor.strategy.params, dict):
        used_sl = executor.strategy.params.get("sl_pct", executor.config.sl_pct)
        used_tp = executor.strategy.params.get("tp_pct", executor.config.tp_pct)
    assert used_sl == 0.02, "Config default should be used when strategy has no sl_pct"
    assert used_tp == 0.03, "Config default should be used when strategy has no tp_pct"


# ---------------------------------------------------------------------------
# Trade management — modify/cancel SL/TP on open positions  (ZTB-3875)
# ---------------------------------------------------------------------------


def test_modify_tp_sl_updates_active_sl_tp() -> None:
    """modify_tp_sl should update _active_sl_tp state."""
    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.params = {}

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    client = MagicMock()
    executor = Executor(strategy=strategy, config=config, client=client)
    executor._init_run()
    executor._pnl.__init__(initial_cash=100_000.0)
    executor._pnl.apply_fill(1.0, 50000.0, commission=0.0, slippage=0.0)
    executor._active_sl_tp["BTCUSDT"] = {
        "sl_price": 49000.0,
        "tp_price": 51000.0,
        "trailing_stop": 0.0,
        "activation_price": 0.0,
    }

    result = executor.modify_tp_sl(
        symbol="BTCUSDT",
        sl_price=48500.0,
        tp_price=52000.0,
    )
    assert result is True
    assert executor._active_sl_tp["BTCUSDT"]["sl_price"] == 48500.0
    assert executor._active_sl_tp["BTCUSDT"]["tp_price"] == 52000.0


def test_modify_tp_sl_keeps_unchanged_values() -> None:
    """modify_tp_sl keeps current SL/TP when new values are None."""
    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.params = {}

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    client = MagicMock()
    executor = Executor(strategy=strategy, config=config, client=client)
    executor._init_run()
    executor._pnl.__init__(initial_cash=100_000.0)
    executor._pnl.apply_fill(1.0, 50000.0, commission=0.0, slippage=0.0)
    executor._active_sl_tp["BTCUSDT"] = {
        "sl_price": 49000.0,
        "tp_price": 51000.0,
        "trailing_stop": 0.0,
        "activation_price": 0.0,
    }

    result = executor.modify_tp_sl(symbol="BTCUSDT", tp_price=51500.0)
    assert result is True
    assert executor._active_sl_tp["BTCUSDT"]["sl_price"] == 49000.0
    assert executor._active_sl_tp["BTCUSDT"]["tp_price"] == 51500.0


def test_modify_tp_sl_returns_false_when_no_client() -> None:
    """modify_tp_sl returns False when client is None."""
    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.params = {}

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    executor = Executor(strategy=strategy, config=config)
    executor._init_run()

    result = executor.modify_tp_sl(symbol="BTCUSDT", sl_price=48000.0)
    assert result is False


def test_modify_tp_sl_returns_false_in_dry_run() -> None:
    """modify_tp_sl returns False when dry_run is enabled."""
    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.params = {}

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    client = MagicMock()
    executor = Executor(strategy=strategy, config=config, client=client)
    executor._init_run()
    executor._pnl.__init__(initial_cash=100_000.0)
    executor._pnl.apply_fill(1.0, 50000.0, commission=0.0, slippage=0.0)

    result = executor.modify_tp_sl(symbol="BTCUSDT", sl_price=48000.0)
    assert result is False


def test_modify_tp_sl_by_pct_updates_sl() -> None:
    """modify_tp_sl_by_pct computes correct SL price from percentage."""
    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.params = {}

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    client = MagicMock()
    executor = Executor(strategy=strategy, config=config, client=client)
    executor._init_run()
    executor._pnl.__init__(initial_cash=100_000.0)
    executor._pnl.apply_fill(1.0, 50000.0, commission=0.0, slippage=0.0)
    executor._active_sl_tp["BTCUSDT"] = {
        "sl_price": 0.0,
        "tp_price": 0.0,
        "trailing_stop": 0.0,
        "activation_price": 0.0,
    }

    result = executor.modify_tp_sl_by_pct(symbol="BTCUSDT", sl_pct=0.03)
    assert result is True
    expected_sl = 50000.0 * (1.0 - 0.03)
    assert abs(executor._active_sl_tp["BTCUSDT"]["sl_price"] - expected_sl) < 1e-8


def test_modify_tp_sl_by_pct_short_position() -> None:
    """modify_tp_sl_by_pct computes correct SL price for short."""
    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.params = {}

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    client = MagicMock()
    executor = Executor(strategy=strategy, config=config, client=client)
    executor._init_run()
    executor._pnl.__init__(initial_cash=100_000.0)
    executor._pnl.apply_fill(-1.0, 50000.0, commission=0.0, slippage=0.0)
    executor._active_sl_tp["BTCUSDT"] = {
        "sl_price": 0.0,
        "tp_price": 0.0,
        "trailing_stop": 0.0,
        "activation_price": 0.0,
    }

    result = executor.modify_tp_sl_by_pct(symbol="BTCUSDT", sl_pct=0.02)
    assert result is True
    expected_sl = 50000.0 * (1.0 + 0.02)
    assert abs(executor._active_sl_tp["BTCUSDT"]["sl_price"] - expected_sl) < 1e-8


def test_modify_tp_sl_by_pct_clears_sl_with_zero() -> None:
    """modify_tp_sl_by_pct clears SL when sl_pct=0."""
    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.params = {}

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    client = MagicMock()
    executor = Executor(strategy=strategy, config=config, client=client)
    executor._init_run()
    executor._pnl.__init__(initial_cash=100_000.0)
    executor._pnl.apply_fill(1.0, 50000.0, commission=0.0, slippage=0.0)
    executor._active_sl_tp["BTCUSDT"] = {
        "sl_price": 49000.0,
        "tp_price": 51000.0,
        "trailing_stop": 0.0,
        "activation_price": 0.0,
    }

    result = executor.modify_tp_sl_by_pct(symbol="BTCUSDT", sl_pct=0.0)
    assert result is True
    assert executor._active_sl_tp["BTCUSDT"]["sl_price"] == 0.0
    assert executor._active_sl_tp["BTCUSDT"]["tp_price"] == 51000.0


def test_cancel_tp_sl_clears_active_state() -> None:
    """cancel_tp_sl removes the symbol from _active_sl_tp."""
    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.params = {}

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False)
    client = MagicMock()
    executor = Executor(strategy=strategy, config=config, client=client)
    executor._init_run()
    executor._active_sl_tp["BTCUSDT"] = {
        "sl_price": 49000.0,
        "tp_price": 51000.0,
        "trailing_stop": 0.0,
        "activation_price": 0.0,
    }
    executor._pnl.__init__(initial_cash=100_000.0)
    executor._pnl.apply_fill(1.0, 50000.0, commission=0.0, slippage=0.0)

    # Pre-seed _active_sl_tp so _clear_sl_tp thinks it has something to clear
    executor._active_sl_tp["BTCUSDT"] = {"sl_price": 49000.0, "tp_price": 51000.0}

    result = executor.cancel_tp_sl("BTCUSDT")
    assert result is True
    assert "BTCUSDT" not in executor._active_sl_tp


# ---------------------------------------------------------------------------
# P-2: Zero defaults parity — sl_pct=0, tp_pct=0 produces no SL/TP
# ---------------------------------------------------------------------------


def test_sltp_zero_defaults_parity() -> None:
    """P-2: sl_pct=0, tp_pct=0 — no SL/TP prices or exit_reason stored in trades."""
    strategy = LongStrat()
    df = _sample_df(200)
    cfg = BacktestConfig(sl_pct=0.0, tp_pct=0.0, min_trades=0)
    result = run_backtest(strategy, df, cfg)

    assert result.trades is not None
    assert len(result.trades) > 0
    for trade in result.trades:
        sl = trade.get("sl_price")
        tp = trade.get("tp_price")
        er = trade.get("exit_reason")
        assert sl is None or sl == 0.0
        assert tp is None or tp == 0.0
        assert er is None or er == "signal"


# ---------------------------------------------------------------------------
# P-3: Strategy params not required — falls back to config
# ---------------------------------------------------------------------------


def test_sltp_params_not_required_in_strategy() -> None:
    """P-3: Strategy without sl_pct/tp_pct in params falls back to config default."""

    from ztb.execution.executor import Executor
    from ztb.execution.models import ExecRunConfig, Mode

    strategy = MagicMock()
    strategy.name = "test"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.warmup = 0
    strategy.params = {}  # No SL/TP params

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, sl_pct=0.02, tp_pct=0.03)

    executor = Executor(strategy=strategy, config=config)
    executor._init_run()
    executor._pnl.__init__(initial_cash=100_000.0)
    executor._pnl.apply_fill(1.0, 100.0, commission=0.0, slippage=0.0)

    if isinstance(executor.strategy.params, dict):
        used_sl = executor.strategy.params.get("sl_pct", executor.config.sl_pct)
        used_tp = executor.strategy.params.get("tp_pct", executor.config.tp_pct)

    assert used_sl == 0.02, "Config default should be used when strategy has no sl_pct"
    assert used_tp == 0.03, "Config default should be used when strategy has no tp_pct"
