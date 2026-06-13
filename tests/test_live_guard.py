from __future__ import annotations

import os
from pathlib import Path

import pytest

from ztb.execution.arm_auth import compute_arm_hash, load_arm_hash, verify_board_token
from ztb.execution.errors import LiveArmFailedError, LiveDisarmedError
from ztb.execution.live_guard import LiveGuard


def test_default_disarmed() -> None:
    os.environ.pop(LiveGuard.ENV_VAR, None)
    assert not LiveGuard.is_armed()


def test_arm() -> None:
    LiveGuard.arm("1")
    assert LiveGuard.is_armed()


def test_disarm() -> None:
    LiveGuard.arm("1")
    LiveGuard.disarm()
    assert not LiveGuard.is_armed()


def test_assert_live_allowed_when_armed() -> None:
    LiveGuard.arm("1")
    LiveGuard.assert_live_allowed()


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
    token = "board-token-valid"
    os.environ[LiveGuard.BOARD_TOKEN_VAR] = token
    hash_path = tmp_path / "board-arm-hash"
    hash_path.write_text(compute_arm_hash(token))
    result = LiveGuard.arm(store_path=hash_path)
    assert result["token_verified"]
    assert LiveGuard.is_armed()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)


def test_arm_without_board_token() -> None:
    LiveGuard.disarm()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)
    result = LiveGuard.arm("1")
    assert not result.get("token_verified", False)


def test_arm_with_invalid_board_token(tmp_path: Path) -> None:
    LiveGuard.disarm()
    os.environ[LiveGuard.BOARD_TOKEN_VAR] = "wrong-token"
    hash_path = tmp_path / "board-arm-hash"
    hash_path.write_text(compute_arm_hash("expected-token"))
    with pytest.raises(LiveArmFailedError, match="Board token verification failed"):
        LiveGuard.arm(store_path=hash_path)
    assert not LiveGuard.is_armed()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)
