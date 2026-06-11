from __future__ import annotations

import os

import pytest

from ztb.execution.live_guard import LiveDisarmedError, LiveGuard


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
