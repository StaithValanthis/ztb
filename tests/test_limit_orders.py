from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, PropertyMock

import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.execution.bybit_client import round_to_step
from ztb.execution.executor import Executor
from ztb.execution.models import ExecRunConfig, Mode, OrderSide, OrderType

# get_executions() returns a LIST of raw executions; parse_fills() reads the
# exec* field names (execPrice/execQty/execFee), not price/qty/commission.
_EXEC = {
    "execId": "fill-1",
    "orderId": "oid-1",
    "symbol": "BTCUSDT",
    "side": "Buy",
    "execPrice": "99.0",
    "execQty": "1.0",
    "execFee": "0.05",
    "execTime": "2024-01-01T01:00:00Z",
}


def _df() -> DataFrame:
    idx = pd.date_range("2024-01-01", periods=3, freq="h", tz="UTC")
    return DataFrame(
        {
            "open": [100.0, 100.0, 100.0],
            "high": [101.0, 101.0, 101.0],
            "low": [99.0, 99.0, 99.0],
            "close": [100.0, 100.0, 100.0],
            "volume": [1000.0, 1000.0, 1000.0],
        },
        index=idx,
    )


def _mk_executor(
    order_type: OrderType,
    *,
    fallback: bool = True,
    offset: float = 0.0,
    tick: str = "0.1",
):
    strategy = MagicMock()
    strategy.name = "lim"
    strategy.symbols = ["BTCUSDT"]
    strategy.timeframe = "60"
    strategy.params = {}
    strategy.warmup = 1
    strategy.get_risk_profile.return_value = None  # fall through to config
    idx = _df().index
    strategy.generate_signals.return_value = Series([0.0, 1.0, 1.0], index=idx)

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        order_type=order_type,
        limit_offset_pct=offset,
        limit_fallback_market=fallback,
        initial_cash=100_000.0,
        poll_fill_max_attempts=1,
        poll_fill_interval=0.0,
        sl_pct=0.0,
        tp_pct=0.0,
    )
    executor = Executor(strategy=strategy, config=config)
    executor._init_run()

    ks = MagicMock()
    type(ks).is_tripped = PropertyMock(return_value=False)
    executor._killswitch = ks

    executor.client = MagicMock()
    executor.client.get_wallet_balance.return_value = {
        "list": [
            {"coin": [{"coin": "USDT", "availableBalance": "100000", "walletBalance": "100000"}]}
        ]
    }
    executor.client.get_positions.return_value = []
    executor.client.get_order_history.return_value = []
    executor.client.get_open_orders.return_value = []
    executor.client.get_active_trading_stops.return_value = []
    executor.client.place_order.return_value = {"orderId": "oid-1"}
    executor.client.get_instrument_info.return_value = {
        "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001", "maxOrderQty": "1000"},
        "priceFilter": {"tickSize": tick},
    }
    executor.client.get_tick_size.return_value = float(tick)
    executor.client.round_to_step.side_effect = round_to_step
    return executor, strategy


def _run(executor) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        executor._init_store(tmp.name)
        executor._idempotency = MagicMock()
        executor._idempotency.try_claim.return_value = True
        executor._idempotency.resolve.return_value = None
        return executor.step(_df())


# --------------------------------------------------------------------------- #
# config validation
# --------------------------------------------------------------------------- #
def test_config_rejects_bad_limit_offset() -> None:
    with pytest.raises(ValueError):
        ExecRunConfig(mode=Mode.DEMO, limit_offset_pct=0.5)
    with pytest.raises(ValueError):
        ExecRunConfig(mode=Mode.DEMO, limit_offset_pct=-0.01)
    # boundary + zero are fine
    ExecRunConfig(mode=Mode.DEMO, limit_offset_pct=0.0)
    ExecRunConfig(mode=Mode.DEMO, limit_offset_pct=0.10)


def test_config_default_is_market() -> None:
    assert ExecRunConfig(mode=Mode.DEMO).order_type == OrderType.MARKET


# --------------------------------------------------------------------------- #
# tick + limit-price math
# --------------------------------------------------------------------------- #
def test_get_tick_size_reads_price_filter() -> None:
    from ztb.execution.bybit_client import BybitClient, ClientConfig

    c = BybitClient(ClientConfig(api_key="x", api_secret="y", mode=Mode.DEMO))
    c.get_instrument_info = lambda *a, **k: {"priceFilter": {"tickSize": "0.5"}}  # type: ignore[method-assign]
    assert c.get_tick_size("BTCUSDT") == 0.5


def test_resolve_limit_price_buy_below_sell_above() -> None:
    executor, _ = _mk_executor(OrderType.LIMIT, offset=0.01, tick="0.1")
    buy = executor._resolve_limit_price(OrderSide.BUY, 100.0, "BTCUSDT")
    sell = executor._resolve_limit_price(OrderSide.SELL, 100.0, "BTCUSDT")
    assert buy == 99.0  # 100*(1-0.01)=99.0, on-tick
    assert sell == 101.0  # 100*(1+0.01)=101.0, on-tick
    assert buy < 100.0 < sell


# --------------------------------------------------------------------------- #
# placement / lifecycle through step()
# --------------------------------------------------------------------------- #
def test_market_order_path_unchanged() -> None:
    executor, _ = _mk_executor(OrderType.MARKET)
    executor.client.get_executions.return_value = [_EXEC]
    _run(executor)
    kw = executor.client.place_order.call_args.kwargs
    assert kw["order_type"] == OrderType.MARKET
    assert kw.get("price") is None
    executor.client.cancel_order.assert_not_called()
    assert executor._pnl.position > 0


def test_limit_order_placed_with_limit_type_and_offset_price() -> None:
    executor, _ = _mk_executor(OrderType.LIMIT, offset=0.01, tick="0.1")
    executor.client.get_executions.return_value = [_EXEC]
    _run(executor)
    kw = executor.client.place_order.call_args.kwargs
    assert kw["order_type"] == OrderType.LIMIT
    assert kw["price"] == 99.0  # buy limit 1% below close 100.0, on-tick
    assert executor._pnl.position > 0


def test_filled_limit_cancels_resting_remainder() -> None:
    executor, _ = _mk_executor(OrderType.LIMIT)
    executor.client.get_executions.return_value = [_EXEC]
    _run(executor)
    # even on a fill we attempt cancel to clear any partial remainder
    executor.client.cancel_order.assert_called()


def test_unfilled_limit_falls_back_to_market() -> None:
    executor, _ = _mk_executor(OrderType.LIMIT, fallback=True)
    # first poll (limit) empty, second poll (market fallback) fills
    executor.client.get_executions.side_effect = [[], [_EXEC]]
    result = _run(executor)
    assert executor.client.place_order.call_count == 2
    executor.client.cancel_order.assert_called()
    second = executor.client.place_order.call_args_list[1].kwargs
    assert second["order_type"] == OrderType.MARKET
    assert second["order_link_id"].endswith("-mkt")
    assert executor._pnl.position > 0
    assert result.get("order_placed") is True


def test_unfilled_limit_no_fallback_takes_no_phantom_position() -> None:
    executor, _ = _mk_executor(OrderType.LIMIT, fallback=False)
    executor.client.get_executions.return_value = []  # never fills
    result = _run(executor)
    # exactly one order placed (no market fallback), resting order cancelled,
    # and CRITICALLY no synthetic fill -> position stays flat
    assert executor.client.place_order.call_count == 1
    executor.client.cancel_order.assert_called()
    assert result.get("order_unfilled") is True
    assert abs(executor._pnl.position) < 1e-12
