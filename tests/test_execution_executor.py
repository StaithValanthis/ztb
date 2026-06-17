from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from ztb.execution.errors import ClientError, ExecutionError, PollingError
from ztb.execution.executor import ExecRunConfig, Executor
from ztb.execution.models import AccountState, Mode, Position, TopUpResult
from ztb.execution.reconcile import reconcile_account as _real_reconcile


@pytest.fixture(autouse=True)
def _no_poll_sleep() -> None:
    """Eliminate fill-polling sleep so tests complete instantly.

    The default poll_fill_max_attempts=15 with poll_fill_interval=2.0 makes
    every test that places an order wait ~30 seconds.  Patching the sleep
    inside the executor module keeps the full polling logic but removes only
    the wall-clock delay.
    """
    with patch("ztb.execution.executor.time_module.sleep"):
        yield


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
        start="2026-01-06T00:00:00Z",
        end="2026-01-08T12:00:00Z",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert result.bars_processed > 0


# =========================================================================
# Replay-on-restart cursor: 6-test suite (ZTB-2503 contract frozen)
# =========================================================================


@patch("ztb.execution.executor.load_data")
def test_replay_on_restart_skips_processed_bars(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """Prior run with last_bar_ts=bar_150 -> loop starts at bar_151, bars 0..150 skipped."""
    mock_load.return_value = sample_data
    cursor_ts = str(sample_data.index[150])

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    with patch("ztb.store.exec_io.get_last_bar_ts", return_value=cursor_ts):
        result = exe.run(
            symbol="BTCUSDT",
            timeframe="60",
            start="2026-01-06T00:00:00Z",
            end="2026-01-08T12:00:00Z",
            db_path=":memory:",
        )

    assert result.status == "completed"
    expected = len(sample_data) - 150 - 1
    assert result.bars_processed == expected, (
        f"Expected {expected} bars after cursor skip, got {result.bars_processed}"
    )


@patch("ztb.execution.executor.load_data")
def test_replay_on_restart_maintains_warmup(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Cursor at bar_150 (warmup=100) -> first processed bar has 100+ warmup bars."""
    mock_load.return_value = sample_data
    cursor_ts = str(sample_data.index[150])

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)

    original_step = exe.step
    first_data_len: int | None = None

    def tracking_step(data: pd.DataFrame) -> dict[str, Any]:
        nonlocal first_data_len
        if first_data_len is None:
            first_data_len = len(data)
        return original_step(data)

    exe.step = tracking_step

    with patch("ztb.store.exec_io.get_last_bar_ts", return_value=cursor_ts):
        result = exe.run(
            symbol="BTCUSDT",
            timeframe="60",
            start="2026-01-06T00:00:00Z",
            end="2026-01-08T12:00:00Z",
            db_path=":memory:",
        )

    assert result.status == "completed"
    assert first_data_len is not None, "step should have been called"
    assert first_data_len >= signal_strat.warmup, (
        f"First step data length {first_data_len} must >= warmup {signal_strat.warmup}"
    )
    assert first_data_len == 152, (
        f"First step should have 152 bars (cursor at 150 + 2), got {first_data_len}"
    )


@patch("ztb.execution.executor.load_data")
def test_replay_on_restart_no_prior_run(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """No prior run -> all bars processed (backward compat)."""
    mock_load.return_value = sample_data

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-06T00:00:00Z",
        end="2026-01-08T12:00:00Z",
        db_path=":memory:",
    )

    assert result.status == "completed"
    assert result.bars_processed == len(sample_data) - FakeStrategy.warmup
    assert result.last_bar_ts == str(sample_data.index[-1])


@patch("ztb.execution.executor.load_data")
def test_replay_on_restart_persists_cursor(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """After run(), SELECT last_bar_ts matches last processed bar."""
    mock_load.return_value = sample_data
    cursor_ts = str(sample_data.index[150])

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    with patch("ztb.store.exec_io.get_last_bar_ts", return_value=cursor_ts):
        result = exe.run(
            symbol="BTCUSDT",
            timeframe="60",
            start="2026-01-06T00:00:00Z",
            end="2026-01-08T12:00:00Z",
            db_path=":memory:",
        )

    assert result.status == "completed"
    assert result.last_bar_ts == str(sample_data.index[-1]), (
        f"last_bar_ts should be last bar {sample_data.index[-1]}, got {result.last_bar_ts}"
    )


@patch("ztb.execution.executor.load_data")
def test_replay_on_restart_invalid_cursor(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cursor timestamp not in data -> all bars processed, warning logged, no crash."""
    mock_load.return_value = sample_data
    invalid_ts = "2099-01-01T00:00:00+00:00"

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    with patch("ztb.store.exec_io.get_last_bar_ts", return_value=invalid_ts):
        result = exe.run(
            symbol="BTCUSDT",
            timeframe="60",
            start="2026-01-06T00:00:00Z",
            end="2026-01-08T12:00:00Z",
            db_path=":memory:",
        )

    assert result.status == "completed"
    assert result.bars_processed == len(sample_data) - FakeStrategy.warmup
    assert any("not in data" in rec.message for rec in caplog.records), (
        "Warning about missing cursor should be logged"
    )


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_replay_on_restart_polling_loop_continues(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """Cursor skip -> after historical loop, polling loop continues normally."""
    mock_load.return_value = sample_data
    cursor_ts = str(sample_data.index[150])

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        loop=True,
        poll_interval_seconds=0.01,
        loop_flush_interval=1,
    )
    exe = Executor(fake_strategy, config=config)

    mock_sleep.side_effect = [
        0.01,
        0.01,
        lambda: setattr(exe, "_sigterm_stop", True),
    ]

    with patch("ztb.store.exec_io.get_last_bar_ts", return_value=cursor_ts):
        result = exe.run(
            symbol="BTCUSDT",
            timeframe="60",
            start="2026-01-06T00:00:00Z",
            end="2026-01-08T12:00:00Z",
            db_path=":memory:",
        )

    assert result.status == "completed"
    assert result.bars_processed > 0
    expected_historical = len(sample_data) - 150 - 1
    assert result.bars_processed >= expected_historical, (
        f"bars_processed {result.bars_processed} < historical {expected_historical}"
    )
    assert result.bars_processed > 0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_loop_flushes_bars_processed(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        loop=True,
        poll_interval_seconds=0.01,
        loop_flush_interval=1,
    )
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")

    calls = iter([None, None, lambda: setattr(exe, "_sigterm_stop", True)])
    mock_sleep.side_effect = lambda _: next(calls)()

    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    from ztb.store.exec_io import get_exec_run

    run_info = get_exec_run(exe._store_conn, exe.state.exec_run_id)
    assert run_info is not None
    assert int(run_info.get("bars_processed", 0)) > 0
    assert int(run_info.get("bars_processed", 0)) == exe.state.bars_processed


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_loop_flush_interval_respected(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        loop=True,
        poll_interval_seconds=0.01,
        loop_flush_interval=5,
    )
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")

    iterations: list[None] = []

    def side_effect(_: object) -> None:
        iterations.append(None)
        if len(iterations) >= 6:
            exe._sigterm_stop = True

    mock_sleep.side_effect = side_effect

    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    from ztb.store.exec_io import get_exec_run

    run_info = get_exec_run(exe._store_conn, exe.state.exec_run_id)
    assert run_info is not None
    bp = int(run_info.get("bars_processed", 0))
    assert bp > 0
    assert bp <= exe.state.bars_processed
    assert bp % 5 == 0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_loop_flush_operational_error_suppressed(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        loop=True,
        poll_interval_seconds=0.01,
        loop_flush_interval=1,
    )
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")

    import sqlite3

    with patch("ztb.store.exec_io.update_exec_run_status") as mock_update:
        mock_update.side_effect = sqlite3.OperationalError("database is locked")

        calls = iter([None, None, lambda: setattr(exe, "_sigterm_stop", True)])
        mock_sleep.side_effect = lambda _: next(calls)()

        exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    assert exe.state.bars_processed > 0
    assert not any("Max polling errors" in e for e in exe.state.errors)


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
def test_ensure_warmup_end_bound(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    small_data = sample_data.iloc[:50]
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._ensure_warmup(small_data, 150, "BTCUSDT", "60", "linear", "2026-01-01")
    assert mock_load.call_count >= 1
    _name, kwargs = mock_load.call_args
    end_val = kwargs.get("end")
    assert end_val is not None, "end must not be None — should be bounded to current_start"
    assert "2026-01-01" in str(end_val), "end should be the original start date"


@patch("ztb.execution.executor.load_data")
def test_ensure_warmup_merge_preserves_original_data(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
) -> None:
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
    idx_ext = pd.date_range("2025-12-20", periods=160, freq="h", tz="UTC")
    extended = pd.DataFrame(
        {
            "open": [49000.0] * 160,
            "high": [49100.0] * 160,
            "low": [48900.0] * 160,
            "close": [49000.0] * 160,
            "volume": [100.0] * 160,
        },
        index=idx_ext,
    )
    extended.index.name = "timestamp"
    mock_load.return_value = extended
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    result = exe._ensure_warmup(small_data, 150, "BTCUSDT", "60", "linear", "2026-01-01")
    assert len(result) >= 150
    last_original_idx = small_data.index[-1]
    last_original_close = small_data["close"].iloc[-1]
    assert last_original_idx in result.index
    assert result.loc[last_original_idx, "close"] == last_original_close


@patch("ztb.execution.executor.load_data")
def test_ensure_warmup_merge_overlap(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
) -> None:
    overlap_ts = pd.Timestamp("2025-12-31 12:00", tz="UTC")
    idx = pd.date_range("2025-12-31 10:00", periods=5, freq="h", tz="UTC")
    small_data = pd.DataFrame(
        {
            "open": [50000.0] * 5,
            "high": [50100.0] * 5,
            "low": [49900.0] * 5,
            "close": [55555.0] * 5,
            "volume": [100.0] * 5,
        },
        index=idx,
    )
    small_data.index.name = "timestamp"
    idx_ext = pd.date_range("2025-12-20", periods=300, freq="h", tz="UTC")
    ext_close = [44444.0] * 300
    extended = pd.DataFrame(
        {
            "open": [49000.0] * 300,
            "high": [49100.0] * 300,
            "low": [48900.0] * 300,
            "close": ext_close,
            "volume": [100.0] * 300,
        },
        index=idx_ext,
    )
    extended.index.name = "timestamp"
    mock_load.return_value = extended
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    result = exe._ensure_warmup(small_data, 150, "BTCUSDT", "60", "linear", "2025-12-31T10:00:00Z")
    assert overlap_ts in result.index, "overlapping timestamp should exist in result"
    assert result.loc[overlap_ts, "close"] == 55555.0, (
        "original data should win on overlap (keep='last')"
    )


@patch("ztb.execution.executor.load_data")
def test_ensure_warmup_no_extra_fetch(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
) -> None:
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
    idx_ext = pd.date_range("2025-12-20", periods=200, freq="h", tz="UTC")
    extended = pd.DataFrame(
        {
            "open": [49000.0] * 200,
            "high": [49100.0] * 200,
            "low": [48900.0] * 200,
            "close": [49000.0] * 200,
            "volume": [100.0] * 200,
        },
        index=idx_ext,
    )
    extended.index.name = "timestamp"
    mock_load.return_value = extended
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    result = exe._ensure_warmup(small_data, 150, "BTCUSDT", "60", "linear", "2026-01-01")
    assert len(result) >= 150
    mock_load.reset_mock()
    result2 = exe._ensure_warmup(result, 150, "BTCUSDT", "60", "linear", "2026-01-01")
    assert len(result2) >= 150
    mock_load.assert_not_called()


@patch("ztb.execution.executor.load_data")
def test_executor_with_start_dry_run_completes_quickly(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
) -> None:
    import time

    small_idx = pd.date_range("2026-06-14", periods=50, freq="h", tz="UTC")
    small_data = pd.DataFrame(
        {
            "open": [50000.0] * 50,
            "high": [50100.0] * 50,
            "low": [49900.0] * 50,
            "close": [50000.0] * 50,
            "volume": [100.0] * 50,
        },
        index=small_idx,
    )
    small_data.index.name = "timestamp"
    ext_idx = pd.date_range("2026-06-01", periods=400, freq="h", tz="UTC")
    ext_data = pd.DataFrame(
        {
            "open": [50000.0] * 400,
            "high": [50100.0] * 400,
            "low": [49900.0] * 400,
            "close": [50000.0] * 400,
            "volume": [100.0] * 400,
        },
        index=ext_idx,
    )
    ext_data.index.name = "timestamp"
    mock_load.side_effect = [small_data, ext_data]
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        warmup_bars=10,
        lookback_bars=0,
    )
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    start_wall = time.monotonic()
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-06-14",
        end="2026-06-15",
        db_path=":memory:",
    )
    elapsed = time.monotonic() - start_wall
    assert result.status == "completed"
    assert result.bars_processed > 0
    assert elapsed < 10.0, f"Executor took {elapsed:.2f}s, expected <5s (no 3-minute hang)"


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
def test_fetch_new_bars_passes_end_param(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = pd.DataFrame()
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._fetch_new_bars(sample_data, "BTCUSDT", "60", "linear")
    _, kwargs = mock_load.call_args
    assert "end" in kwargs
    assert isinstance(kwargs["end"], str)
    assert kwargs["end"].endswith("Z")
    assert "no_cache" not in kwargs


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


@patch("ztb.store.exec_io.save_killswitch_state")
def test_check_killswitch_operational_error_suppressed(
    mock_save_ks: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """OperationalError from save_killswitch_state must NOT crash _check_killswitch()."""
    import sqlite3

    from ztb.execution.killswitch import LiveKillSwitch

    mock_save_ks.side_effect = sqlite3.OperationalError("database is locked")
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    ks = LiveKillSwitch()
    ks.manual_trip("test")
    exe = Executor(fake_strategy, config=config, killswitch=ks)
    exe._init_run()
    exe._init_store(":memory:")
    result = exe._check_killswitch()
    assert result is True
    assert ks.is_tripped is True


@patch("ztb.store.exec_io.save_killswitch_state")
@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_heartbeat_save_killswitch_operational_error_suppressed(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    mock_save_ks: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """OperationalError from save_killswitch_state in heartbeat persist must NOT crash the loop."""
    import sqlite3

    from ztb.execution.killswitch import LiveKillSwitch

    mock_save_ks.side_effect = sqlite3.OperationalError("database is locked")
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=False)
    ks = LiveKillSwitch(max_data_staleness_sec=1e12)
    exe = Executor(fake_strategy, config=config, killswitch=ks)
    exe.run(symbol="BTCUSDT")
    assert ks.is_tripped is False


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
def test_polling_catchup_processes_each_bar(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """3 new bars → 3 step() calls with correct chunk sizes."""
    last_ts = sample_data.index[-1]
    new_idx = pd.date_range(start=last_ts + pd.Timedelta(hours=1), periods=3, freq="h", tz="UTC")
    new_bars = pd.DataFrame(
        {
            "open": [50100.0, 50200.0, 50300.0],
            "high": [50200.0, 50300.0, 50400.0],
            "low": [50000.0, 50100.0, 50200.0],
            "close": [50150.0, 50250.0, 50350.0],
            "volume": [150.0, 200.0, 250.0],
        },
        index=new_idx,
    )
    new_bars.index.name = "timestamp"
    mock_load.side_effect = [sample_data, new_bars, pd.DataFrame()]

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01)
    from ztb.execution.killswitch import LiveKillSwitch

    ks = LiveKillSwitch()
    exe = Executor(fake_strategy, config=config, killswitch=ks)
    exe._init_run()
    exe._init_store(":memory:")

    step_data_lengths: list[int] = []
    step_close_vals: list[float] = []

    def tracking_step(data: pd.DataFrame) -> dict:
        step_data_lengths.append(len(data))
        step_close_vals.append(float(data["close"].iloc[-1]))
        if len(step_data_lengths) >= 4:
            ks.manual_trip("test")
        return {"bar_ts": str(data.index[-1])}

    exe.step = tracking_step  # type: ignore[assignment]
    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    # Round 1: no new bars → 1 step call with full sample_data
    # Round 2: 3 new bars → 3 step() calls inside the for loop
    # Round 3: killswitch check → break
    assert len(step_data_lengths) == 4
    assert step_data_lengths[0] == len(sample_data)
    assert step_data_lengths[1] == len(sample_data) + 1
    assert step_close_vals[1] == 50150.0
    assert step_data_lengths[2] == len(sample_data) + 2
    assert step_close_vals[2] == 50250.0
    assert step_data_lengths[3] == len(sample_data) + 3
    assert step_close_vals[3] == 50350.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_catchup_killswitch_breaks_early(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """Killswitch trip on bar 2 must break out of the catch-up loop."""
    last_ts = sample_data.index[-1]
    new_idx = pd.date_range(start=last_ts + pd.Timedelta(hours=1), periods=3, freq="h", tz="UTC")
    new_bars = pd.DataFrame(
        {
            "open": [50100.0, 50200.0, 50300.0],
            "high": [50200.0, 50300.0, 50400.0],
            "low": [50000.0, 50100.0, 50200.0],
            "close": [50150.0, 50250.0, 50350.0],
            "volume": [150.0, 200.0, 250.0],
        },
        index=new_idx,
    )
    new_bars.index.name = "timestamp"
    mock_load.side_effect = [sample_data, new_bars, pd.DataFrame()]

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01)
    from ztb.execution.killswitch import LiveKillSwitch

    ks = LiveKillSwitch()
    exe = Executor(fake_strategy, config=config, killswitch=ks)
    exe._init_run()
    exe._init_store(":memory:")

    step_data_lengths: list[int] = []

    def tracking_step(data: pd.DataFrame) -> dict:
        step_data_lengths.append(len(data))
        # Trip killswitch on bar 2 (3rd total step call, 1st is round 1 with no new bars)
        if len(step_data_lengths) == 3:
            ks.manual_trip("test")
            return {"bar_ts": str(data.index[-1]), "killswitch_tripped": True}
        return {"bar_ts": str(data.index[-1])}

    exe.step = tracking_step  # type: ignore[assignment]
    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    # Round 1: 1 step (sample_data)
    # Round 2 catch-up: 2 steps (bars 1 and 2, then break on bar 2)
    assert len(step_data_lengths) == 3
    assert step_data_lengths[0] == len(sample_data)
    assert step_data_lengths[1] == len(sample_data) + 1
    assert step_data_lengths[2] == len(sample_data) + 2  # bar 3 not processed


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_catchup_client_error_continues(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """ClientError on bar 2 must not skip bar 3 processing (step returns dict, not raises)."""
    last_ts = sample_data.index[-1]
    new_idx = pd.date_range(start=last_ts + pd.Timedelta(hours=1), periods=3, freq="h", tz="UTC")
    new_bars = pd.DataFrame(
        {
            "open": [50100.0, 50200.0, 50300.0],
            "high": [50200.0, 50300.0, 50400.0],
            "low": [50000.0, 50100.0, 50200.0],
            "close": [50150.0, 50250.0, 50350.0],
            "volume": [150.0, 200.0, 250.0],
        },
        index=new_idx,
    )
    new_bars.index.name = "timestamp"
    mock_load.side_effect = [sample_data, new_bars, pd.DataFrame()]

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01)
    from ztb.execution.killswitch import LiveKillSwitch

    ks = LiveKillSwitch()
    exe = Executor(fake_strategy, config=config, killswitch=ks)
    exe._init_run()
    exe._init_store(":memory:")

    step_data_lengths: list[int] = []
    step_call_idx = [0]

    def tracking_step(data: pd.DataFrame) -> dict:
        step_data_lengths.append(len(data))
        step_call_idx[0] += 1
        # Bar 2 (3rd total: round1 + bar1) returns client_error (step's internal contract)
        if step_call_idx[0] == 3:
            return {"bar_ts": str(data.index[-1]), "client_error": True}
        if step_call_idx[0] >= 4:
            ks.manual_trip("test")
        return {"bar_ts": str(data.index[-1])}

    exe.step = tracking_step  # type: ignore[assignment]
    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    # Round 1: 1 step (sample_data)
    # Round 2 catch-up: 3 steps (bar1, bar2 [client_error], bar3)
    assert len(step_data_lengths) == 4
    assert step_data_lengths[1] == len(sample_data) + 1  # bar 1
    assert step_data_lengths[2] == len(sample_data) + 2  # bar 2 (client_error, skipped)
    assert step_data_lengths[3] == len(sample_data) + 3  # bar 3 processed despite bar 2 error


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_catchup_zero_new_bars_normal_poll(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """No new bars → single step() call, normal path."""
    mock_load.side_effect = [sample_data, pd.DataFrame(), pd.DataFrame()]

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01)
    from ztb.execution.killswitch import LiveKillSwitch

    ks = LiveKillSwitch()
    exe = Executor(fake_strategy, config=config, killswitch=ks)
    exe._init_run()
    exe._init_store(":memory:")

    step_call_count = [0]

    def tracking_step(data: pd.DataFrame) -> dict:
        step_call_count[0] += 1
        ks.manual_trip("test")
        return {"bar_ts": str(data.index[-1])}

    exe.step = tracking_step  # type: ignore[assignment]
    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    assert step_call_count[0] == 1


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_catchup_one_new_bar_normal_path(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """1 new bar → single step() call via else branch."""
    last_ts = sample_data.index[-1]
    new_idx = pd.date_range(start=last_ts + pd.Timedelta(hours=1), periods=1, freq="h", tz="UTC")
    single_bar = pd.DataFrame(
        {
            "open": [50100.0],
            "high": [50200.0],
            "low": [50000.0],
            "close": [50150.0],
            "volume": [150.0],
        },
        index=new_idx,
    )
    single_bar.index.name = "timestamp"
    mock_load.side_effect = [sample_data, single_bar, pd.DataFrame()]

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, loop=True, poll_interval_seconds=0.01)
    from ztb.execution.killswitch import LiveKillSwitch

    ks = LiveKillSwitch()
    exe = Executor(fake_strategy, config=config, killswitch=ks)
    exe._init_run()
    exe._init_store(":memory:")

    step_call_count = [0]

    def tracking_step(data: pd.DataFrame) -> dict:
        step_call_count[0] += 1
        if step_call_count[0] >= 2:
            ks.manual_trip("test")
        return {"bar_ts": str(data.index[-1])}

    exe.step = tracking_step  # type: ignore[assignment]
    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    # 1 call for round 1 (no new bars), 1 call for round 2 (1 new bar)
    assert step_call_count[0] == 2


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_loop_operational_error_suppressed(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    """OperationalError from _save_error must NOT exit the loop."""
    import sqlite3

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

    original_save_error = exe._save_error

    def failing_save_error(error_type: str, message: str) -> None:
        original_save_error(error_type, message)
        raise sqlite3.OperationalError("database is locked")

    exe._save_error = failing_save_error  # type: ignore[assignment]

    with pytest.raises(PollingError, match=r"Polling loop error \(3/3\)"):
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
    mock_client.place_order.return_value = {
        "skipped": True,
        "reason": "No trade on startup reconcile",
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
                        "equity": "175000.0",
                        "walletBalance": "145000.0",
                        "unrealisedPnl": "30000.0",
                    }
                ]
            }
        ]
    }
    mock_client.place_order.return_value = {
        "skipped": True,
        "reason": "No trade on startup reconcile",
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
    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "1.0", "avgPrice": "50000.0"}
    ]
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
    assert result1["order_placed"] is False, (
        "No order needed: exchange already has 1.0 BTC, target is also 1.0"
    )
    assert result1["signal"] == 0.5

    mock_client.place_order.reset_mock()
    result2 = exe.step(sample_data)
    assert result2["order_placed"] is True
    assert result2["signal"] == 0.0
    mock_client.place_order.assert_called_once()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_before_delta_no_exchange_position(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Order is placed when exchange has zero position and signal is non-zero."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(SignalStrategy(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert result["signal"] == 0.5


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_before_delta_partial_position(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Delta accounts for existing exchange position after reconcile."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "0.3", "avgPrice": "49000.0"}
    ]
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(SignalStrategy(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert result["signal"] == 0.5
    assert result["current_position"] == 0.3
    assert abs(result["target_position"] - 1.0) < 1e-6


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_before_delta_same_position_no_order(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """No order when exchange position already matches target."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "1.0", "avgPrice": "50000.0"}
    ]
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    class HalfSignal:
        name = "half_strat"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            return pd.Series(0.5 * np.ones(len(data)), index=data.index)

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(HalfSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is False
    assert abs(result["delta"]) < 1e-12


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_before_delta_flip_to_zero(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Changing signal to 0.0 places reduce-only order based on exchange position."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "1.0", "avgPrice": "50000.0"}
    ]
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    class FlipToZero:
        name = "flip_zero"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            return pd.Series(np.zeros(len(data)), index=data.index)

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(FlipToZero(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert result["signal"] == 0.0
    assert abs(result["delta"] - (-1.0)) < 1e-6


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_before_delta_skip_in_dry_run(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Reconcile is skipped in dry_run mode — delta uses PnL position."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "1.0", "avgPrice": "50000.0"}
    ]
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, risk_enabled=False)
    exe = Executor(SignalStrategy(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["current_position"] == 0.0
    assert abs(result["target_position"] - 1.0) < 1e-6
    assert abs(result["delta"] - 1.0) < 1e-6
    mock_client.get_positions.assert_not_called()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_before_delta_signal_initialized_reset(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """_signal_initialized reset after adopt_state — first step with same signal places order."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)

    class SameSignal:
        name = "same_sig"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def __init__(self) -> None:
            self._call_count = 0

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            self._call_count += 1
            if self._call_count == 1:
                return pd.Series(np.ones(len(data)), index=data.index)
            return pd.Series(np.zeros(len(data)), index=data.index)

    exe = Executor(SameSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "2.0", "avgPrice": "50000.0"}
    ]
    result1 = exe.step(sample_data)
    assert result1["order_placed"] is False
    assert exe._signal_initialized is True

    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "2.0", "avgPrice": "50000.0"}
    ]
    mock_client.place_order.reset_mock()
    result2 = exe.step(sample_data)
    assert result2["order_placed"] is True
    assert result2["signal"] == 0.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_before_delta_error_does_not_block(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Exchange fetch error in reconcile does not prevent order placement."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_client.get_positions.side_effect = RuntimeError("Exchange unreachable")
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(SignalStrategy(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True


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
    assert exe._last_executed_signal == 0.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_order_failure_retries_next_bar(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """ClientError on place_order does NOT consume signal — next bar retries."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.side_effect = [
        ClientError("Insufficient balance"),
        {"orderId": "oid_retry"},
    ]
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    assert exe._last_executed_signal == 0.0

    # Step 1: place_order raises ClientError — signal NOT consumed
    result1 = exe.step(sample_data)
    assert result1.get("client_error") is True
    assert exe._last_executed_signal == 0.0

    # Step 2: same signal, _last_executed_signal still 0.0 → signal_changed=True → order placed
    mock_client.place_order.reset_mock()
    mock_client.place_order.return_value = {"orderId": "oid_retry"}
    result2 = exe.step(sample_data)
    assert result2.get("order_placed") is True
    assert exe._last_executed_signal == 0.5


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reduce_only_skip_does_not_consume_signal(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Reduce-only skip (exchange position=0) does NOT update _last_executed_signal."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.place_order.return_value = {"orderId": "oid_1"}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(SignalStrategy(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    # Step 1: enter position (signal 0.5)
    result1 = exe.step(sample_data)
    assert result1.get("order_placed") is True
    assert exe._last_executed_signal == 0.5

    # Step 2: exchange reports position=0, signal=0 (FakeStrategy) — reduce-only skip fires
    exe.strategy = FakeStrategy()  # signal 0 → close
    result2 = exe.step(sample_data)
    assert result2.get("order_skipped") is True
    assert "Reduce-only skipped" in result2.get("skip_reason", "")
    # Signal NOT consumed — _last_executed_signal still 0.5
    assert exe._last_executed_signal == 0.5


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_signal_change_no_delta_updates_state(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Signal changes but delta≈0 — elif signal_changed updates _last_executed_signal."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_positions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(FakeStrategy(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    # Pretend we had executed signal 0.5 (PnL position is already 0)
    exe._last_executed_signal = 0.5
    exe._signal_initialized = True

    # Step 1: signal 0.0 (FakeStrategy), PnL position=0 → delta≈0, signal changed
    # elif signal_changed: should fire
    result1 = exe.step(sample_data)
    assert result1.get("order_placed") is False
    assert exe._last_executed_signal == 0.0

    # Step 2: same signal — should NOT place order (unchanged)
    result2 = exe.step(sample_data)
    assert result2.get("order_placed") is False
    assert exe._last_executed_signal == 0.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_wallet_fetch_failure_does_not_consume_signal(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When wallet fetch fails, signal is NOT consumed — next bar retries."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.side_effect = Exception("Connection error")
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(SignalStrategy(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    assert exe._signal_initialized is False
    assert exe._last_executed_signal == 0.0

    result = exe.step(sample_data)

    assert result["wallet_fetch_failed"] is True
    assert exe._last_executed_signal == 0.0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_wallet_fetch_failure_then_same_signal_triggers_order(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """After wallet fetch failure (signal NOT consumed), same signal on next
    bar still sees signal_changed and places the order."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.side_effect = [
        Exception("Connection error"),
        {"list": []},
    ]
    mock_client.get_positions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(SignalStrategy(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    # Step 1: wallet fetch fails — signal NOT consumed (still 0.0)
    result1 = exe.step(sample_data)
    assert result1["wallet_fetch_failed"] is True
    assert exe._last_executed_signal == 0.0

    # Step 2: wallet succeeds, signal 0.5 — still sees signal_changed → places order
    mock_client.place_order.return_value = {"orderId": "oid_retry"}
    result2 = exe.step(sample_data)
    assert result2.get("wallet_fetch_failed") is not True
    assert result2["order_placed"] is True
    assert exe._last_executed_signal == 0.5


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_wallet_fetch_failure_then_different_signal_triggers_order(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """After wallet fetch failure, a different signal on the next bar triggers."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.side_effect = [
        Exception("Connection error"),
        {"list": []},
    ]
    mock_client.get_positions.return_value = []
    mock_bybit_cls.return_value = mock_client

    class FlipAfterFail:
        name = "flip_after_fail"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def __init__(self) -> None:
            self._call_count = 0

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            self._call_count += 1
            arr = np.zeros(len(data))
            if self._call_count == 1:
                arr[-1] = 0.5
            elif self._call_count >= 2:
                arr[-1] = 1.0
            return pd.Series(arr, index=data.index)

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    exe = Executor(FlipAfterFail(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    # Step 1: wallet fails, signal NOT consumed
    result1 = exe.step(sample_data)
    assert result1["wallet_fetch_failed"] is True
    assert exe._last_executed_signal == 0.0

    # Step 2: wallet works, signal 1.0 (changed) → places order
    mock_client.place_order.return_value = {"orderId": "oid_change"}
    result2 = exe.step(sample_data)
    assert result2.get("wallet_fetch_failed") is not True
    assert result2["order_placed"] is True
    assert exe._last_executed_signal == 1.0


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
    expected_equity = 100000.0 + (close_price - 30000.0) * 1.5
    assert exe._pnl.equity(close_price) == pytest.approx(expected_equity, abs=1.0)


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
    close_price = float(sample_data["close"].iloc[-1])
    expected_qty = round(0.5 * 95000.0 / close_price, config.asset_precision)
    assert exe._pnl.position == pytest.approx(expected_qty, abs=1e-8)


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
    """DEMO mode wallet fetch failure skips bar (no fallback to PnLCalculator)."""
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
    assert exe._pnl.position == 0.0


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
def test_reconcile_adoption_does_not_overwrite_initial_cash(
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
    expected_equity = 100.0 + (close_price - 30000.0) * 1.5
    assert exe._pnl.equity(close_price) == pytest.approx(expected_equity, abs=1.0)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_adoption_preserves_configured_cash(
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
    assert exe._pnl.snapshot.initial_cash == pytest.approx(42.0)


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
    mock_client.top_up_demo_account.return_value = TopUpResult(
        success=False,
        credited_amount=0.0,
        coin="USDT",
        requested_amount=100000.0,
        message="top-up failed",
    )
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
    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "2.0", "avgPrice": "50000.0"}
    ]
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
    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "-2.0", "avgPrice": "50000.0"}
    ]
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
# ZTB-1789: Reduce-only zero-position guard
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reduce_only_skipped_when_no_exchange_position_long(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """PnL position > 0, signal flat, exchange position = 0 → order skipped, PnL zeroed."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)

    class FlatFromLongSignal:
        name = "flat_from_long"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = 0.0
            return pd.Series(arr, index=data.index)

    exe = Executor(FlatFromLongSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._pnl.apply_fill(2.0, 50000.0)
    exe._sync_pnl_state()

    assert abs(exe._pnl.position - 2.0) < 1e-8

    result = exe.step(sample_data)
    assert result.get("order_skipped") is True
    assert "reduce-only" in result.get("skip_reason", "").lower()
    mock_client.place_order.assert_not_called()
    assert abs(exe._pnl.position) < 1e-8


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reduce_only_skipped_when_no_exchange_position_short(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """PnL position < 0, signal flat, exchange position = 0 → order skipped, PnL zeroed."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)

    class FlatFromShortSignal:
        name = "flat_from_short"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = 0.0
            return pd.Series(arr, index=data.index)

    exe = Executor(FlatFromShortSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._pnl.apply_fill(-2.0, 50000.0)
    exe._sync_pnl_state()

    assert abs(exe._pnl.position - (-2.0)) < 1e-8

    result = exe.step(sample_data)
    assert result.get("order_skipped") is True
    assert "reduce-only" in result.get("skip_reason", "").lower()
    mock_client.place_order.assert_not_called()
    assert abs(exe._pnl.position) < 1e-8


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reduce_only_proceeds_when_exchange_has_position_long(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """PnL long 2.0, exchange long 2.0 → reduce-only proceeds normally."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_long"}
    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "2.0", "avgPrice": "50000.0"}
    ]
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)

    class FlatSignal:
        name = "flat_signal"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = 0.0
            return pd.Series(arr, index=data.index)

    exe = Executor(FlatSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._pnl.apply_fill(2.0, 50000.0)
    exe._sync_pnl_state()

    result = exe.step(sample_data)
    assert result.get("order_skipped") is not True
    call_kwargs = mock_client.place_order.call_args.kwargs
    assert call_kwargs.get("reduce_only") is True


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reduce_only_proceeds_when_exchange_has_position_short(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """PnL short -2.0, exchange short -2.0 → reduce-only proceeds normally."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_short"}
    mock_client.get_positions.return_value = [
        {"symbol": "BTCUSDT", "size": "-2.0", "avgPrice": "50000.0"}
    ]
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)

    class FlatSignal:
        name = "flat_signal"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = 0.0
            return pd.Series(arr, index=data.index)

    exe = Executor(FlatSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._pnl.apply_fill(-2.0, 50000.0)
    exe._sync_pnl_state()

    result = exe.step(sample_data)
    assert result.get("order_skipped") is not True
    call_kwargs = mock_client.place_order.call_args.kwargs
    assert call_kwargs.get("reduce_only") is True


# ---------------------------------------------------------------------------
# ZTB-2683: Wallet balance fix — cap qty to coin-level available_balance
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

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False, max_leverage=1.0)
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
    assert capped_qty == 0.0005


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_balance_cap_skips_when_capped_qty_zero(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When available_balance*max_leverage rounds target qty to zero, no order is placed."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "0.00000004",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "0.001",
                        "walletBalance": "0.001",
                        "availableBalance": "0.00000004",
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
    assert result.get("order_placed") is False
    assert abs(result.get("delta", 0.0)) < 1e-12
    mock_client.place_order.assert_not_called()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_flip_sets_reduce_only_false_with_balance_cap(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Flip order has reduce_only=False; opening portion is capped by available balance."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_flip"}
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

    class FlipSignal:
        name = "flip_signal"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = -0.5
            return pd.Series(arr, index=data.index)

    exe = Executor(FlipSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._pnl.apply_fill(2.0, 50000.0)
    exe._sync_pnl_state()

    result = exe.step(sample_data)

    assert result["order_placed"] is True
    call_kwargs = mock_client.place_order.call_args.kwargs
    assert call_kwargs.get("reduce_only") is False
    assert call_kwargs["qty"] > 2.0


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
# ZTB-1658: 'ab not enough' fix — wallet fetch, available balance, backoff
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_wallet_fetch_failure_skips_bar(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Wallet fetch failure skips bar — order NOT placed."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.side_effect = ClientError(0, "wallet down")
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result.get("wallet_fetch_failed") is True
    assert result.get("order_placed") is False
    mock_client.place_order.assert_not_called()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_uta_fallback_when_available_balance_missing(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When Bybit omits coin-level availableBalance, fall back to totalAvailableBalance."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "300.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "1000.0",
                        "walletBalance": "1000.0",
                        "unrealisedPnl": "0.0",
                    }
                ],
            }
        ]
    }
    mock_client.place_order.return_value = {"orderId": "uta_fallback_oid"}
    mock_client.get_positions.return_value = []
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
    call_kwargs = mock_client.place_order.call_args.kwargs
    placed_qty = call_kwargs["qty"]
    close_price = float(sample_data["close"].iloc[-1])
    max_qty = round(0.5 * min(1000.0, 300.0 * 2.0) / close_price, config.asset_precision)
    assert placed_qty <= max_qty + 1e-12


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_sizes_against_available_balance(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """target_qty is capped by available_balance * max_leverage, not by initial_cash."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "500.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "200000.0",
                        "walletBalance": "200000.0",
                        "availableBalance": "500.0",
                    }
                ],
            }
        ]
    }
    mock_client.place_order.return_value = {"orderId": "test_oid"}
    mock_client.get_positions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO, dry_run=False, risk_enabled=False, max_leverage=3.0, initial_cash=100000.0
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    close_price = float(sample_data["close"].iloc[-1])
    max_qty = round(0.5 * min(100000.0, 500.0 * 3.0) / close_price, config.asset_precision)

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    placed_qty = mock_client.place_order.call_args[1]["qty"]
    assert placed_qty <= max_qty + 1e-12


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_ab_not_enough_backoff(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """'ab not enough' ClientError is caught, logged, and bar skipped without retry."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "100000.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "100000.0",
                        "walletBalance": "100000.0",
                        "availableBalance": "100000.0",
                    }
                ],
            }
        ]
    }
    mock_client.place_order.side_effect = ClientError(100, "ab not enough for new order")
    mock_client.get_positions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result.get("client_error") is True
    assert "ab not enough" in result.get("error", "")
    assert mock_client.place_order.call_count == 1


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_executor_instrument_bounds_enforced(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Instrument min/max bounds are enforced via _validate_qty in place_order."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "100000.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "100000.0",
                        "walletBalance": "100000.0",
                        "availableBalance": "100000.0",
                    }
                ],
            }
        ]
    }
    mock_client.place_order.return_value = {"skipped": True, "reason": "Qty below minOrderQty"}
    mock_client.get_positions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result.get("order_skipped") is True
    assert "Qty below minOrderQty" in result.get("skip_reason", "")


# ---------------------------------------------------------------------------
# ZTB-1792: Reduce-only warmup bug — flip detection
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reduce_only_false_when_flip_from_long_to_short(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When abs(delta) > abs(current_position) (long→short flip), reduce_only=False."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_flip"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)

    class FlipToShort:
        name = "flip_to_short"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = -1.0
            return pd.Series(arr, index=data.index)

    exe = Executor(FlipToShort(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._pnl.apply_fill(2.0, 50000.0)
    exe._sync_pnl_state()

    result = exe.step(sample_data)
    assert result["current_position"] > 0
    assert result["delta"] < 0
    assert abs(result["delta"]) > result["current_position"]

    call_kwargs = mock_client.place_order.call_args.kwargs
    assert call_kwargs.get("reduce_only") is False
    assert call_kwargs["qty"] > abs(result["current_position"])


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reduce_only_false_when_flip_from_short_to_long(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When abs(delta) > abs(current_position) (short→long flip), reduce_only=False."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_flip"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)

    class FlipToLong:
        name = "flip_to_long"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = 1.0
            return pd.Series(arr, index=data.index)

    exe = Executor(FlipToLong(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._pnl.apply_fill(-2.0, 50000.0)
    exe._sync_pnl_state()

    result = exe.step(sample_data)
    assert result["current_position"] < 0
    assert result["delta"] > 0
    assert abs(result["delta"]) > abs(result["current_position"])

    call_kwargs = mock_client.place_order.call_args.kwargs
    assert call_kwargs.get("reduce_only") is False
    assert call_kwargs["qty"] > abs(result["current_position"])


# ---------------------------------------------------------------------------
# ZTB-2072: exec_fills are persisted on every order path
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_synthetic_fill_saved_when_no_exchange_fills(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Synthetic fallback path saves an exec_fill record when exchange returns no fills."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid_syn"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO, dry_run=False, risk_enabled=False, poll_fill_max_attempts=1
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True

    from ztb.store.exec_io import get_exec_fills

    fills = get_exec_fills(exe._store_conn, exe._exec_run_id)
    assert len(fills) >= 1, "Expected at least one synthetic exec_fill"
    fill = fills[0]
    assert "synthetic" in fill["fill_id"]
    assert fill["order_link_id"] == result["order"]["order_link_id"]
    assert fill["qty"] > 0
    assert fill["price"] > 0


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_synthetic_fill_commission_matches_order(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Synthetic fill commission matches the configured commission rate."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid_c"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        risk_enabled=False,
        commission=0.002,
        poll_fill_max_attempts=1,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True

    from ztb.store.exec_io import get_exec_fills

    fills = get_exec_fills(exe._store_conn, exe._exec_run_id)
    assert len(fills) >= 1
    close_price = float(sample_data["close"].iloc[-1])
    placed_qty = mock_client.place_order.call_args[1]["qty"]
    expected_commission = placed_qty * close_price * 0.002
    assert fills[0]["commission"] == pytest.approx(expected_commission, abs=1e-8)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_real_fills_saved_when_exchange_returns_fills(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Real fills from exchange are saved to exec_fills table."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid_real"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = [
        {
            "execId": "real_fill_1",
            "orderId": "test_oid_real",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "execPrice": "50001.0",
            "execQty": "0.001",
            "execFee": "0.05",
            "execTime": "2026-01-01T00:00:00Z",
        }
    ]
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.LIVE, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True

    from ztb.store.exec_io import get_exec_fills

    fills = get_exec_fills(exe._store_conn, exe._exec_run_id)
    assert len(fills) >= 1
    fill = fills[0]
    assert fill["fill_id"] == "real_fill_1"
    assert fill["price"] == pytest.approx(50001.0)
    assert fill["qty"] == pytest.approx(0.001)
    assert abs(fill["commission"] - 0.05) < 1e-8


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_both_order_and_fill_persisted_together(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Both exec_order and exec_fill are persisted in the same step."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid_pair"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        risk_enabled=False,
        poll_fill_max_attempts=1,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe.step(sample_data)

    from ztb.store.exec_io import get_exec_fills, get_exec_orders

    orders = get_exec_orders(exe._store_conn, exe._exec_run_id)
    fills = get_exec_fills(exe._store_conn, exe._exec_run_id)

    assert len(orders) >= 1
    assert len(fills) >= 1
    assert fills[0]["order_link_id"] == orders[0]["order_link_id"]


# ---------------------------------------------------------------------------
# ZTB-2447: exec_fill polling loop
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_poll_fills_returns_fills_on_first_attempt(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """_poll_fills returns fills immediately when exchange has them on first call."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "poll_oid_ok"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = [
        {
            "execId": "fill_on_first",
            "orderId": "poll_oid_ok",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "execPrice": "50001.0",
            "execQty": "0.001",
            "execFee": "0.05",
            "execTime": "2026-01-01T00:00:01Z",
        }
    ]
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.LIVE, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert "real_fills" in result
    assert len(result["real_fills"]) == 1
    assert result["real_fills"][0]["fill_id"] == "fill_on_first"
    assert mock_client.get_executions.call_count == 1
    mock_client.get_executions.assert_called_with(symbol="BTCUSDT", order_id="poll_oid_ok")


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_poll_fills_retries_and_finds_fills_on_second_attempt(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """_poll_fills retries and finds fills on the second attempt."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "poll_oid_retry"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.side_effect = [
        [],
        [
            {
                "execId": "fill_on_retry",
                "orderId": "poll_oid_retry",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "execPrice": "50002.0",
                "execQty": "0.001",
                "execFee": "0.05",
                "execTime": "2026-01-01T00:00:02Z",
            }
        ],
    ]
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.LIVE,
        dry_run=False,
        risk_enabled=False,
        poll_fill_max_attempts=3,
        poll_fill_interval=0.01,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert "real_fills" in result
    assert len(result["real_fills"]) == 1
    assert result["real_fills"][0]["fill_id"] == "fill_on_retry"
    assert mock_client.get_executions.call_count == 2


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_poll_fills_exhausts_attempts_and_falls_back_to_synthetic(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """_poll_fills exhausts all attempts and falls back to synthetic fill."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "poll_oid_exhaust"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.LIVE,
        dry_run=False,
        risk_enabled=False,
        poll_fill_max_attempts=3,
        poll_fill_interval=0.01,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert "real_fills" not in result or len(result["real_fills"]) == 0
    assert mock_client.get_executions.call_count == 3

    from ztb.store.exec_io import get_exec_fills

    fills = get_exec_fills(exe._store_conn, exe._exec_run_id)
    assert len(fills) >= 1
    assert "synthetic" in fills[0]["fill_id"]


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_poll_fills_handles_api_error_and_retries(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """_poll_fills handles an API error (exception) and retries."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "poll_oid_err"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.side_effect = [
        Exception("API timeout"),
        [
            {
                "execId": "fill_after_error",
                "orderId": "poll_oid_err",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "execPrice": "50003.0",
                "execQty": "0.001",
                "execFee": "0.05",
                "execTime": "2026-01-01T00:00:03Z",
            }
        ],
    ]
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.LIVE,
        dry_run=False,
        risk_enabled=False,
        poll_fill_max_attempts=3,
        poll_fill_interval=0.01,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert "real_fills" in result
    assert len(result["real_fills"]) == 1
    assert result["real_fills"][0]["fill_id"] == "fill_after_error"
    assert mock_client.get_executions.call_count == 2
    mock_client.get_executions.assert_any_call(symbol="BTCUSDT", order_id="poll_oid_err")


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_poll_fills_config_defaults(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """ExecRunConfig has sensible defaults for fill polling."""
    config = ExecRunConfig()
    assert config.poll_fill_max_attempts == 15
    assert config.poll_fill_interval == 2.0


@patch("ztb.execution.executor.time_module.sleep")
@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_poll_fills_aborts_early_on_sigterm(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    mock_sleep: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """_poll_fills breaks out of the retry loop when _sigterm_stop is set."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "poll_sigterm_oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.LIVE,
        dry_run=False,
        risk_enabled=False,
        poll_fill_max_attempts=10,
        poll_fill_interval=0.01,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    calls = iter(
        [
            [],
            lambda: setattr(exe, "_sigterm_stop", True) or [],
        ]
    )
    mock_client.get_executions.side_effect = lambda *a, **kw: (
        v() if callable(v := next(calls)) else v
    )

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert exe._sigterm_stop is True
    assert mock_client.get_executions.call_count == 2


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_poll_fills_runs_in_demo_mode(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """DEMO mode polls get_executions for real fills (no synthetic short-circuit).

    Regression lock: demo must NOT skip fill polling (was the d797575 bug).
    """
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "demo_oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO, dry_run=False, risk_enabled=False, poll_fill_max_attempts=1
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert mock_client.get_executions.call_count >= 1


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_demo_mode_polls_then_synthetic_fallback(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """DEMO step() polls get_executions; synthetic fallback ONLY when no real fill returns."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "synth_oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = []
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO, dry_run=False, risk_enabled=False, poll_fill_max_attempts=1
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result["order_placed"] is True

    from ztb.store.exec_io import get_exec_fills

    fills = get_exec_fills(exe._store_conn, exe._exec_run_id)
    assert len(fills) >= 1
    assert "synthetic" in fills[0]["fill_id"]
    assert mock_client.get_executions.call_count >= 1


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_polling_loop_killswitch_checked_after_sleep(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Killswitch tripped during sleep is caught before _fetch_new_bars."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "ks_oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        loop=True,
        poll_interval_seconds=0.01,
        risk_enabled=False,
    )
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    exe._killswitch = MagicMock()
    exe._killswitch.is_tripped = False

    call_count = 0

    def trip_after_sleep(*args: Any, **kwargs: Any) -> bool:
        nonlocal call_count
        call_count += 1
        return call_count != 1

    exe._check_killswitch = trip_after_sleep  # type: ignore[assignment]

    exe._sigterm_stop = False
    exe._run_polling_loop(sample_data, "BTCUSDT", "1m", "spot")

    assert any("Killswitch tripped during sleep" in e for e in exe.state.errors)
    assert mock_client.get_executions.call_count == 0


# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_stale_pending_should_reconcile_via_order_history(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When try_claim fails and existing has no order_id, _reconcile_pending_order is called."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
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

    mock_client.get_order_history.return_value = [
        {"orderLinkId": order_link_id, "orderId": "reconciled_order_1"}
    ]

    exe._idempotency.try_claim(order_link_id)

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert result["order"]["restored"] is True
    assert result["order"]["order_id"] == "reconciled_order_1"
    mock_client.get_order_history.assert_called_once_with(symbol="BTCUSDT", limit=50)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_pending_order_found(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When reconcile finds order in history, idempotency is resolved to 'placed'."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
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

    mock_client.get_order_history.return_value = [
        {"orderLinkId": order_link_id, "orderId": "reconciled_order_1"}
    ]

    exe._idempotency.try_claim(order_link_id)

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert result["order"]["restored"] is True
    assert result["order"]["order_id"] == "reconciled_order_1"

    row = exe._idempotency.get(order_link_id)
    assert row is not None
    assert row["status"] == "placed"
    assert row["order_id"] == "reconciled_order_1"


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_pending_order_not_found(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When reconcile returns None, stale pending row is deleted and try_claim is retried."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "new_order_id"}
    mock_client.get_order_history.return_value = []
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = []
    mock_bybit_cls.return_value = mock_client

    from ztb.execution.idempotency import make_intent_hash, make_order_link_id

    signal_strat = SignalStrategy()
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        risk_enabled=False,
        poll_fill_max_attempts=1,
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

    mock_client.get_order_history.return_value = []
    exe._idempotency.try_claim(order_link_id)

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert result["order"] is not None
    assert result["order"]["order_id"] == "new_order_id"
    mock_client.place_order.assert_called_once()
    mock_client.get_order_history.assert_called_once_with(symbol="BTCUSDT", limit=50)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_pending_order_api_failure(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When get_order_history raises, the fallback deletes pending row and retries."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "new_order_id"}
    mock_client.get_order_history.side_effect = Exception("API timeout")
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = []
    mock_bybit_cls.return_value = mock_client

    from ztb.execution.idempotency import make_intent_hash, make_order_link_id

    signal_strat = SignalStrategy()
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        risk_enabled=False,
        poll_fill_max_attempts=1,
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

    exe._idempotency.try_claim(order_link_id)

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    mock_client.place_order.assert_called_once()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_stale_pending_fallback_does_not_break_crash_recovery(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Existing crash recovery (existing row WITH order_id) still works unchanged."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
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

    row = exe._idempotency.get(order_link_id)
    assert row is not None
    assert row["status"] == "placed"
    assert row["order_id"] == "existing_order_1"
    mock_client.get_order_history.assert_not_called()


# ---------------------------------------------------------------------------
# ZTB-2194: Fix duplicate OrderLinkedID on stale-pending retry
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_stale_pending_resolve_failed_nonce(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Stale pending row with empty order_id → resolve as 'failed' → nonced
    link_id → fresh try_claim succeeds → place_order with fresh link_id."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "fresh_order_id"}
    mock_client.get_order_history.return_value = []
    mock_client.get_open_orders.return_value = []
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = []
    mock_bybit_cls.return_value = mock_client

    from ztb.execution.idempotency import make_intent_hash, make_order_link_id

    signal_strat = SignalStrategy()
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        risk_enabled=False,
        poll_fill_max_attempts=1,
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

    exe._idempotency.try_claim(order_link_id)

    result = exe.step(sample_data)

    assert result["order_placed"] is True
    old_row = exe._idempotency.get(order_link_id)
    assert old_row is not None
    assert old_row["status"] == "failed", "Stale pending should be resolved as 'failed'"

    placed_link_id = result["order"]["order_link_id"]
    assert placed_link_id != order_link_id, "Fresh link_id must differ from stale one"

    placed_row = exe._idempotency.get(placed_link_id)
    assert placed_row is not None
    assert placed_row["status"] == "placed"
    assert placed_row["order_id"] == "fresh_order_id"

    mock_client.place_order.assert_called_once()
    mock_client.get_order_history.assert_called_once_with(symbol="BTCUSDT", limit=50)
    mock_client.get_open_orders.assert_called_once_with(symbol="BTCUSDT")


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_pending_order_open_orders_match(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Reconcile finds order in get_open_orders (not history)."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
    mock_client.get_order_history.return_value = []
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

    mock_client.get_open_orders.return_value = [
        {"orderLinkId": order_link_id, "orderId": "open_order_1"}
    ]

    exe._idempotency.try_claim(order_link_id)

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert result["order"]["restored"] is True
    assert result["order"]["order_id"] == "open_order_1"

    row = exe._idempotency.get(order_link_id)
    assert row is not None
    assert row["status"] == "placed"
    assert row["order_id"] == "open_order_1"

    mock_client.get_order_history.assert_called_once_with(symbol="BTCUSDT", limit=50)
    mock_client.get_open_orders.assert_called_once_with(symbol="BTCUSDT")


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_pending_order_both_endpoints(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Reconcile queries both endpoints; history match wins and open orders is NOT called."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "test_oid"}
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

    mock_client.get_order_history.return_value = [
        {"orderLinkId": order_link_id, "orderId": "history_order"}
    ]

    exe._idempotency.try_claim(order_link_id)

    result = exe.step(sample_data)
    assert result["order_placed"] is True
    assert result["order"]["restored"] is True
    assert result["order"]["order_id"] == "history_order"

    mock_client.get_order_history.assert_called_once_with(symbol="BTCUSDT", limit=50)
    mock_client.get_open_orders.assert_not_called()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_place_order_duplicate_reconcile_found(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Defensive catch: ClientError thrown → reconcile finds order → resolve + fill + advance."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.side_effect = ClientError(200, "OrderLinkedID is duplicate")
    mock_client.get_order_history.return_value = [
        {"orderLinkId": "placeholder", "orderId": "found_dup_order"}
    ]
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
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

    mock_client.get_order_history.return_value = [
        {"orderLinkId": order_link_id, "orderId": "found_dup_order"}
    ]

    bars_before = 0
    result = exe.step(sample_data)

    assert result["order_placed"] is True
    assert result["order"]["order_id"] == "found_dup_order"
    assert result["order"]["restored"] is True
    assert exe.state.bars_processed == bars_before + 1
    assert exe.state.last_bar_ts == str(sample_data.index[-1])

    row = exe._idempotency.get(order_link_id)
    assert row is not None
    assert row["status"] == "placed"
    assert row["order_id"] == "found_dup_order"

    mock_client.place_order.assert_called_once()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_place_order_duplicate_skip_bar_advances_state(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Defensive catch: ClientError → reconcile returns None → pending 'failed' → bar advanced."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.side_effect = ClientError(200, "OrderLinkedID is duplicate")
    mock_client.get_order_history.return_value = []
    mock_client.get_open_orders.return_value = []
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
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

    bars_before = 0
    exe.step(sample_data)

    assert exe.state.bars_processed == bars_before + 1
    assert exe.state.last_bar_ts == str(sample_data.index[-1])

    row = exe._idempotency.get(order_link_id)
    assert row is not None
    assert row["status"] == "failed", (
        "Pending entry must be resolved as 'failed' when order not found on exchange"
    )

    mock_client.place_order.assert_called_once()


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reconcile_query_failure_skip(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Reconcile query raises Exception → treated as not-found → bar skipped gracefully."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "graceful_order"}
    mock_client.get_order_history.side_effect = Exception("API timeout")
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_client.get_executions.return_value = []
    mock_bybit_cls.return_value = mock_client

    from ztb.execution.idempotency import make_intent_hash, make_order_link_id

    signal_strat = SignalStrategy()
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=False,
        risk_enabled=False,
        poll_fill_max_attempts=1,
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

    exe._idempotency.try_claim(order_link_id)

    result = exe.step(sample_data)

    assert result["order_placed"] is True

    old_row = exe._idempotency.get(order_link_id)
    assert old_row is not None
    assert old_row["status"] == "failed", "Stale pending should be resolved as 'failed'"

    mock_client.place_order.assert_called_once()
    mock_client.get_order_history.assert_called_once_with(symbol="BTCUSDT", limit=50)


class WarmupSignalStrategy:
    name = "warmup_signal"
    symbols = ["BTCUSDT"]
    timeframe = "60"
    params: dict = {}
    warmup = 20

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        arr = np.zeros(len(data))
        arr[: self.warmup] = 0.0
        arr[self.warmup :] = 1.0
        return pd.Series(arr, index=data.index)


def test_executor_compute_target_with_start_data() -> None:
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    strat = WarmupSignalStrategy()
    exe = Executor(strat, config=config)
    idx = pd.date_range("2026-01-01", periods=30, freq="h", tz="UTC")
    data = pd.DataFrame(
        {
            "close": [50000.0 + i * 10 for i in range(30)],
            "open": [50000.0] * 30,
            "high": [50100.0] * 30,
            "low": [49900.0] * 30,
            "volume": [100.0] * 30,
        },
        index=idx,
    )
    target = exe._compute_target_position(data)
    assert target == 1.0


@patch("ztb.execution.executor.load_data")
def test_executor_with_start_dry_run_has_orders(
    mock_load: MagicMock,
) -> None:
    idx = pd.date_range("2026-01-06", periods=60, freq="h", tz="UTC")
    data = pd.DataFrame(
        {
            "open": [50000.0 + i * 5 for i in range(60)],
            "high": [50100.0 + i * 5 for i in range(60)],
            "low": [49900.0 + i * 5 for i in range(60)],
            "close": [50000.0 + i * 5 for i in range(60)],
            "volume": [100.0] * 60,
        },
        index=idx,
    )
    data.index.name = "timestamp"
    mock_load.return_value = data
    strat = WarmupSignalStrategy()
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        lookback_bars=30,
        warmup_bars=0,
    )
    exe = Executor(strat, config=config)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-06T00:00:00Z",
        end="2026-01-08T12:00:00Z",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert result.bars_processed > 0
    assert result.current_position > 0


@patch("ztb.execution.executor.load_data")
def test_executor_with_start_risk_decisions_produced(
    mock_load: MagicMock,
) -> None:
    idx = pd.date_range("2026-01-06", periods=60, freq="h", tz="UTC")
    data = pd.DataFrame(
        {
            "open": [50000.0 + i * 5 for i in range(60)],
            "high": [50100.0 + i * 5 for i in range(60)],
            "low": [49900.0 + i * 5 for i in range(60)],
            "close": [50000.0 + i * 5 for i in range(60)],
            "volume": [100.0] * 60,
        },
        index=idx,
    )
    data.index.name = "timestamp"
    mock_load.return_value = data
    strat = WarmupSignalStrategy()
    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        risk_enabled=True,
        lookback_bars=30,
        warmup_bars=0,
    )
    exe = Executor(strat, config=config)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-06T00:00:00Z",
        end="2026-01-08T12:00:00Z",
        db_path=":memory:",
    )
    assert result.status == "completed"
    assert result.bars_processed > 0


# ---------------------------------------------------------------------------
# Area 2: Persist skip reasons to exec_errors (ZTB-2628)
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_reduce_only_skip_saves_exec_error(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)

    class FlatSignal:
        name = "flat_error_test"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = 0.0
            return pd.Series(arr, index=data.index)

    exe = Executor(FlatSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe._pnl.apply_fill(2.0, 50000.0)
    exe._sync_pnl_state()
    assert abs(exe._pnl.position - 2.0) < 1e-8

    result = exe.step(sample_data)
    assert result.get("order_skipped") is True

    rows = list(
        exe._store_conn.execute(
            "SELECT * FROM exec_errors WHERE error_type='OrderSkipped'"
        ).fetchall()
    )
    assert len(rows) >= 1
    assert "reduce-only" in rows[0]["message"].lower() or "Reduce-only" in rows[0]["message"]


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_balance_cap_caps_qty_on_flip(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Flip scenario: balance cap constrains qty without crashing."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"orderId": "oid_cap"}
    mock_client.get_positions.return_value = []
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "0.5",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "100.0",
                        "walletBalance": "100.0",
                        "availableBalance": "0.5",
                        "unrealisedPnl": "0.0",
                    }
                ],
            }
        ]
    }
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False, max_leverage=1.0)

    class HalfLongSignal:
        name = "half_long"
        symbols = ["BTCUSDT"]
        timeframe = "60"
        params: dict = {}
        warmup = 50

        def generate_signals(self, data: pd.DataFrame) -> pd.Series:
            arr = np.zeros(len(data))
            arr[-1] = 0.5
            return pd.Series(arr, index=data.index)

    exe = Executor(HalfLongSignal(), config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.state.current_position = 0.0

    result = exe.step(sample_data)
    assert isinstance(result, dict)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_validation_skip_saves_exec_error(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.place_order.return_value = {"skipped": True, "reason": "Qty too small"}
    mock_client.get_wallet_balance.return_value = {"list": []}
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client

    result = exe.step(sample_data)
    assert result.get("order_skipped") is True

    rows = list(
        exe._store_conn.execute(
            "SELECT * FROM exec_errors WHERE error_type='OrderSkipped'"
        ).fetchall()
    )
    assert len(rows) >= 1
    assert "Qty too small" in rows[0]["message"]


# ---------------------------------------------------------------------------
# Area 4: _apply_risk position % cap scaling (ZTB-2628)
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
def test_executor_apply_risk_position_pct_capped(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, risk_enabled=True)
    exe = Executor(SignalStrategy(), config=config)
    exe._init_run()
    assert exe.risk_mgr is not None
    exe.risk_mgr.config.max_leverage = 10.0
    exe.risk_mgr.config.max_position_pct = 0.50
    sig, decision = exe._apply_risk(1.0, 0.0, 100000.0, 100000.0, "2026-01-01T00:00:00Z")
    assert decision is not None
    assert decision.action.value == "reduce"
    assert sig == 0.5, f"Expected 0.5 (position % cap), got {sig}"


@patch("ztb.execution.executor.load_data")
def test_executor_apply_risk_leverage_still_works(
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = sample_data
    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, risk_enabled=True)
    exe = Executor(SignalStrategy(), config=config)
    exe._init_run()
    assert exe.risk_mgr is not None
    exe.risk_mgr.config.max_leverage = 2.0
    exe.risk_mgr.config.max_position_pct = 0.95
    sig, decision = exe._apply_risk(5.0, 0.0, 100000.0, 100000.0, "2026-01-01T00:00:00Z")
    assert decision is not None
    assert decision.action.value == "reduce"
    assert sig == 2.0, f"Expected 2.0 (leverage cap), got {sig}"


# =========================================================================
# _fetch_new_bars cursor advancement: 5-test suite (ZTB-2732 contract frozen)
# =========================================================================


@patch("ztb.execution.executor.load_data")
def test_fetch_new_bars_appends_new_data(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    new_idx = sample_data.index[-1] + pd.Timedelta(hours=1)
    new_bar = pd.DataFrame(
        {
            "open": [50100.0],
            "high": [50200.0],
            "low": [50000.0],
            "close": [50150.0],
            "volume": [120.0],
        },
        index=[new_idx],
    )
    new_bar.index.name = "timestamp"
    mock_load.return_value = new_bar

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")

    result = exe._fetch_new_bars(sample_data, "BTCUSDT", "60", "linear")

    assert len(result) == len(sample_data) + 1
    assert result.index[-1] == new_idx
    assert all(result.index[:200] == sample_data.index)


@patch("ztb.execution.executor.load_data")
def test_fetch_new_bars_preserves_existing_bars(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = None

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")

    result = exe._fetch_new_bars(sample_data, "BTCUSDT", "60", "linear")

    assert len(result) == len(sample_data)
    assert list(result.index) == list(sample_data.index)
    assert all(result["close"] == sample_data["close"])


@patch("ztb.execution.executor.load_data")
def test_fetch_new_bars_no_new_bar(
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    mock_load.return_value = None

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True)
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")

    result = exe._fetch_new_bars(sample_data, "BTCUSDT", "60", "linear")

    assert result is sample_data


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.time_module.sleep")
def test_polling_loop_advances_last_bar_ts(
    mock_sleep: MagicMock,
    mock_load: MagicMock,
    fake_strategy: FakeStrategy,
    sample_data: pd.DataFrame,
) -> None:
    new_idx = sample_data.index[-1] + pd.Timedelta(hours=1)
    extended_idx = list(sample_data.index) + [new_idx]
    extended_data = pd.DataFrame(
        {
            "open": [50000.0] * 201,
            "high": [50100.0] * 201,
            "low": [49900.0] * 201,
            "close": [50000.0] * 201,
            "volume": [100.0] * 201,
        },
        index=extended_idx,
    )
    extended_data.index.name = "timestamp"

    call_count = 0

    def load_side_effect(*args: object, **kwargs: object) -> pd.DataFrame:
        nonlocal call_count
        call_count += 1
        return extended_data

    mock_load.side_effect = load_side_effect

    config = ExecRunConfig(
        mode=Mode.DEMO,
        dry_run=True,
        loop=True,
        poll_interval_seconds=0.01,
    )
    exe = Executor(fake_strategy, config=config)
    exe._init_run()
    exe._init_store(":memory:")

    def stop_loop(_: object) -> None:
        exe._sigterm_stop = True

    mock_sleep.side_effect = stop_loop

    exe._run_polling_loop(sample_data, "BTCUSDT", "60", "linear")

    assert exe.state.last_bar_ts is not None
    assert str(sample_data.index[-1]) <= str(exe.state.last_bar_ts)


# ---------------------------------------------------------------------------
# Step-alignment tests (ZTB-3008)
# ---------------------------------------------------------------------------


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_step_alignment_ceils_target_qty_for_small_wallet_long(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Small wallet target_qty is ceiled to step to avoid flooring to zero."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "100.0",
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
    mock_client.place_order.return_value = {"orderId": "oid_ceiled"}
    mock_client.get_positions.return_value = []
    mock_client.get_qty_step.return_value = 0.001
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False, max_leverage=1.0)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.state.current_position = 0.0

    result = exe.step(sample_data)

    # target_qty = 0.5 * min(100000, 50*1) / 50000 = 0.5 * 50 / 50000 = 0.0005
    # ceil_to_step(0.0005, 0.001) -> 0.001
    assert result.get("order_placed") is True
    placed_qty = mock_client.place_order.call_args[1].get("qty", 0)
    assert placed_qty == pytest.approx(0.001)


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_step_alignment_fetch_failure_falls_back_gracefully(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When get_qty_step raises, executor falls back to asset_precision rounding."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "100000.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "100000.0",
                        "walletBalance": "100000.0",
                        "availableBalance": "100000.0",
                        "unrealisedPnl": "0.0",
                    }
                ],
            }
        ]
    }
    mock_client.place_order.return_value = {"orderId": "oid_fallback"}
    mock_client.get_positions.return_value = []
    mock_client.get_qty_step.side_effect = Exception("API error")
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False, max_leverage=1.0)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.state.current_position = 0.0

    result = exe.step(sample_data)
    assert result.get("order_placed") is True


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_step_alignment_does_not_affect_dry_run(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """Dry-run mode skips step alignment entirely."""
    mock_load.return_value = sample_data
    mock_bybit_cls.return_value = MagicMock()

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=True, risk_enabled=False)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    result = exe.run(
        symbol="BTCUSDT",
        timeframe="60",
        start="2026-01-01",
        end="2026-01-10",
        db_path=":memory:",
    )
    assert result.status == "completed"


@patch("ztb.execution.executor.load_data")
@patch("ztb.execution.executor.BybitClient")
def test_step_alignment_floors_capped_qty_to_zero_and_skips(
    mock_bybit_cls: MagicMock,
    mock_load: MagicMock,
    sample_data: pd.DataFrame,
) -> None:
    """When balance cap max_qty floors to zero after step-rounding, order is skipped."""
    mock_load.return_value = sample_data
    mock_client = MagicMock()
    mock_client.get_wallet_balance.return_value = {
        "list": [
            {
                "totalAvailableBalance": "30.0",
                "coin": [
                    {
                        "coin": "USDT",
                        "equity": "50.0",
                        "walletBalance": "50.0",
                        "availableBalance": "30.0",
                        "unrealisedPnl": "0.0",
                    }
                ],
            }
        ]
    }
    mock_client.place_order.return_value = {"orderId": "oid_cap"}
    mock_client.get_positions.return_value = []
    mock_client.get_qty_step.return_value = 0.001
    mock_bybit_cls.return_value = mock_client

    config = ExecRunConfig(mode=Mode.DEMO, dry_run=False, risk_enabled=False, max_leverage=1.0)
    signal_strat = SignalStrategy()
    exe = Executor(signal_strat, config=config)
    exe._init_run()
    exe._init_store(":memory:")
    exe.client = mock_client
    exe.state.current_position = 0.0

    result = exe.step(sample_data)

    # target_qty = 0.5 * min(100000, 30*1) / 50000 = 0.0003
    # ceil_to_step(0.0003, 0.001) -> 0.001
    # max_qty = floor_to_step(30/50000, 0.001) = 0.0
    # capped_qty = 0.0 -> skipped
    assert result.get("order_skipped") is True
