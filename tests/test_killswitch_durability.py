from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from ztb.execution.arm_auth import compute_arm_hash
from ztb.execution.errors import LiveDisarmedError
from ztb.execution.killswitch import LiveKillSwitch
from ztb.execution.live_guard import LiveGuard
from ztb.store.exec_io import (
    ensure_exec_tables,
    get_latest_unresolved_kill_event,
    load_killswitch_state,
    save_kill_event,
    save_killswitch_state,
)

_TEST_TOKEN = "brd-tkn-kd"


def _setup_board(tmp_path: Path) -> Path:
    os.environ[LiveGuard.BOARD_TOKEN_VAR] = _TEST_TOKEN
    hp = tmp_path / "board-arm-hash"
    hp.write_text(compute_arm_hash(_TEST_TOKEN))
    return hp


def _cleanup_board() -> None:
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    ensure_exec_tables(conn)
    return conn


def test_killswitch_persist_and_restore() -> None:
    conn = _make_conn()
    exec_run_id = "exec_test_001"

    ks1 = LiveKillSwitch(max_account_dd=0.1)
    ks1.check_account_dd(100.0)
    ks1.check_account_dd(80.0)
    assert ks1.is_tripped
    assert ks1._hwm_equity == 100.0

    persist = ks1.to_persistable_state()
    save_killswitch_state(
        conn, exec_run_id, persist["tripped"], persist["hwm_equity"], persist["last_heartbeat"]
    )

    ks2 = LiveKillSwitch(max_account_dd=0.1)
    state = load_killswitch_state(conn, exec_run_id)
    assert state is not None
    ks2.restore_from_state(state, current_equity=80.0)
    assert ks2.is_tripped
    assert ks2._hwm_equity == 100.0

    conn.close()


def test_killswitch_restore_hwm_not_lower() -> None:
    conn = _make_conn()
    exec_run_id = "exec_test_002"

    save_killswitch_state(conn, exec_run_id, True, 100.0, 0.0)

    ks = LiveKillSwitch(max_account_dd=0.1)
    state = load_killswitch_state(conn, exec_run_id)
    assert state is not None
    ks.restore_from_state(state, current_equity=80.0)
    assert ks._hwm_equity == 100.0

    conn.close()


def test_killswitch_restore_hwm_raised() -> None:
    conn = _make_conn()
    exec_run_id = "exec_test_003"

    save_killswitch_state(conn, exec_run_id, True, 100.0, 0.0)

    ks = LiveKillSwitch(max_account_dd=0.1)
    state = load_killswitch_state(conn, exec_run_id)
    assert state is not None
    ks.restore_from_state(state, current_equity=120.0)
    assert ks._hwm_equity == 120.0

    conn.close()


def test_arm_fail_closed_on_unresolved_trip(tmp_path: Path) -> None:
    conn = _make_conn()
    exec_run_id = "exec_test_004"

    save_kill_event(
        conn,
        {
            "exec_run_id": exec_run_id,
            "source": "account_dd",
            "reason": "Drawdown exceeded",
            "value": 0.15,
            "threshold": 0.1,
            "timestamp": "2025-01-01T00:00:00Z",
        },
    )

    assert get_latest_unresolved_kill_event(conn) is not None

    sp = _setup_board(tmp_path)
    with pytest.raises(LiveDisarmedError):
        LiveGuard.arm(token="1", conn=conn, store_path=sp)

    LiveGuard.disarm()
    conn.close()
    _cleanup_board()


def test_arm_succeeds_on_clean_store(tmp_path: Path) -> None:
    conn = _make_conn()

    assert get_latest_unresolved_kill_event(conn) is None

    sp = _setup_board(tmp_path)
    LiveGuard.arm(token="1", conn=conn, store_path=sp)
    assert os.environ.get(LiveGuard.ENV_VAR) == "1"

    LiveGuard.disarm()
    conn.close()
    _cleanup_board()
