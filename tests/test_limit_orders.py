from __future__ import annotations

import tempfile
from unittest.mock import MagicMock, PropertyMock

import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.execution.bybit_client import ceil_to_step, round_to_step
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


def _exec(exec_id: str, qty: str, price: str = "99.0") -> dict:
    return {**_EXEC, "execId": exec_id, "execQty": qty, "execPrice": price}


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
    executor.client.get_qty_step.return_value = 0.001
    executor.client.round_to_step.side_effect = round_to_step
    executor.client.ceil_to_step.side_effect = ceil_to_step
    return executor, strategy


def _run(executor, df: DataFrame | None = None) -> dict:
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        executor._init_store(tmp.name)
        executor._idempotency = MagicMock()
        executor._idempotency.try_claim.return_value = True
        executor._idempotency.resolve.return_value = None
        return executor.step(df if df is not None else _df())


# --------------------------------------------------------------------------- #
# config validation
# --------------------------------------------------------------------------- #
def test_config_rejects_bad_limit_offset() -> None:
    with pytest.raises(ValueError):
        ExecRunConfig(mode=Mode.DEMO, limit_offset_pct=0.5)
    with pytest.raises(ValueError):
        ExecRunConfig(mode=Mode.DEMO, limit_offset_pct=-0.01)
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


def test_resolve_limit_price_buy_floors_sell_ceils() -> None:
    # tick 0.5 to make the rounding direction observable
    executor, _ = _mk_executor(OrderType.LIMIT, offset=0.011, tick="0.5")
    buy = executor._resolve_limit_price(OrderSide.BUY, 100.0, "BTCUSDT")
    sell = executor._resolve_limit_price(OrderSide.SELL, 100.0, "BTCUSDT")
    # buy raw = 98.9 -> floor to 0.5 -> 98.5 (below market, maker)
    assert buy == 98.5
    # sell raw = 101.1 -> ceil to 0.5 -> 101.5 (above market, maker — never crosses down)
    assert sell == 101.5
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
    first = executor.client.place_order.call_args_list[0].kwargs
    assert first["order_type"] == OrderType.LIMIT
    assert first["price"] == 99.0  # buy limit 1% below close 100.0, on-tick
    assert executor._pnl.position > 0


def test_filled_limit_cancels_and_resolves_placed() -> None:
    # cancel-FIRST design: we always cancel to clear any resting remainder, and a
    # filled limit resolves the link to a restorable 'placed' state.
    executor, _ = _mk_executor(OrderType.LIMIT)
    executor.client.get_executions.return_value = [_EXEC]
    _run(executor)
    executor.client.cancel_order.assert_called()
    statuses = [c.args[1] for c in executor._idempotency.resolve.call_args_list if len(c.args) >= 2]
    assert "placed" in statuses
    assert "cancelled" not in statuses  # it filled


def test_unfilled_limit_falls_back_to_market_for_remainder() -> None:
    executor, _ = _mk_executor(OrderType.LIMIT, fallback=True)
    # pre poll empty, post-cancel poll empty, fallback market poll fills
    executor.client.get_executions.side_effect = [[], [], [_EXEC]]
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
    assert executor.client.place_order.call_count == 1  # no market fallback
    executor.client.cancel_order.assert_called()
    assert result.get("order_unfilled") is True
    assert abs(executor._pnl.position) < 1e-12  # CRITICAL: no synthetic phantom
    # the unfilled limit link must be terminal so restart cannot synth-restore it
    statuses = [c.args[1] for c in executor._idempotency.resolve.call_args_list if len(c.args) >= 2]
    assert "cancelled" in statuses
    assert "placed" not in statuses


def test_partial_limit_fill_tops_up_remainder_only() -> None:
    executor, _ = _mk_executor(OrderType.LIMIT, fallback=True)
    # limit partially fills 0.4; post-cancel sees same; fallback market fills the rest
    executor.client.get_executions.side_effect = [
        [_exec("fill-A", "0.4")],
        [_exec("fill-A", "0.4")],
        [_exec("fill-B", "0.6")],
    ]
    _run(executor)
    assert executor.client.place_order.call_count == 2
    first = executor.client.place_order.call_args_list[0].kwargs
    second = executor.client.place_order.call_args_list[1].kwargs
    assert second["order_type"] == OrderType.MARKET
    # fallback sizes ONLY the unfilled remainder, strictly less than the full order
    assert 0.0 < second["qty"] < first["qty"]
    # net position reflects the partial limit fill + market remainder
    assert executor._pnl.position > 0.4


def test_reduce_only_exit_is_always_market() -> None:
    # open a long with a limit, then flatten — the exit must be a guaranteed market
    executor, _ = _mk_executor(OrderType.LIMIT, fallback=True)
    executor.client.get_executions.return_value = [_EXEC]
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        executor._init_store(tmp.name)
        executor._idempotency = MagicMock()
        executor._idempotency.try_claim.return_value = True
        executor._idempotency.resolve.return_value = None

        idx = _df().index
        # bar: long
        executor.strategy.generate_signals.return_value = Series([0.0, 1.0, 1.0], index=idx)
        executor.step(_df())
        assert executor._pnl.position > 0

        # now flatten — exchange reports the held long so reduce-only proceeds
        executor.client.place_order.reset_mock()
        executor.client.cancel_order.reset_mock()
        executor.client.get_positions.return_value = [
            {"symbol": "BTCUSDT", "side": "Buy", "size": "1.0", "avgPrice": "99.0", "leverage": "1"}
        ]
        executor.strategy.generate_signals.return_value = Series([1.0, 1.0, 0.0], index=idx)
        executor.step(_df())

    exit_kw = executor.client.place_order.call_args.kwargs
    assert exit_kw["order_type"] == OrderType.MARKET  # reduce_only exits never rest
    assert exit_kw.get("reduce_only") is True
