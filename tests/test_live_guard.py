from __future__ import annotations

import os
from pathlib import Path

import pytest

from ztb.execution.arm_auth import compute_arm_hash, load_arm_hash, verify_board_token
from ztb.execution.errors import LiveArmFailedError, LiveDisarmedError
from ztb.execution.live_guard import LiveGuard

_TEST_TOKEN = "brd-tkn"


def _setup_arm(tmp_path: Path) -> Path:
    """Set up board token + hash file, return hash path."""
    os.environ[LiveGuard.BOARD_TOKEN_VAR] = _TEST_TOKEN
    hash_path = tmp_path / "board-arm-hash"
    hash_path.write_text(compute_arm_hash(_TEST_TOKEN))
    return hash_path


def _cleanup_arm() -> None:
    LiveGuard.disarm()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)


def test_default_disarmed() -> None:
    os.environ.pop(LiveGuard.ENV_VAR, None)
    assert not LiveGuard.is_armed()


def test_arm(tmp_path: Path) -> None:
    sp = _setup_arm(tmp_path)
    LiveGuard.arm("1", hash_path=sp)
    assert LiveGuard.is_armed()
    _cleanup_arm()


def test_disarm(tmp_path: Path) -> None:
    sp = _setup_arm(tmp_path)
    LiveGuard.arm("1", hash_path=sp)
    LiveGuard.disarm()
    assert not LiveGuard.is_armed()
    _cleanup_arm()


def test_assert_live_allowed_when_armed(tmp_path: Path) -> None:
    sp = _setup_arm(tmp_path)
    LiveGuard.arm("1", hash_path=sp)
    LiveGuard.assert_live_allowed()
    _cleanup_arm()


def test_assert_live_allowed_when_disarmed() -> None:
    LiveGuard.disarm()
    with pytest.raises(LiveDisarmedError):
        LiveGuard.assert_live_allowed()


def test_env_var_values() -> None:
    for val in ("1", "true", "yes"):
        os.environ[LiveGuard.ENV_VAR] = val
        assert LiveGuard.is_armed()
    for val in ("0", "false", "no", ""):
        os.environ[LiveGuard.ENV_VAR] = val
        assert not LiveGuard.is_armed()


def test_missing_env_var() -> None:
    os.environ.pop(LiveGuard.ENV_VAR, None)
    assert not LiveGuard.is_armed()


def test_compute_arm_hash_deterministic() -> None:
    h1 = compute_arm_hash("board-token-123")
    h2 = compute_arm_hash("board-token-123")
    assert h1 == h2
    assert len(h1) == 64


def test_compute_arm_hash_different_tokens() -> None:
    h1 = compute_arm_hash("token-a")
    h2 = compute_arm_hash("token-b")
    assert h1 != h2


def test_verify_board_token_valid(tmp_path: Path) -> None:
    token = "correct-token"
    hash_path = tmp_path / "board-arm-hash"
    hash_path.write_text(compute_arm_hash(token))
    stored = load_arm_hash(hash_path)
    assert verify_board_token(token, stored)


def test_verify_board_token_invalid(tmp_path: Path) -> None:
    token = "wrong-token"
    hash_path = tmp_path / "board-arm-hash"
    hash_path.write_text(compute_arm_hash("original-token"))
    stored = load_arm_hash(hash_path)
    assert not verify_board_token(token, stored)


def test_verify_board_token_no_hash() -> None:
    assert not verify_board_token("any-token", None)
    assert not verify_board_token("any-token", "")


def test_load_arm_hash_custom_path(tmp_path: Path) -> None:
    p = tmp_path / "custom-hash"
    p.write_text("abc123")
    result = load_arm_hash(p)
    assert result == "abc123"


def test_load_arm_hash_nonexistent(tmp_path: Path) -> None:
    result = load_arm_hash(tmp_path / "nonexistent")
    assert result is None


def test_load_arm_hash_strips_whitespace(tmp_path: Path) -> None:
    p = tmp_path / "hash"
    p.write_text("  abc123  \n")
    result = load_arm_hash(p)
    assert result == "abc123"


def test_arm_with_valid_board_token(tmp_path: Path) -> None:
    LiveGuard.disarm()
    sp = _setup_arm(tmp_path)
    result = LiveGuard.arm(hash_path=sp)
    assert result["token_verified"]
    assert LiveGuard.is_armed()
    _cleanup_arm()


def test_arm_without_board_token_raises(tmp_path: Path) -> None:
    LiveGuard.disarm()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)
    with pytest.raises(LiveArmFailedError, match="Board token verification failed"):
        LiveGuard.arm("1")


def test_arm_with_missing_hash_file(tmp_path: Path) -> None:
    LiveGuard.disarm()
    os.environ[LiveGuard.BOARD_TOKEN_VAR] = _TEST_TOKEN
    with pytest.raises(LiveArmFailedError, match="Board token verification failed"):
        LiveGuard.arm(hash_path=tmp_path / "nonexistent-hash")
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)


def test_arm_with_invalid_board_token(tmp_path: Path) -> None:
    LiveGuard.disarm()
    os.environ[LiveGuard.BOARD_TOKEN_VAR] = "wrong-token"
    hash_path = tmp_path / "board-arm-hash"
    hash_path.write_text(compute_arm_hash("expected-token"))
    with pytest.raises(LiveArmFailedError, match="Board token verification failed"):
        LiveGuard.arm(hash_path=hash_path)
    assert not LiveGuard.is_armed()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)


def test_arm_fail_closed_on_unresolved_kill_via_path(tmp_path: Path) -> None:
    from ztb.store.exec_io import (
        create_exec_run,
        ensure_exec_tables,
        save_kill_event,
    )
    from ztb.store.results import connect

    db_path = tmp_path / "test_fail_closed.db"
    conn = connect(str(db_path))
    ensure_exec_tables(conn)
    create_exec_run(conn, "exec_kill1", "run_k1", "s", "BTCUSDT", "60")
    save_kill_event(
        conn,
        {
            "exec_run_id": "exec_kill1",
            "source": "account_dd",
            "reason": "Drawdown exceeded",
            "value": 0.15,
            "threshold": 0.1,
            "timestamp": "2026-01-01T00:00:00Z",
        },
    )
    conn.close()
    sp = _setup_arm(tmp_path)
    LiveGuard.disarm()
    with pytest.raises(LiveDisarmedError, match="Cannot arm: unresolved kill event exists"):
        LiveGuard.arm(store_path=db_path, hash_path=sp)
    assert not LiveGuard.is_armed()
    _cleanup_arm()


def test_arm_succeeds_on_clean_store_via_path(tmp_path: Path) -> None:
    from ztb.store.exec_io import ensure_exec_tables
    from ztb.store.results import connect

    db_path = tmp_path / "test_clean.db"
    conn = connect(str(db_path))
    ensure_exec_tables(conn)
    conn.close()
    sp = _setup_arm(tmp_path)
    LiveGuard.disarm()
    result = LiveGuard.arm(store_path=db_path, hash_path=sp)
    assert LiveGuard.is_armed()
    assert result["token_verified"]
    LiveGuard.disarm()
    _cleanup_arm()


def test_arm_fail_closed_via_default_store_path(tmp_path: Path) -> None:
    from ztb.store.exec_io import (
        create_exec_run,
        ensure_exec_tables,
        save_kill_event,
    )
    from ztb.store.results import connect

    db_path = tmp_path / "test_default_fc.db"
    conn = connect(str(db_path))
    ensure_exec_tables(conn)
    create_exec_run(conn, "exec_kill2", "run_k2", "s", "BTCUSDT", "60")
    save_kill_event(
        conn,
        {
            "exec_run_id": "exec_kill2",
            "source": "account_dd",
            "reason": "Drawdown exceeded",
            "value": 0.15,
            "threshold": 0.1,
            "timestamp": "2026-01-01T00:00:00Z",
        },
    )
    conn.close()
    sp = _setup_arm(tmp_path)
    LiveGuard.disarm()
    LiveGuard.set_default_store_path(db_path)
    with pytest.raises(LiveDisarmedError, match="Cannot arm: unresolved kill event exists"):
        LiveGuard.arm(hash_path=sp)
    assert not LiveGuard.is_armed()
    LiveGuard.set_default_store_path(None)
    _cleanup_arm()


def test_arm_succeeds_on_clean_store_via_default_path(tmp_path: Path) -> None:
    from ztb.store.exec_io import ensure_exec_tables
    from ztb.store.results import connect

    db_path = tmp_path / "test_clean_default.db"
    conn = connect(str(db_path))
    ensure_exec_tables(conn)
    conn.close()
    sp = _setup_arm(tmp_path)
    LiveGuard.disarm()
    LiveGuard.set_default_store_path(db_path)
    result = LiveGuard.arm(hash_path=sp)
    assert LiveGuard.is_armed()
    assert result["token_verified"]
    LiveGuard.disarm()
    LiveGuard.set_default_store_path(None)
    _cleanup_arm()


def test_set_default_store_path_none_resets() -> None:
    LiveGuard.set_default_store_path("/tmp/some/path")
    assert LiveGuard._default_store_path == "/tmp/some/path"
    LiveGuard.set_default_store_path(None)
    assert LiveGuard._default_store_path is None
