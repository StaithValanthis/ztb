from __future__ import annotations

import os
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from ztb.execution.errors import ExecutionError, PollingError
from ztb.execution.executor import ExecRunConfig, Executor
from ztb.execution.models import AccountState, Mode, Position
from ztb.execution.reconcile import reconcile_account as _real_reconcile


@pytest.fixture
def sample_data() -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC")
    data = pd.DataFrame(
        {
            "open": [50000.0] * 200,
            "high": [50100.0] * 200,
            "low": [49900.0] * 200,
            "close": [50000.0] * 200,
            "volume": [100.0] * 200,
        },
        index=idx,
    )
    data.index.name = "timestamp"
    return data


class FakeStrategy:
    name = "test_strat"
    symbols = ["BTCUSDT"]
    timeframe = "60"
    params: dict = {}
    warmup = 100

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        return pd.Series(np.zeros(len(data)), index=data.index)


class SignalStrategy:
    name = "signal_strat"
    symbols = ["BTCUSDT"]
    timeframe = "60"
    params: dict = {}
    warmup = 50

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        arr = np.zeros(len(data))
        arr[-1] = 0.5
        return pd.Series(arr, index=data.index)


@pytest.fixture
def fake_strategy() -> FakeStrategy:
    return FakeStrategy()


@patch("ztb.execution.executor.load_data")
def test_executor_dry_run(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-02",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert result.bars_processed > 0


@patch("ztb.execution.executor.load_data")
def test_executor_dry_run_once(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=True)
    exe = Executor(fake_strategy, config=config)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"


@patch("ztb.execution.executor.load_data")
def test_executor_with_signal(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(signal_strat, config=config)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"


def test_executor_init(fake_strategy: FakeStrategy) -> None:
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    assert exe.config.mode == Mode.DEMO
    assert exe.config.dry_run is True


def test_executor_zero_signal_generates_no_order(fake_strategy: FakeStrategy) -> None:
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    assert exe.state.current_position == 0.0


def test_executor_init_run_sets_state(fake_strategy: FakeStrategy) -> None:
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    assert exe.state.strategy_name == "test_strat"
    assert exe.state.symbol == "BTCUSDT"
    assert exe.state.mode == Mode.DEMO


def test_executor_no_risk_mgr_when_disabled(fake_strategy: FakeStrategy) -> None:
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, risk_enabled=False)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.risk_mgr is None


def test_executor_risk_mgr_when_enabled(fake_strategy: FakeStrategy) -> None:
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, risk_enabled=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.risk_mgr is not None


@patch("ztb.execution.executor.load_data")
def test_executor_no_data_raises(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
) -> None:
    mock_load.return_value = pd.DataFrame()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    with pytest.raises(Exception, match="No data loaded"):
        exe.run(symbol="BTCUSDT", timeframe="60", db_path=":memory:")


def test_executor_compute_target_position(fake_strategy: FakeStrategy) -> None:
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    idx = pd.date_range("2026-01-01", periods=150, freq="h", tz="UTC")
    data = pd.DataFrame(
        {
            "close": [50000.0] * 150,
            "open": [50000.0] * 150,
            "high": [50100.0] * 150,
            "low": [49900.0] * 150,
            "volume": [100.0] * 150,
        },
        index=idx,
    )
    target = exe._compute_target_position(data)
    assert target == 0.0


def test_executor_live_mode_blocked_via_client() -> None:
    from ztb.execution.bybit_client import BybitClient, ClientConfig
    from ztb.execution.live_guard import LiveDisarmedError, LiveGuard

    LiveGuard.disarm()
    with pytest.raises(LiveDisarmedError):
        BybitClient(ClientConfig(mode=Mode.LIVE))


def test_executor_live_mode_allowed_when_armed(tmp_path: Path) -> None:
    from ztb.execution.arm_auth import compute_arm_hash
    from ztb.execution.bybit_client import BybitClient, ClientConfig
    from ztb.execution.live_guard import LiveGuard

    os.environ[LiveGuard.BOARD_TOKEN_VAR] = "test-token"
    hp = tmp_path / "board-arm-hash"
    hp.write_text(compute_arm_hash("test-token"))
    LiveGuard.arm("1", hash_path=hp)
    client = BybitClient(ClientConfig(api_key="k", api_secret="s", mode=Mode.LIVE))
    assert client._base_url == "https://api.bybit.com"
    client.close()
    LiveGuard.disarm()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)


@patch("ztb.execution.executor.load_data")
def test_executor_save_error(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe._save_error("TestError", "test message")
    from ztb.store.exec_io import get_exec_run

    run = get_exec_run(exe._store_conn, exe._exec_run_id)
    assert run is not None


@patch("ztb.execution.executor.load_data")
def test_executor_compute_target_warmup_insufficient(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
) -> None:
    mock_load.return_value = pd.DataFrame()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    idx = pd.date_range("2026-01-01", periods=50, freq="h", tz="UTC")
    data = pd.DataFrame(
        {
            "close": [50000.0] * 50,
            "open": [50000.0] * 50,
            "high": [50100.0] * 50,
            "low": [49900.0] * 50,
            "volume": [100.0] * 50,
        },
        index=idx,
    )
    target = exe._compute_target_position(data)
    assert target == 0.0


@patch("ztb.execution.executor.load_data")
def test_executor_apply_risk_no_risk_mgr(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, risk_enabled=False)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    sig, decision = exe._apply_risk(0.5, 0.0, 50000.0, 100000.0, "2026-01-01T00:00:00Z")
    assert sig == 0.5
    assert decision is None


@patch("ztb.execution.executor.load_data")
def test_executor_apply_risk_halt(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, risk_enabled=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.risk_mgr is not None
    exe.risk_mgr.kill_switch.update(200000.0)
    sig, decision = exe._apply_risk(0.5, 0.0, 50000.0, 100000.0, "2026-01-01T00:00:00Z")
    assert sig == 0.0
    assert decision is not None
    assert decision.action.value == "halt"


@patch("ztb.execution.executor.load_data")
def test_executor_apply_risk_reduce(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, risk_enabled=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.risk_mgr is not None
    sig, decision = exe._apply_risk(5.0, 0.0, 100000.0, 100000.0, "2026-01-01T00:00:00Z")
    assert decision is not None
    assert decision.action.value == "reduce"
    assert sig == 3.0


@patch("ztb.execution.executor.load_data")
def test_executor_step_halt_sets_zero_signal(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, risk_enabled=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    assert exe.risk_mgr is not None
    exe.risk_mgr.kill_switch.update(200000.0)
    result = exe.step(sample_data)
    assert result["signal"] == 0.0


@patch("ztb.execution.executor.load_data")
def test_executor_non_dry_run_raises_without_client(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    with pytest.raises(Exception, match="No BybitClient configured"):
        exe.step(sample_data)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_non_dry_run_with_client(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_order_1"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.state.current_position = 0.0
    result = exe.step(sample_data)
    assert result["order_placed"] is False
    assert result["signal"] == 0.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_non_dry_run_places_order(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_order_1"}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    result = exe.step(sample_data)
    assert result["signal"] == 0.5
    assert result["order_placed"] is True
    assert result["order"]["order_id"] == "test_order_1"


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_skipped_order_early_return(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"skipped": True, "reason": "Qty too small"}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    result = exe.step(sample_data)
    assert result["signal"] == 0.5
    assert result.get("order_skipped") is True
    assert result.get("skip_reason") == "Qty too small"
    assert result.get("order_placed") is False
    assert result.get("order") is None


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_skipped_order_no_cost(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"skipped": True, "reason": "Qty too small"}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    pnl_before = exe._pnl.equity(50000.0)

    result = exe.step(sample_data)

    pnl_after = exe._pnl.equity(50000.0)
    assert result.get("order_skipped") is True
    assert pnl_before == pnl_after, "Costs should NOT be applied on skipped order"


@patch("ztb.execution.executor.load_data")
def test_executor_once_mode_insufficient_data(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
) -> None:
    idx = pd.date_range("2026-01-01", periods=50, freq="h", tz="UTC")
    data = pd.DataFrame(
        {
            "close": [50000.0] * 50,
            "open": [50000.0] * 50,
            "high": [50100.0] * 50,
            "low": [49900.0] * 50,
            "volume": [100.0] * 50,
        },
        index=idx,
    )
    data.index.name = "timestamp"
    mock_load.side_effect = [data, pd.DataFrame()]
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=True, warmup_bars=100)
    exe = Executor(fake_strategy, config=config)
    with pytest.raises(Exception, match="Cannot fetch enough historical data"):
        exe.run(symbol="BTCUSDT", timeframe="60", db_path=":memory:")


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_idempotency_restores_order(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_order_1"}
    mock_bybit_cls.return_value = mock_client

    from ztb.execution.idempotency import make_intent_hash, make_order_link_id

    signal_strat = SignalStrategy()
    config = ExecRunConfig(
        mode=Mode.DEMO, dry_run=False, risk_enabled=False, order_sizing_buffer=1.0
    )
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    equity = config.initial_cash
    close_price = float(sample_data["close"].iloc[-1])
    target_qty = round(0.5 * equity / close_price, config.asset_precision)
    intent_hash = make_intent_hash(target_qty, 0.0)
    order_link_id = make_order_link_id(
        "signal_strat", "BTCUSDT", str(sample_data.index[-1]), intent_hash
    )
    exe._idempotency.try_claim(order_link_id, "existing_order_1")
    exe._idempotency.resolve(order_link_id, "placed", "existing_order_1")
    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert result["order"]["order_id"] == "existing_order_1"
    assert result["order"]["restored"] is True


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_signal_to_qty_conversion(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}

    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True)
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    mock_client.place_order.assert_called_once()
    assert mock_client.get_positions.call_count >= 1


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_reconcile_called_after_placement(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}

    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True)
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert mock_client.get_positions.call_count >= 1


@patch("ztb.execution.executor.load_data")
def test_executor_pnl_apply_fill_buy(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    exe._pnl.apply_fill(1.0, 50000.0)
    exe._sync_pnl_state()
    assert exe.state.current_position == 1.0
    assert exe.state.avg_entry_price == 50000.0


@patch("ztb.execution.executor.load_data")
def test_executor_unrealized_pnl(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    exe._pnl.apply_fill(1.0, 50000.0)
    upnl = exe._pnl.unrealized_pnl(50100.0)
    assert upnl == 100.0


@patch("ztb.execution.executor.load_data")
def test_executor_reconcile(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    exe.state.current_position = 1.0
    exe.state.avg_entry_price = 50000.0
    report = exe._reconcile(1.0, 50000.0, "2026-01-01T00:00:00Z")
    assert report.matched is True


@patch("ztb.execution.executor.load_data")
def test_executor_dry_run_updates_avg_price(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    result = exe.step(sample_data)
    assert result["signal"] == 0.5
    assert exe.state is not None
    assert exe._pnl.avg_entry_price == pytest.approx(50000.0, abs=1.0)


@patch("ztb.execution.executor.load_data")
def test_executor_pnl_zero_delta(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    exe._pnl.apply_fill(1.0, 50000.0)
    exe._sync_pnl_state()
    assert exe.state.avg_entry_price == 50000.0


@patch("ztb.execution.executor.load_data")
def test_executor_pnl_partial_close(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    exe._pnl.apply_fill(2.0, 50000.0)
    exe._pnl.apply_fill(-1.0, 51000.0)
    exe._sync_pnl_state()
    assert exe.state.realized_pnl == pytest.approx(1000.0)


@patch("ztb.execution.executor.load_data")
def test_executor_pnl_close_all(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    exe._pnl.apply_fill(-2.0, 50000.0)
    exe._pnl.apply_fill(2.0, 51000.0)
    exe._sync_pnl_state()
    assert exe.state.avg_entry_price == 0.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_reconcile_api_path(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    exe.state.current_position = 0.0
    exe.client = mock_client
    report = exe._reconcile(0.0, 50000.0, "2026-01-01T00:00:00Z")
    assert report.matched is True


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_reconcile_api_path_exception(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.side_effect = Exception("API error")
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    exe.state.current_position = 0.0
    exe.client = mock_client
    report = exe._reconcile(0.0, 50000.0, "2026-01-01T00:00:00Z")
    assert report.matched is True


@patch("ztb.execution.executor.load_data")
def test_executor_reconcile_equity_no_inflation(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """Equity = initial_cash + realized_pnl + unrealized_pnl, not abs(pos)*price."""
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    exe._pnl.apply_fill(1.0, 30000.0, commission=0.0, slippage=0.0)
    exe._sync_pnl_state()

    import ztb.execution.executor as _exec_mod

    captured: dict[str, object] = {}

    def capture_expected(exp: object, act: object, sym: str) -> object:
        captured["expected"] = exp
        return _real_reconcile(exp, act, sym)

    with patch.object(_exec_mod, "reconcile_account", capture_expected):
        exe._reconcile(1.0, 40000.0, "2026-01-01T00:00:00Z")

    expected_upnl = (40000.0 - 30000.0) * 1.0
    expected_equity = config.initial_cash + expected_upnl
    cap = cast("AccountState", captured["expected"])
    assert cap.total_equity == pytest.approx(expected_equity)
    assert cap.total_equity < config.initial_cash + 1.0 * 40000.0


@patch("ztb.execution.executor.load_data")
def test_executor_step_equity_no_inflation(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Step equity uses unrealized PnL, not position*price, for position sizing."""
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, order_sizing_buffer=1.0)
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    assert exe.state is not None
    exe._pnl.apply_fill(1.0, 30000.0)
    exe._sync_pnl_state()
    result = exe.step(sample_data)
    expected_upnl = (50000.0 - 30000.0) * 1.0
    expected_equity = config.initial_cash + expected_upnl
    assert expected_equity == pytest.approx(120000.0)
    close_price = float(sample_data["close"].iloc[-1])
    target_qty = round(0.5 * expected_equity / close_price, config.asset_precision)
    assert result["target_position"] == pytest.approx(target_qty)
    assert result["target_position"] < round(
        0.5 * (config.initial_cash + 1.0 * close_price) / close_price,
        config.asset_precision,
    )


@patch("ztb.execution.executor.load_data")
def test_executor_equity_short_position_no_inflation(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Short position equity uses unrealized PnL (negative), not abs(pos)*price."""
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, order_sizing_buffer=1.0)
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    assert exe.state is not None
    exe._pnl.apply_fill(-1.0, 30000.0)
    exe._sync_pnl_state()
    exe.step(sample_data)
    expected_upnl = (50000.0 - 30000.0) * -1.0
    expected_equity = config.initial_cash + expected_upnl
    assert expected_equity == pytest.approx(80000.0)
    close_price = float(sample_data["close"].iloc[-1])
    target_qty = round(0.5 * expected_equity / close_price, config.asset_precision)
    assert exe.state.current_position == pytest.approx(target_qty)


@patch("ztb.execution.executor.load_data")
def test_executor_pnl_existing_avg(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    assert exe.state is not None
    exe._pnl.apply_fill(1.0, 50000.0)
    exe._pnl.apply_fill(1.0, 51000.0)
    exe._sync_pnl_state()
    expected_avg = (50000.0 * 1.0 + 51000.0 * 1.0) / 2.0
    assert abs(exe.state.avg_entry_price - expected_avg) < 0.01


@patch("ztb.execution.executor.load_data")
def test_executor_dry_run_no_costs(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, commission=0.001, slippage=0.001)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    assert exe.state is not None
    exe.step(sample_data)
    assert exe._pnl.realized_pnl < 0


@patch("ztb.execution.executor.load_data")
def test_executor_config_loop_default(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    assert config.loop is False
    assert config.poll_interval_seconds == 60
    assert config.lookback_bars == 0


@patch("ztb.execution.executor.load_data")
def test_executor_config_loop_true_when_not_dry_run(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO)
    assert config.loop is True


@patch("ztb.execution.executor.load_data")
def test_executor_config_loop_false_when_once(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, once=True)
    assert config.loop is False


@patch("ztb.execution.executor.load_data")
def test_executor_config_loop_enabled(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=10.0)
    exe = Executor(fake_strategy, config=config)
    assert exe.config.loop is True
    assert exe.config.poll_interval_seconds == 10.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_run_with_loop(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    call_count = 0

    def sleep_side_effect(seconds: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise Exception("stop loop")

    mock_sleep.side_effect = sleep_side_effect
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01)
    exe = Executor(fake_strategy, config=config)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert result.bars_processed > 0


@patch("ztb.execution.executor.load_data")
def test_ensure_warmup_sufficient(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    result = exe._ensure_warmup(sample_data, 50, "BTCUSDT", "60", "linear", "2026-01-01")
    assert len(result) >= 50


@patch("ztb.execution.executor.load_data")
def test_ensure_warmup_extends(mock_load: MagicMock, fake_strategy: FakeStrategy) -> None:
    idx = pd.date_range("2026-01-01", periods=50, freq="h", tz="UTC")
    small_data = pd.DataFrame(
        {
            "open": [50000.0] * 50,
            "high": [50100.0] * 50,
            "low": [49900.0] * 50,
            "close": [50000.0] * 50,
            "volume": [100.0] * 50,
        },
        index=idx,
    )
    small_data.index.name = "timestamp"
    idx2 = pd.date_range("2025-12-20", periods=160, freq="h", tz="UTC")
    extended_data = pd.DataFrame(
        {
            "open": [50000.0] * 160,
            "high": [50100.0] * 160,
            "low": [49900.0] * 160,
            "close": [50000.0] * 160,
            "volume": [100.0] * 160,
        },
        index=idx2,
    )
    extended_data.index.name = "timestamp"
    mock_load.return_value = extended_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    result = exe._ensure_warmup(small_data, 150, "BTCUSDT", "60", "linear", "2026-01-01")
    assert len(result) >= 150


@patch("ztb.execution.executor.load_data")
def test_ensure_warmup_fails_empty(mock_load: MagicMock, fake_strategy: FakeStrategy) -> None:
    idx = pd.date_range("2026-01-01", periods=50, freq="h", tz="UTC")
    small_data = pd.DataFrame(
        {
            "open": [50000.0] * 50,
            "high": [50100.0] * 50,
            "low": [49900.0] * 50,
            "close": [50000.0] * 50,
            "volume": [100.0] * 50,
        },
        index=idx,
    )
    small_data.index.name = "timestamp"
    mock_load.return_value = pd.DataFrame()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    with pytest.raises(ExecutionError, match="Cannot fetch enough historical data"):
        exe._ensure_warmup(small_data, 150, "BTCUSDT", "60", "linear", "2026-01-01")


@patch("ztb.execution.executor.load_data")
def test_fetch_new_bars_no_new_data(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = pd.DataFrame()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    result = exe._fetch_new_bars(sample_data, "BTCUSDT", "60", "linear")
    assert len(result) == len(sample_data)


@patch("ztb.execution.executor.load_data")
def test_fetch_new_bars_with_new_bar(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    last_ts = sample_data.index[-1]
    new_idx = pd.date_range(start=last_ts + pd.Timedelta(hours=1), periods=1, freq="h", tz="UTC")
    new_bar = pd.DataFrame(
        {
            "open": [50100.0],
            "high": [50200.0],
            "low": [50000.0],
            "close": [50150.0],
            "volume": [150.0],
        },
        index=new_idx,
    )
    new_bar.index.name = "timestamp"
    mock_load.return_value = new_bar
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    result = exe._fetch_new_bars(sample_data, "BTCUSDT", "60", "linear")
    assert len(result) == len(sample_data) + 1


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_loop_killswitch_stops(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    from ztb.execution.killswitch import LiveKillSwitch

    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01)
    ks = LiveKillSwitch()
    ks.manual_trip("test")
    exe = Executor(fake_strategy, config=config, killswitch=ks)
    exe._init_run()
    exe._init_store(":memory:")
    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")
    assert any("Killswitch" in e for e in exe.state.errors)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_loop_error_retry_then_stop(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")

    call_count = 0

    def failing_step(data: pd.DataFrame) -> dict:
        nonlocal call_count
        call_count += 1
        raise ValueError("poll error")

    exe.step = failing_step  # type: ignore[assignment]

    with pytest.raises(PollingError, match="poll error"):
        exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    assert call_count == 3


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_loop_sigterm_stops_via_flag(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")

    mock_sleep.side_effect = lambda _: setattr(exe, "_sigterm_stop", True)

    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    assert exe._sigterm_stop is True


@patch("ztb.execution.executor.signal.signal")
def test_setup_sigterm_sets_flag_not_exit(
    mock_signal_signal: MagicMock,
    fake_strategy: FakeStrategy,
) -> None:
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()

    original_handler = object()

    def capture_handler(signum: int, handler: object) -> object:
        nonlocal original_handler
        return original_handler

    mock_signal_signal.side_effect = capture_handler

    exe._setup_sigterm()

    assert exe._sigterm_stop is False

    registered = mock_signal_signal.call_args[0][1]
    registered(15, None)

    assert exe._sigterm_stop is True


# ---------------------------------------------------------------------------
# Startup reconciliation — adopt exchange position on boot
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_startup_reconcile_adopts_exchange_position(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {
            "symbol": "BTCUSDT",
            "size": "1.5",
            "avgPrice": "30000.0",
            "unrealisedPnl": "30000.0",
            "cumRealisedPnl": "500.0",
            "updatedTime": "2026-06-13T00:00:00Z",
        }
    ]
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "175000.0",
                        "walletBalance": "145000.0",
                        "unrealisedPnl": "30000.0",
                    }
                ]
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True, risk_enabled=False)
    exe = Executor(fake_strategy, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert exe._pnl.position == pytest.approx(1.5)
    assert exe._pnl.avg_entry_price == pytest.approx(30000.0)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_startup_reconcile_skips_adoption_when_no_exchange_position(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True, risk_enabled=False)
    exe = Executor(fake_strategy, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert exe._pnl.position == 0.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_startup_reconcile_adopts_short_position(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {
            "symbol": "BTCUSDT",
            "size": "-2.0",
            "avgPrice": "45000.0",
            "unrealisedPnl": "10000.0",
            "cumRealisedPnl": "200.0",
            "updatedTime": "2026-06-13T00:00:00Z",
        }
    ]
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "110000.0",
                        "walletBalance": "100000.0",
                        "unrealisedPnl": "10000.0",
                    }
                ]
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True, risk_enabled=False)
    exe = Executor(fake_strategy, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert exe._pnl.position == pytest.approx(-2.0)
    assert exe._pnl.avg_entry_price == pytest.approx(45000.0)


# ---------------------------------------------------------------------------
# Trade-on-signal-change — prevent over-trading
# ---------------------------------------------------------------------------


def test_signal_change_initialized_false_first_step() -> None:
    """First _step_impl call has _signal_initialized=False so signal_changed=True."""
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(FakeStrategy(), config=config)
    exe._init_run()
    assert exe._signal_initialized is False
    assert exe._last_executed_signal == 0.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_signal_change_tracks_after_first_trade(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """After placing an order, _last_executed_signal reflects the traded signal."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.step(sample_data)

    assert exe._signal_initialized is True
    assert exe._last_executed_signal == 0.5


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_signal_change_suppresses_duplicate_orders(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When signal is unchanged, no order is placed even if delta > 0."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result1 = exe.step(sample_data)
    assert result1["order_placed"] is True
    assert exe._last_executed_signal == 0.5

    # Second step with same signal — should NOT place an order
    mock_client.place_order.reset_mock()
    result2 = exe.step(sample_data)
    assert result2["order_placed"] is False
    mock_client.place_order.assert_not_called()
    assert exe._last_executed_signal == 0.5


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_signal_change_allows_order_when_signal_differs(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When signal changes, a new order is placed."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    class FlipSignal:
        name = "flip_strat"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def __init__(self) -> None:
            self._call_count = 0

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            self._call_count += 1
            arr = 0.5 * np.ones(len(data))
            if self._call_count > 1:
                arr[-1] = 0.0
            return pd.Series(arr, index=data.index)

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(FlipSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result1 = exe.step(sample_data)
    assert result1["order_placed"] is True
    assert result1["signal"] == 0.5

    mock_client.place_order.reset_mock()
    result2 = exe.step(sample_data)
    assert result2["order_placed"] is True
    assert result2["signal"] == 0.0
    mock_client.place_order.assert_called_once()


@patch("ztb.execution.executor.load_data")
def test_signal_change_dry_run_always_trades(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Dry run mode is NOT affected by signal-change guard."""
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(SignalStrategy(), config=config)
    exe._init_run()
    exe._init_store(":memory:")

    assert exe._signal_initialized is False

    result1 = exe.step(sample_data)
    assert result1["order_placed"] is False
    assert exe._signal_initialized is True
    assert exe._last_executed_signal == 0.5


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_startup_reconcile_then_signal_guard(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """After startup reconcile adopts a position, the first step still
    processes (signal_changed=True)."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_positions.return_value = [
        {
            "symbol": "BTCUSDT",
            "size": "0.5",
            "avgPrice": "48000.0",
            "unrealisedPnl": "1000.0",
            "cumRealisedPnl": "100.0",
            "updatedTime": "2026-06-13T00:00:00Z",
        }
    ]
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "101000.0",
                        "walletBalance": "100000.0",
                        "unrealisedPnl": "1000.0",
                    }
                ]
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True, risk_enabled=False)
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )

    assert result.status == "completed"
    assert exe._signal_initialized is True
    assert exe._last_executed_signal == 0.5


# ---------------------------------------------------------------------------
# --loop mode continuity: skipped-order tracking, signal init, polling
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_step_increments_bars_processed_on_skipped_order(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """bars_processed increments when order is skipped due to qty < minOrderQty."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"skipped": True, "reason": "Qty too small"}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    bars_before = exe.state.bars_processed
    result = exe.step(sample_data)
    assert result.get("order_skipped") is True
    assert exe.state.bars_processed == bars_before + 1


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_signal_initialized_set_on_first_bar_even_if_order_skipped(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """_signal_initialized becomes True after first step even when order skipped."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"skipped": True, "reason": "Qty too small"}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    assert exe._signal_initialized is False
    result = exe.step(sample_data)
    assert result.get("order_skipped") is True
    assert exe._signal_initialized is True
    assert exe._last_executed_signal == 0.5


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_full_historical_loop_skipped_orders_bars_processed(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """After full historical bar-by-bar processing with only skipped orders,
    bars_processed == len(data) - warmup."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"skipped": True, "reason": "Qty too small"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False, loop=False)
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    effective_warmup = max(signal_strat.warmup, config.warmup_bars)
    expected = len(sample_data) - effective_warmup
    assert result.bars_processed == expected, (
        f"Expected {expected} bars (len={len(sample_data)}, warmup={effective_warmup}), "
        f"got {result.bars_processed}"
    )


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
@patch("ztb.execution.executor.BybitClient")
def test_polling_loop_stays_alive_after_skipped_order(
    mock_bybit_cls: MagicMock,
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Polling loop continues running after a skipped order (does not exit)."""
    call_count = 0

    def sleep_side_effect(seconds: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 3:
            raise Exception("stop loop")

    mock_sleep.side_effect = sleep_side_effect
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"skipped": True, "reason": "Qty too small"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    signal_strat = SignalStrategy()
    config = ExecRunConfig(
        mode=Mode.DEMO, dry_run=False, loop=True, poll_interval_seconds=0.01, risk_enabled=False
    )
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert call_count >= 3


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_no_zombie_exec_runs(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """After full run with only skipped orders, exec_run is properly completed
    with bars_processed > 0 (no zombie 'running' record)."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"skipped": True, "reason": "Qty too small"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False, loop=False)
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert result.bars_processed > 0


# ---------------------------------------------------------------------------
# ZTB-1339: Wallet balance + ClientError handling + warmup reconciliation
# ---------------------------------------------------------------------------


def test_pnl_set_initial_cash() -> None:
    from ztb.engine.pnl import PnLCalculator

    pnl = PnLCalculator(initial_cash=100_000.0)
    assert pnl.equity(50000.0) == 100_000.0
    pnl.set_initial_cash(150_000.0)
    assert pnl.equity(50000.0) == 150_000.0


def test_reconcile_report_actual_wallet_fields() -> None:
    from ztb.execution.models import AccountState
    from ztb.execution.reconcile import reconcile_account

    expected = AccountState(
        total_equity=100000.0,
        wallet_balance=100000.0,
        unrealized_pnl=0.0,
        positions={
            "BTCUSDT": Position(
                symbol="BTCUSDT",
                size=1.0,
                avg_price=50000.0,
                unrealized_pnl=0.0,
                realized_pnl=0.0,
                timestamp="",
            )
        },
    )
    actual = AccountState(
        total_equity=120000.0,
        wallet_balance=105000.0,
        unrealized_pnl=15000.0,
        positions={
            "BTCUSDT": Position(
                symbol="BTCUSDT",
                size=1.0,
                avg_price=50000.0,
                unrealized_pnl=15000.0,
                realized_pnl=5000.0,
                timestamp="",
            )
        },
    )
    report = reconcile_account(expected, actual, "BTCUSDT")
    assert report.actual_wallet_balance == 105000.0
    assert report.actual_equity == 120000.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_step_client_error_graceful(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    from ztb.execution.errors import ClientError

    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    mock_client.place_order.side_effect = ClientError(200, "not enough balance")

    result = exe.step(sample_data)
    assert result.get("client_error") is True
    assert "ClientError" in result.get("error", "")


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_warmup_reconcile_adopts_wallet_balance(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {
            "symbol": "BTCUSDT",
            "size": "1.5",
            "avgPrice": "30000.0",
            "unrealisedPnl": "30000.0",
            "cumRealisedPnl": "500.0",
            "updatedTime": "2026-06-13T00:00:00Z",
        }
    ]
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "175000.0",
                        "walletBalance": "145000.0",
                        "unrealisedPnl": "30000.0",
                    }
                ]
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True, risk_enabled=False)
    exe = Executor(fake_strategy, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    close_price = float(sample_data["close"].iloc[-1])
    assert exe._pnl.position == pytest.approx(1.5)
    assert exe._pnl.avg_entry_price == pytest.approx(30000.0)
    expected_equity = 145000.0 + (close_price - 30000.0) * 1.5
    assert exe._pnl.equity(close_price) == pytest.approx(expected_equity, abs=1.0)
    assert exe._pnl.snapshot.initial_cash == pytest.approx(145000.0)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_step_impl_uses_wallet_balance(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "95000.0",
                        "walletBalance": "95000.0",
                        "unrealisedPnl": "0.0",
                    }
                ]
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    signal_strat = SignalStrategy()
    config = ExecRunConfig(
        mode=Mode.DEMO, dry_run=False, once=True, risk_enabled=False, order_sizing_buffer=1.0
    )
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    close_price = float(sample_data["close"].iloc[-1])
    expected_qty = round(0.5 * 95000.0 / close_price, config.asset_precision)
    assert exe._pnl.position == pytest.approx(expected_qty, abs=1e-8)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_polling_loop_skips_client_error(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    from ztb.execution.errors import ClientError
    from ztb.execution.executor import time_module as exec_time_module

    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    class FlippingSignal:
        name = "flip_strat"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50
        _call_count = 0

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            self._call_count += 1
            arr = np.zeros(len(data))
            if self._call_count % 2 == 1:
                arr[-1] = 0.5
            return pd.Series(arr, index=data.index)

    config = ExecRunConfig(
        mode=Mode.DEMO, dry_run=False, loop=True, poll_interval_seconds=0.01, risk_enabled=False
    )
    exe = Executor(FlippingSignal(), config=config, client=mock_client)
    exe._init_run()
    exe._init_store(":memory:")

    loop_calls = 0
    real_sleep = exec_time_module.sleep

    def sleep_and_sigterm(seconds: float) -> None:
        nonlocal loop_calls
        loop_calls += 1
        real_sleep(0.001)
        if loop_calls >= 4:
            exe._sigterm_stop = True

    call_count = 0

    def place_order_side_effect(**kwargs: object) -> dict:
        nonlocal call_count
        call_count += 1
        raise ClientError(200, "not enough")

    mock_client.place_order.side_effect = place_order_side_effect

    with patch.object(exec_time_module, "sleep", sleep_and_sigterm):
        exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    assert call_count >= 2
    assert not any("Max polling errors" in e for e in exe.state.errors)


# ---------------------------------------------------------------------------
# ZTB-1378: Reconcile adoption shall NOT overwrite configured initial_cash
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_startup_reconcile_syncs_initial_cash_with_wallet(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {
            "symbol": "BTCUSDT",
            "size": "1.5",
            "avgPrice": "30000.0",
            "unrealisedPnl": "30000.0",
            "cumRealisedPnl": "500.0",
            "updatedTime": "2026-06-13T00:00:00Z",
        }
    ]
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "175000.0",
                        "walletBalance": "145000.0",
                        "unrealisedPnl": "30000.0",
                    }
                ]
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        once=True,
        risk_enabled=False,
        initial_cash=100.0,
    )
    exe = Executor(FakeStrategy(), config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    close_price = float(sample_data["close"].iloc[-1])
    expected_equity = 145000.0 + (close_price - 30000.0) * 1.5
    assert exe._pnl.equity(close_price) == pytest.approx(expected_equity, abs=1.0)
    assert exe._pnl.snapshot.initial_cash == pytest.approx(145000.0)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_startup_reconcile_syncs_initial_cash_even_with_position(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {
            "symbol": "BTCUSDT",
            "size": "0.5",
            "avgPrice": "40000.0",
            "unrealisedPnl": "5000.0",
            "cumRealisedPnl": "200.0",
            "updatedTime": "2026-06-13T00:00:00Z",
        }
    ]
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "95000.0",
                        "walletBalance": "90000.0",
                        "unrealisedPnl": "5000.0",
                    }
                ]
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        once=True,
        risk_enabled=False,
        initial_cash=42.0,
    )
    exe = Executor(FakeStrategy(), config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert exe._pnl.snapshot.initial_cash == pytest.approx(90000.0)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_adoption_still_adopts_position(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = [
        {
            "symbol": "BTCUSDT",
            "size": "-2.0",
            "avgPrice": "45000.0",
            "unrealisedPnl": "10000.0",
            "cumRealisedPnl": "300.0",
            "updatedTime": "2026-06-13T00:00:00Z",
        }
    ]
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "80000.0",
                        "walletBalance": "70000.0",
                        "unrealisedPnl": "10000.0",
                    }
                ]
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True, risk_enabled=False)
    exe = Executor(FakeStrategy(), config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert exe._pnl.position == pytest.approx(-2.0)
    assert exe._pnl.avg_entry_price == pytest.approx(45000.0)


# ---------------------------------------------------------------------------
# ZTB-1422: demo top-up + reduce_only
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_demo_run_calls_top_up(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """top_up_demo_account is called when mode=DEMO and not dry_run."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True, risk_enabled=False)
    exe = Executor(fake_strategy, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    mock_client.top_up_demo_account.assert_called_once_with("USDT", str(config.initial_cash))


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_dry_run_skips_top_up(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """top_up_demo_account is NOT called when dry_run=True."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=True, risk_enabled=False)
    exe = Executor(fake_strategy, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    mock_client.top_up_demo_account.assert_not_called()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_live_mode_skips_top_up(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """top_up_demo_account is NOT called when mode=LIVE."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.LIVE, dry_run=False, once=True, risk_enabled=False)
    exe = Executor(fake_strategy, config=config, client=mock_client)
    exe._init_run()
    exe._init_store(":memory:")
    assert exe.state is not None
    exe.state.current_position = 0.0
    exe.client = mock_client
    result = exe.step(sample_data)
    assert result is not None
    mock_client.top_up_demo_account.assert_not_called()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_top_up_failure_non_fatal(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """Top-up failure does not crash the run; run continues."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.top_up_demo_account.side_effect = Exception("top-up failed")
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True, risk_enabled=False)
    exe = Executor(fake_strategy, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    mock_client.top_up_demo_account.assert_called_once()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reduce_only_for_sell_to_reduce_long(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When delta < 0 and current_position > 0, reduce_only=True."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)

    class ReduceLongSignal:
        name = "reduce_long"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = 0.5
            return pd.Series(arr, index=data.index)

    exe = Executor(ReduceLongSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._pnl.apply_fill(2.0, 50000.0)
    exe._sync_pnl_state()

    result = exe.step(sample_data)
    assert result["delta"] < 0
    assert exe.state.current_position > 0

    call_kwargs = mock_client.place_order.call_args.kwargs
    assert call_kwargs.get("reduce_only") is True


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reduce_only_for_buy_to_reduce_short(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When delta > 0 and current_position < 0, reduce_only=True."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)

    class ReduceShortSignal:
        name = "reduce_short"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = -0.5
            return pd.Series(arr, index=data.index)

    exe = Executor(ReduceShortSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._pnl.apply_fill(-2.0, 50000.0)
    exe._sync_pnl_state()

    result = exe.step(sample_data)
    assert result["delta"] > 0
    assert exe.state.current_position < 0

    call_kwargs = mock_client.place_order.call_args.kwargs
    assert call_kwargs.get("reduce_only") is True


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_no_reduce_only_on_position_open(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When opening a new position from flat, reduce_only=False."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.state.current_position = 0.0

    result = exe.step(sample_data)
    assert result["current_position"] == 0.0
    assert abs(result["delta"]) > 1e-12

    call_kwargs = mock_client.place_order.call_args.kwargs
    assert call_kwargs.get("reduce_only") is False


# ---------------------------------------------------------------------------
# ZTB-1465: Wallet balance fix — cap qty to available_balance
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_balance_cap_caps_qty_when_insufficient_balance(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When available_balance is low, qty is capped to prevent 'ab not enough'."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_capped"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "500.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "1000.0",
                        "walletBalance": "1000.0",
                        "availableBalance": "500.0",
                        "unrealisedPnl": "0.0",
                    }
                ],
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False, max_leverage=2.0)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.state.current_position = 0.0

    result = exe.step(sample_data)

    assert result.get("order_skipped") is not True
    assert result["order_placed"] is True


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_balance_cap_reduces_qty_when_balance_very_low(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When available_balance is very low, qty is capped below the signal target."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_capped"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "50.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "100.0",
                        "walletBalance": "100.0",
                        "availableBalance": "50.0",
                        "unrealisedPnl": "0.0",
                    }
                ],
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO, dry_run=False, risk_enabled=False, max_leverage=1.0, order_sizing_buffer=1.0
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.state.current_position = 0.0

    result = exe.step(sample_data)

    assert result["order_placed"] is True
    call_kwargs = mock_client.place_order.call_args.kwargs
    capped_qty = call_kwargs["qty"]
    assert capped_qty == 0.001


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_balance_cap_skips_when_capped_qty_zero(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When capped qty rounds to zero, order is skipped."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "0.0001",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "0.001",
                        "walletBalance": "0.001",
                        "availableBalance": "0.0001",
                        "unrealisedPnl": "0.0",
                    }
                ],
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False, max_leverage=1.0)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.state.current_position = 0.0

    result = exe.step(sample_data)
    assert result.get("order_skipped") is True
    assert "below minimum" in result.get("skip_reason", "").lower()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_balance_cap_does_not_apply_to_reduce_only(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Reduce-only orders are not capped — exchange does not check balance."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_reduce"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "1.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "100.0",
                        "walletBalance": "100.0",
                        "availableBalance": "1.0",
                        "unrealisedPnl": "0.0",
                    }
                ],
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False, max_leverage=1.0)

    class ReduceSignal:
        name = "reduce_signal"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = -0.5
            return pd.Series(arr, index=data.index)

    exe = Executor(ReduceSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._pnl.apply_fill(2.0, 50000.0)
    exe._sync_pnl_state()

    result = exe.step(sample_data)

    assert result["order_placed"] is True
    call_kwargs = mock_client.place_order.call_args.kwargs
    assert call_kwargs.get("reduce_only") is True
    assert call_kwargs["qty"] > 0.001


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_balance_cap_does_not_apply_when_no_wallet_data(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When wallet fetch returns empty/zero balance, no cap is applied."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_nocap"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.state.current_position = 0.0

    result = exe.step(sample_data)
    assert result["order_placed"] is True


def test_polling_error_class_exists() -> None:
    assert issubclass(PollingError, ExecutionError)
    err = PollingError("test message")
    assert str(err) == "test message"


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_loop_sigterm_no_polling_error(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")

    exe._sigterm_stop = True

    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    assert not any("Max polling errors" in e for e in exe.state.errors)


# ---------------------------------------------------------------------------
# ZTB-1407: initial_cash sync with wallet balance + order sizing safety buffer
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_startup_reconcile_syncs_initial_cash_no_position(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """initial_cash is synced with wallet balance even when no position exists."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "500.0",
                        "walletBalance": "500.0",
                        "unrealisedPnl": "0.0",
                    }
                ]
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        once=True,
        risk_enabled=False,
        initial_cash=100000.0,
    )
    exe = Executor(fake_strategy, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert exe._pnl.snapshot.initial_cash == pytest.approx(500.0)


@patch("ztb.execution.executor.load_data")
def test_order_sizing_buffer_reduces_position(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Default order_sizing_buffer=0.95 reduces position size vs buffer=1.0."""
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()

    config_full = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=True, order_sizing_buffer=1.0)
    exe_full = Executor(signal_strat, config=config_full)
    result_full = exe_full.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result_full.status == "completed"

    config_buf = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=True, order_sizing_buffer=0.5)
    exe_buf = Executor(signal_strat, config=config_buf)
    result_buf = exe_buf.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result_buf.status == "completed"

    assert exe_buf.state.current_position == pytest.approx(
        exe_full.state.current_position * 0.5, abs=1e-8
    )


@patch("ztb.execution.executor.load_data")
def test_order_sizing_buffer_unit(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Buffer directly scales equity used for target_qty."""
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, order_sizing_buffer=0.8)
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    assert exe.state is not None
    exe._pnl.apply_fill(1.0, 30000.0)
    exe._sync_pnl_state()
    result = exe.step(sample_data)
    close_price = float(sample_data["close"].iloc[-1])
    expected_upnl = (50000.0 - 30000.0) * 1.0
    expected_equity = (config.initial_cash + expected_upnl) * 0.8
    target_qty = round(0.5 * expected_equity / close_price, config.asset_precision)
    assert result["target_position"] == pytest.approx(target_qty)


# ---------------------------------------------------------------------------
# Finding 2: DEMO equity cap tests (restored from main with order_sizing_buffer=1.0)
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_demo_mode_equity_cap_when_wallet_exceeds_initial_cash(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """DEMO mode caps equity at initial_cash when wallet equity exceeds it."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_capped"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "200000.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "200000.0",
                        "walletBalance": "200000.0",
                        "availableBalance": "200000.0",
                        "unrealisedPnl": "100000.0",
                    }
                ],
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        once=True,
        risk_enabled=False,
        initial_cash=100000.0,
        order_sizing_buffer=1.0,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    close_price = float(sample_data["close"].iloc[-1])
    capped_equity = config.initial_cash
    expected_qty = round(0.5 * capped_equity / close_price, config.asset_precision)
    assert exe._pnl.position == pytest.approx(expected_qty, abs=1e-8)
    assert exe._pnl.position < round(0.5 * 200000.0 / close_price, config.asset_precision)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_demo_mode_equity_cap_when_wallet_fetch_fails(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """DEMO mode wallet fetch failure falls through to PnLCalculator equity."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.side_effect = Exception("network error")
    mock_client.place_order.return_value = {"orderId": "oid"}
    mock_client.get_positions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        once=True,
        risk_enabled=False,
        initial_cash=100000.0,
        order_sizing_buffer=1.0,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    close_price = float(sample_data["close"].iloc[-1])
    pnl_equity = config.initial_cash
    expected_qty = round(0.5 * pnl_equity / close_price, config.asset_precision)
    assert exe._pnl.position == pytest.approx(expected_qty, abs=1e-8)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_live_mode_does_not_cap_equity(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """LIVE mode does NOT cap equity at initial_cash when wallet exceeds it."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_live"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "200000.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "200000.0",
                        "walletBalance": "200000.0",
                        "availableBalance": "200000.0",
                        "unrealisedPnl": "100000.0",
                    }
                ],
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.LIVE,
        dry_run=False,
        once=True,
        risk_enabled=False,
        initial_cash=100000.0,
        order_sizing_buffer=1.0,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    close_price = float(sample_data["close"].iloc[-1])
    live_equity = 200000.0
    expected_qty = round(0.5 * live_equity / close_price, config.asset_precision)
    assert exe._pnl.position == pytest.approx(expected_qty, abs=1e-8)
    capped_qty = round(0.5 * config.initial_cash / close_price, config.asset_precision)
    assert exe._pnl.position > capped_qty + 1e-12


# ---------------------------------------------------------------------------
# Finding 3: order_sizing_buffer boundary tests
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
def test_order_sizing_buffer_zero(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Buffer=0.0 results in zero position (scales equity to zero)."""
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, order_sizing_buffer=0.0)
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    result = exe.step(sample_data)
    assert result["signal"] == 0.5
    assert result["target_position"] == 0.0


@patch("ztb.execution.executor.load_data")
def test_order_sizing_buffer_one(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Buffer=1.0 uses full equity for position sizing."""
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, order_sizing_buffer=1.0)
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    result = exe.step(sample_data)
    close_price = float(sample_data["close"].iloc[-1])
    expected_qty = round(0.5 * config.initial_cash / close_price, config.asset_precision)
    assert result["target_position"] == pytest.approx(expected_qty)


@patch("ztb.execution.executor.load_data")
def test_order_sizing_buffer_above_one(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Buffer>1.0 scales equity above initial_cash for position sizing."""
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, order_sizing_buffer=1.5)
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    result = exe.step(sample_data)
    close_price = float(sample_data["close"].iloc[-1])
    expected_qty = round(0.5 * config.initial_cash * 1.5 / close_price, config.asset_precision)
    assert result["target_position"] == pytest.approx(expected_qty)
    no_cap = round(0.5 * config.initial_cash / close_price, config.asset_precision)
    assert result["target_position"] > no_cap


# ---------------------------------------------------------------------------
# Finding 4: total_available_balance distinction test
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_total_available_balance_caps_notional(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """max_notional uses total_available_balance, not available_balance."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_cap"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "10000.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "100000.0",
                        "walletBalance": "100000.0",
                        "availableBalance": "4000.0",
                        "unrealisedPnl": "0.0",
                    }
                ],
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        once=True,
        risk_enabled=False,
        initial_cash=100000.0,
        order_sizing_buffer=1.0,
        max_leverage=3.0,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config, client=mock_client)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"
    close_price = float(sample_data["close"].iloc[-1])
    total_available = 10000.0
    max_notional = total_available * config.max_leverage
    max_qty = round(max_notional / close_price, config.asset_precision)
    assert exe._pnl.position == pytest.approx(max_qty)
    assert exe._pnl.position > round(
        4000.0 * config.max_leverage / close_price, config.asset_precision
    )
