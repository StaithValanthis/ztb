from __future__ import annotations

import os

from ztb.execution.errors import ExecutionError


class LiveDisarmedError(ExecutionError):
    def __init__(self) -> None:
        super().__init__("Live trading disarmed — set ZTB_LIVE_ARMED=1 to arm")


class LiveGuard:
    ENV_VAR = "ZTB_LIVE_ARMED"

    @classmethod
    def is_armed(cls) -> bool:
        val = os.environ.get(cls.ENV_VAR, "0")
        return val in ("1", "true", "yes")

    @classmethod
    def assert_live_allowed(cls) -> None:
        if not cls.is_armed():
            raise LiveDisarmedError()

    @classmethod
    def arm(cls, token: str = "1") -> None:
        os.environ[cls.ENV_VAR] = token

    @classmethod
    def disarm(cls) -> None:
        os.environ[cls.ENV_VAR] = "0"
