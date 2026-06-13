from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from ztb.execution.errors import ExecutionError
from ztb.execution.executor import ExecRunConfig, Executor
from ztb.execution.models import AccountState, Mode
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


def test_executor_live_mode_allowed_when_armed() -> None:
    from ztb.execution.bybit_client import BybitClient, ClientConfig
    from ztb.execution.live_guard import LiveGuard

    LiveGuard.arm("1")
    client = BybitClient(ClientConfig(api_key="k", api_secret="s", mode=Mode.LIVE))
    assert client._base_url == "https://api.bybit.com"
    client.close()
    LiveGuard.disarm()


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
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
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
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
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
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
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
    assert exe.state.total_cost > 50000.0


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
def test_executor_config_loop_default(mock_load: MagicMock, fake_strategy: FakeStrategy, sample_data: pd.DataFrame) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    assert config.loop is False
    assert config.poll_interval_seconds == 60.0


@patch("ztb.execution.executor.load_data")
def test_executor_config_loop_enabled(mock_load: MagicMock, fake_strategy: FakeStrategy, sample_data: pd.DataFrame) -> None:
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
def test_ensure_warmup_sufficient(mock_load: MagicMock, fake_strategy: FakeStrategy, sample_data: pd.DataFrame) -> None:
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
        {"open": [50000.0] * 50, "high": [50100.0] * 50, "low": [49900.0] * 50, "close": [50000.0] * 50, "volume": [100.0] * 50},
        index=idx,
    )
    small_data.index.name = "timestamp"
    idx2 = pd.date_range("2025-12-20", periods=160, freq="h", tz="UTC")
    extended_data = pd.DataFrame(
        {"open": [50000.0] * 160, "high": [50100.0] * 160, "low": [49900.0] * 160, "close": [50000.0] * 160, "volume": [100.0] * 160},
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
        {"open": [50000.0] * 50, "high": [50100.0] * 50, "low": [49900.0] * 50, "close": [50000.0] * 50, "volume": [100.0] * 50},
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
def test_fetch_new_bars_no_new_data(mock_load: MagicMock, fake_strategy: FakeStrategy, sample_data: pd.DataFrame) -> None:
    mock_load.return_value = pd.DataFrame()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    result = exe._fetch_new_bars(sample_data, "BTCUSDT", "60", "linear")
    assert len(result) == len(sample_data)


@patch("ztb.execution.executor.load_data")
def test_fetch_new_bars_with_new_bar(mock_load: MagicMock, fake_strategy: FakeStrategy, sample_data: pd.DataFrame) -> None:
    last_ts = sample_data.index[-1]
    new_idx = pd.date_range(start=last_ts + pd.Timedelta(hours=1), periods=1, freq="h", tz="UTC")
    new_bar = pd.DataFrame(
        {"open": [50100.0], "high": [50200.0], "low": [50000.0], "close": [50150.0], "volume": [150.0]},
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
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01, risk_enabled=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    assert exe.risk_mgr is not None
    exe.risk_mgr.kill_switch.update(200000.0)
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

    original_step = exe.step

    call_count = 0

    def failing_step(data: pd.DataFrame) -> dict:
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise ValueError("poll error")
        return original_step(data)

    exe.step = failing_step
    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")
    assert any("Max polling errors" in e for e in exe.state.errors)
