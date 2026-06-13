from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from ztb.execution.arm_auth import load_arm_hash, verify_board_token
from ztb.execution.errors import LiveArmFailedError, LiveDisarmedError


class LiveGuard:
    ENV_VAR = "ZTB_LIVE_ARMED"
    BOARD_TOKEN_VAR = "ZTB_BOARD_TOKEN"

    @classmethod
    def is_armed(cls) -> bool:
        val = os.environ.get(cls.ENV_VAR, "0")
        return val in ("1", "true", "yes")

    @classmethod
    def assert_live_allowed(cls) -> None:
        if not cls.is_armed():
            raise LiveDisarmedError()

    @classmethod
    def arm(
        cls,
        token: str = "1",
        conn: sqlite3.Connection | None = None,
        store_path: str | Path | None = None,
    ) -> dict[str, Any]:
        if conn is not None:
            from ztb.store.exec_io import get_latest_unresolved_kill_event

            event = get_latest_unresolved_kill_event(conn)
            if event is not None:
                raise LiveDisarmedError("Cannot arm: unresolved kill event exists")
        board_token = os.environ.get(cls.BOARD_TOKEN_VAR)
        if board_token:
            stored_hash = load_arm_hash(store_path)
            if not verify_board_token(board_token, stored_hash):
                raise LiveArmFailedError("Board token verification failed")
        os.environ[cls.ENV_VAR] = token
        entry = {"token_verified": bool(board_token), "source": "LiveGuard.arm()"}
        cls._write_audit(store_path, entry)
        return entry

    @classmethod
    def disarm(cls) -> None:
        os.environ[cls.ENV_VAR] = "0"

    @classmethod
    def _write_audit(cls, store_path: str | Path | None, entry: dict[str, Any]) -> None:
        if not store_path:
            return
        from ztb.store.exec_io import ensure_audit_table, log_audit_event
        from ztb.store.results import connect

        try:
            conn = connect(str(store_path))
            ensure_audit_table(conn)
            log_audit_event(
                conn,
                event_type="arm",
                source=entry.get("source", "LiveGuard"),
                detail=f"Board token verified via {cls.BOARD_TOKEN_VAR}",
            )
            conn.close()
        except Exception:
            pass
