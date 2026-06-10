from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from ztb.execution.executor import ExecRunConfig, Executor
from ztb.execution.models import Mode


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

    with pytest.raises(Exception, match="Live mode is blocked"):
        BybitClient(ClientConfig(mode=Mode.LIVE))


@patch("ztb.execution.executor.load_data")
def test_executor_signal_to_qty_conversion(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, once=True)
    exe = Executor(signal_strat, config=config)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.current_position == 1.0
    assert result.avg_entry_price == 50000.0


@patch("ztb.execution.executor.load_data")
def test_executor_reconcile_called_after_placement(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    signal_strat = SignalStrategy()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, once=True)

    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}

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
