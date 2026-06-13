from __future__ import annotations

import pandas as pd
from pandas import Series

from ztb.engine.portfolio import single_symbol_portfolio


def test_flat_signals() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    signals = Series(0.0, index=idx)
    close = Series(100.0, index=idx)
    state = single_symbol_portfolio(signals, close)
    assert state.position == 0.0
    assert state.cash == 100_000.0
    assert len(state.trades) == 0


def test_buy_and_hold() -> None:
    idx = pd.date_range("2020-01-01", periods=10, freq="h")
    signals = Series(0.0, index=idx)
    signals.iloc[1:] = 1.0
    close = Series(100.0 + Series(range(10), index=idx), index=idx)
    state = single_symbol_portfolio(signals, close)
    assert len(state.trades) > 0
    assert len(state.equity) == 10


def test_trade_recorded() -> None:
    idx = pd.date_range("2020-01-01", periods=3, freq="h")
    signals = Series([0.0, 1.0, 0.0], index=idx)
    close = Series([100.0, 101.0, 102.0], index=idx)
    state = single_symbol_portfolio(signals, close)
    assert len(state.trades) == 2
    assert state.trades[0]["side"] == "buy"
    assert state.trades[1]["side"] == "sell"


def test_initial_cash() -> None:
    idx = pd.date_range("2020-01-01", periods=3, freq="h")
    signals = Series(0.0, index=idx)
    close = Series(100.0, index=idx)
    state = single_symbol_portfolio(signals, close, initial_cash=50_000.0)
    assert state.cash == 50_000.0


def test_custom_commission() -> None:
    idx = pd.date_range("2020-01-01", periods=3, freq="h")
    signals = Series([1.0, 1.0, 0.0], index=idx)
    close = Series([100.0, 101.0, 102.0], index=idx)
    state_high = single_symbol_portfolio(signals, close, commission=0.01)
    state_low = single_symbol_portfolio(signals, close, commission=0.0)
    assert state_high.cash < state_low.cash


def test_state_dataclass() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = Series(0.0, index=idx)
    close = Series(100.0, index=idx)
    state = single_symbol_portfolio(signals, close)
    assert hasattr(state, "cash")
    assert hasattr(state, "position")
    assert hasattr(state, "equity")
    assert hasattr(state, "timestamps")
    assert hasattr(state, "trades")


def test_add_to_long() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = Series([0.5, 1.0, 1.0, 0.0, 0.0], index=idx)
    close = Series([100.0, 101.0, 102.0, 103.0, 104.0], index=idx)
    state = single_symbol_portfolio(signals, close, commission=0.0, slippage=0.0)
    assert len(state.trades) == 2
    assert state.trades[0]["side"] == "buy"
    assert state.trades[1]["side"] == "sell"


def test_short_position() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = Series([0.0, -1.0, -1.0, -1.0, 0.0], index=idx)
    close = Series([100.0, 100.0, 100.0, 100.0, 100.0], index=idx)
    state = single_symbol_portfolio(signals, close, commission=0.0, slippage=0.0)
    assert state.position == 0.0
    assert len(state.trades) == 2


def test_add_to_short() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = Series([-0.5, -1.0, -1.0, 0.0, 0.0], index=idx)
    close = Series([100.0, 101.0, 102.0, 103.0, 104.0], index=idx)
    state = single_symbol_portfolio(signals, close, commission=0.0, slippage=0.0)
    assert len(state.trades) >= 2
    assert state.trades[0]["side"] == "sell"


def test_flip_short_to_long() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = Series([-1.0, 1.0, 1.0, 0.0, 0.0], index=idx)
    close = Series([100.0, 100.0, 100.0, 100.0, 100.0], index=idx)
    state = single_symbol_portfolio(signals, close, commission=0.0, slippage=0.0)
    assert len(state.trades) >= 1
    assert state.position == 0.0


def test_reduce_short() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = Series([-0.5, -1.0, -0.5, 0.0, 0.0], index=idx)
    close = Series([100.0, 100.0, 100.0, 100.0, 100.0], index=idx)
    state = single_symbol_portfolio(signals, close, commission=0.0, slippage=0.0)
    assert len(state.trades) >= 3
