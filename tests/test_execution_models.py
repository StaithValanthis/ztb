from __future__ import annotations

from ztb.execution.models import (
    AccountState,
    ExecRunConfig,
    Mode,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)


def test_mode_enum() -> None:
    assert Mode.DEMO == "demo"
    assert Mode.LIVE == "live"


def test_order_side_enum() -> None:
    assert OrderSide.BUY == "Buy"
    assert OrderSide.SELL == "Sell"


def test_order_defaults() -> None:
    o = Order(
        order_id="oid1",
        order_link_id="olid1",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        price=50000.0,
        qty=0.1,
        status=OrderStatus.NEW,
        timestamp="2026-01-01T00:00:00Z",
    )
    assert o.cum_exec_qty == 0.0
    assert o.cum_exec_fee == 0.0
    assert o.reduce_only is False


def test_position_defaults() -> None:
    p = Position(
        symbol="BTCUSDT",
        size=0.5,
        avg_price=50000.0,
        unrealized_pnl=100.0,
        realized_pnl=50.0,
        timestamp="",
    )
    assert p.symbol == "BTCUSDT"
    assert p.size == 0.5


def test_account_state_defaults() -> None:
    a = AccountState(total_equity=100000.0, wallet_balance=100000.0, unrealized_pnl=0.0)
    assert a.positions == {}
    assert a.timestamp == ""
    assert a.available_balance == 0.0


def test_account_state_with_available_balance() -> None:
    a = AccountState(
        total_equity=100000.0,
        wallet_balance=95000.0,
        available_balance=80000.0,
        unrealized_pnl=5000.0,
    )
    assert a.available_balance == 80000.0
    assert a.wallet_balance == 95000.0
    assert a.total_equity == 100000.0


def test_exec_run_config_defaults() -> None:
    c = ExecRunConfig()
    assert c.mode == Mode.DEMO
    assert c.dry_run is False
    assert c.once is False
    assert c.risk_enabled is True
    assert c.initial_cash == 100_000.0


def test_exec_run_config_demo_mode() -> None:
    c = ExecRunConfig(mode=Mode.DEMO)
    assert c.mode == Mode.DEMO


def test_order_status_enum() -> None:
    assert OrderStatus.NEW == "New"
    assert OrderStatus.FILLED == "Filled"
    assert OrderStatus.CANCELLED == "Cancelled"
    assert OrderStatus.REJECTED == "Rejected"
