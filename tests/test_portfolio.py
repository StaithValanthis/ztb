from __future__ import annotations

import pandas as pd
import pytest
from pandas import Series

from ztb.engine.portfolio import multi_symbol_portfolio, single_symbol_portfolio


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
    assert len(state.trades) == 3
    assert state.trades[0]["side"] == "buy"
    assert state.trades[1]["side"] == "buy"
    assert state.trades[2]["side"] == "sell"


def test_short_position() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = Series([0.0, -1.0, -1.0, -1.0, 0.0], index=idx)
    close = Series([100.0, 100.0, 100.0, 100.0, 100.0], index=idx)
    state = single_symbol_portfolio(signals, close, commission=0.0, slippage=0.0)
    assert state.position == 0.0
    assert len(state.trades) > 0


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


def test_short_open_position_cash_identity() -> None:
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    signals = Series([-10.0, -10.0, -10.0], index=idx)
    close = Series([100.0, 101.0, 102.0], index=idx)
    state = single_symbol_portfolio(signals, close, commission=0.0, slippage=0.0)
    last_equity = state.equity[-1]
    expected_cash = last_equity - state.position * close.iloc[-1]
    assert state.cash == pytest.approx(expected_cash)


def test_first_bar_records_trade() -> None:
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    signals = Series([1.0], index=idx)
    close = Series([100.0], index=idx)
    comm = 0.001
    slip = 0.001
    state = single_symbol_portfolio(signals, close, commission=comm, slippage=slip)
    assert len(state.trades) == 1
    assert state.trades[0]["side"] == "buy"
    assert state.trades[0]["commission"] > 0.0
    assert state.trades[0]["slippage"] > 0.0
    assert state.trades[0]["pnl"] < 0.0
    assert state.equity[-1] < 100000.0


def test_bar0_short_entry() -> None:
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    signals = Series([-1.0], index=idx)
    close = Series([100.0], index=idx)
    comm = 0.001
    slip = 0.001
    state = single_symbol_portfolio(signals, close, commission=comm, slippage=slip)
    assert len(state.trades) == 1
    assert state.trades[0]["side"] == "sell"
    cost = abs(state.trades[0]["size"]) * 100.0 * (comm + slip)
    assert state.equity[0] == pytest.approx(100_000.0 - cost)


def test_bar0_partial_entry() -> None:
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    signals = Series([0.5], index=idx)
    close = Series([100.0], index=idx)
    comm = 0.001
    slip = 0.001
    state = single_symbol_portfolio(signals, close, commission=comm, slippage=slip)
    assert len(state.trades) == 1
    assert state.trades[0]["side"] == "buy"
    cost = abs(state.trades[0]["size"]) * 100.0 * (comm + slip)
    assert state.equity[0] == pytest.approx(100_000.0 - cost)
    assert state.trades[0]["size"] == pytest.approx(0.5 * 100_000.0 / 100.0)


def test_bar0_then_close() -> None:
    idx = pd.date_range("2026-01-01", periods=2, freq="D")
    signals = Series([1.0, 0.0], index=idx)
    close = Series([100.0, 101.0], index=idx)
    comm = 0.001
    slip = 0.001
    state = single_symbol_portfolio(signals, close, commission=comm, slippage=slip)
    assert len(state.trades) == 2
    entry_cost = state.trades[0]["commission"] + state.trades[0]["slippage"]
    exit_cost = state.trades[1]["commission"] + state.trades[1]["slippage"]
    assert state.equity[1] == pytest.approx(100_000.0 - entry_cost - exit_cost + (101.0 - 100.0) * state.trades[0]["size"])


def test_bar0_flip_long_to_short() -> None:
    idx = pd.date_range("2026-01-01", periods=2, freq="D")
    signals = Series([1.0, -1.0], index=idx)
    close = Series([100.0, 100.0], index=idx)
    comm = 0.001
    slip = 0.001
    state = single_symbol_portfolio(signals, close, commission=comm, slippage=slip)
    assert len(state.trades) == 2
    assert state.trades[0]["side"] == "buy"
    assert state.trades[1]["side"] == "sell"
    total_cost = state.trades[0]["commission"] + state.trades[0]["slippage"] + state.trades[1]["commission"] + state.trades[1]["slippage"]
    assert state.equity[1] == pytest.approx(100_000.0 - total_cost)


def test_bar0_flip_short_to_long() -> None:
    idx = pd.date_range("2026-01-01", periods=2, freq="D")
    signals = Series([-1.0, 1.0], index=idx)
    close = Series([100.0, 100.0], index=idx)
    comm = 0.001
    slip = 0.001
    state = single_symbol_portfolio(signals, close, commission=comm, slippage=slip)
    assert len(state.trades) == 2
    assert state.trades[0]["side"] == "sell"
    assert state.trades[1]["side"] == "buy"
    total_cost = state.trades[0]["commission"] + state.trades[0]["slippage"] + state.trades[1]["commission"] + state.trades[1]["slippage"]
    assert state.equity[1] == pytest.approx(100_000.0 - total_cost)


def test_bar0_multi_symbol_two_signals() -> None:
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    signals = {"A": Series([1.0], index=idx), "B": Series([-0.5], index=idx)}
    closes = {"A": Series([100.0], index=idx), "B": Series([50.0], index=idx)}
    comm = 0.001
    slip = 0.001
    state = multi_symbol_portfolio(signals, closes, commission=comm, slippage=slip)
    assert len(state.trades) == 2
    assert state.positions["A"] > 0
    assert state.positions["B"] < 0
    total_cost = sum(t["commission"] + t["slippage"] for t in state.trades)
    assert state.equity[0] == pytest.approx(100_000.0 - total_cost, rel=1e-9)


def test_equity_continuity_single() -> None:
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    signals = Series([1.0, 1.0, -0.5, 0.0, 0.8], index=idx)
    close = Series([100.0, 102.0, 101.0, 99.0, 103.0], index=idx)
    initial_cash = 100_000.0
    state = single_symbol_portfolio(signals, close, initial_cash=initial_cash,
                                    commission=0.001, slippage=0.001)
    assert len(state.equity) == 5
    for i, ti in enumerate(state.timestamps):
        pos = sum(
            t["size"] if t["side"] == "buy" else -t["size"]
            for t in state.trades if t["timestamp"] <= ti
        )
        cash_flow = sum(
            -(t["size"] if t["side"] == "buy" else -t["size"]) * t["price"]
            - t["commission"] - t["slippage"]
            for t in state.trades if t["timestamp"] <= ti
        )
        cash = initial_cash + cash_flow
        ci = float(close.loc[ti])
        assert state.equity[i] == pytest.approx(cash + pos * ci, rel=1e-9)


def test_equity_continuity_multi() -> None:
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    signals = {
        "A": Series([0.5, 0.5, -0.3, 0.0, 0.4], index=idx),
        "B": Series([-0.3, -0.3, 0.2, 0.0, 0.0], index=idx),
    }
    closes = {
        "A": Series([100.0, 102.0, 101.0, 99.0, 103.0], index=idx),
        "B": Series([50.0, 51.0, 49.0, 50.0, 52.0], index=idx),
    }
    initial_cash = 100_000.0
    state = multi_symbol_portfolio(signals, closes, initial_cash=initial_cash,
                                   commission=0.001, slippage=0.001)
    assert len(state.equity) == 5
    for i, ti in enumerate(state.timestamps):
        positions: dict[str, float] = {}
        cash = initial_cash
        for t in state.trades:
            if t["timestamp"] <= ti:
                sym = t.get("symbol", "")
                side_sign = 1.0 if t["side"] == "buy" else -1.0
                positions[sym] = positions.get(sym, 0.0) + side_sign * t["size"]
                cash -= side_sign * t["size"] * t["price"]
                cash -= t["commission"] + t["slippage"]
        pos_val = sum(positions.get(sym, 0.0) * float(closes[sym].loc[ti]) for sym in signals)
        assert state.equity[i] == pytest.approx(cash + pos_val, rel=1e-9)


# ---------------------------------------------------------------------------
# multi_symbol_portfolio
# ---------------------------------------------------------------------------


def test_multi_empty_symbols() -> None:
    state = multi_symbol_portfolio({}, {})
    assert state.cash == 100_000.0
    assert state.positions == {}
    assert state.trades == []


def test_multi_flat_signals() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = {"A": Series(0.0, index=idx), "B": Series(0.0, index=idx)}
    closes = {"A": Series(100.0, index=idx), "B": Series(50.0, index=idx)}
    state = multi_symbol_portfolio(signals, closes)
    assert state.position == 0.0
    assert len(state.trades) == 0


def test_multi_buy_and_hold() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = {"A": Series(1.0, index=idx)}
    closes = {"A": Series(100.0, index=idx)}
    state = multi_symbol_portfolio(signals, closes)
    assert len(state.trades) >= 1
    assert state.position > 0


def test_multi_long_two_symbols() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = {
        "A": Series(0.5, index=idx),
        "B": Series(0.5, index=idx),
    }
    closes = {
        "A": Series(100.0, index=idx),
        "B": Series(50.0, index=idx),
    }
    state = multi_symbol_portfolio(signals, closes, commission=0.0, slippage=0.0)
    assert len(state.trades) >= 2
    assert state.positions["A"] > 0
    assert state.positions["B"] > 0
    assert len(state.equity) == 5


def test_multi_one_short_one_long() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = {
        "A": Series(0.5, index=idx),
        "B": Series(-0.3, index=idx),
    }
    closes = {
        "A": Series(100.0, index=idx),
        "B": Series(50.0, index=idx),
    }
    state = multi_symbol_portfolio(signals, closes, commission=0.0, slippage=0.0)
    assert state.positions["A"] > 0
    assert state.positions["B"] < 0
    assert len(state.trades) >= 2


def test_multi_bar_zero_records_trade() -> None:
    idx = pd.date_range("2026-01-01", periods=1, freq="D")
    signals = {"A": Series([1.0], index=idx)}
    closes = {"A": Series([100.0], index=idx)}
    comm = 0.001
    slip = 0.001
    state = multi_symbol_portfolio(signals, closes, commission=comm, slippage=slip)
    assert len(state.trades) == 1
    assert state.trades[0]["side"] == "buy"
    assert state.trades[0]["commission"] > 0.0
    assert state.trades[0]["pnl"] < 0.0


def test_multi_cross_section_equity_split() -> None:
    idx = pd.date_range("2020-01-01", periods=3, freq="h")
    signals = {"A": Series(0.0, index=idx), "B": Series(0.0, index=idx)}
    closes = {"A": Series(100.0, index=idx), "B": Series(200.0, index=idx)}
    state = multi_symbol_portfolio(signals, closes, initial_cash=100_000.0)
    assert state.cash == 100_000.0
    assert state.position == 0.0


def test_multi_trade_size_reflects_commission() -> None:
    idx = pd.date_range("2020-01-01", periods=3, freq="h")
    signals = {"A": Series([1.0, 1.0, 0.0], index=idx)}
    closes = {"A": Series([100.0, 101.0, 102.0], index=idx)}
    state_high = multi_symbol_portfolio(signals, closes, commission=0.01)
    state_low = multi_symbol_portfolio(signals, closes, commission=0.0)
    assert state_high.equity[-1] < state_low.equity[-1]


def test_multi_split_long_close() -> None:
    idx = pd.date_range("2020-01-01", periods=5, freq="h")
    signals = {"A": Series([0.0, 1.0, 1.0, 0.0, 0.0], index=idx)}
    closes = {"A": Series([100.0, 101.0, 102.0, 103.0, 104.0], index=idx)}
    state = multi_symbol_portfolio(signals, closes, commission=0.0, slippage=0.0)
    assert len(state.trades) >= 2
    assert state.position == 0.0
