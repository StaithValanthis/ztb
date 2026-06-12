from __future__ import annotations

import os

from ztb.execution.errors import LiveDisarmedError


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
    def arm(cls, token: str = "1", conn=None) -> None:
        if conn is not None:
            from ztb.store.exec_io import get_latest_unresolved_kill_event

            event = get_latest_unresolved_kill_event(conn)
            if event is not None:
                raise LiveDisarmedError("Cannot arm: unresolved kill event exists")
        os.environ[cls.ENV_VAR] = token

    @classmethod
    def disarm(cls) -> None:
        os.environ[cls.ENV_VAR] = "0"
