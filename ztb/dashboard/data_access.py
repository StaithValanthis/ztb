from __future__ import annotations

from pathlib import Path
from typing import Any

from ztb.store.results import (
    connect,
    connect_live,
    get_equity_curve,
    get_metrics,
    get_risk_decisions,
    get_run,
    get_trades,
    list_forward_runs,
    list_runs,
)


class DashboardData:
    def __init__(
        self,
        db_path: str | Path | None = None,
        live_db_path: str | Path | None = None,
    ) -> None:
        self._conn = connect(db_path)
        self._live_conn = connect_live(live_db_path)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return list_runs(self._conn)[:limit]

    def list_forward_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return list_forward_runs(self._conn)[:limit]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return get_run(self._conn, run_id)

    def get_metrics(self, run_id: str) -> list[dict[str, Any]]:
        return get_metrics(self._conn, run_id)

    def get_trades(self, run_id: str) -> list[dict[str, Any]]:
        return get_trades(self._conn, run_id)

    def get_equity(self, run_id: str) -> list[dict[str, Any]]:
        return get_equity_curve(self._conn, run_id)

    def get_risk_decisions(self, run_id: str) -> list[dict[str, Any]]:
        return get_risk_decisions(self._conn, run_id)

    def list_exec_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        from ztb.store.exec_io import list_exec_runs as _list_exec_runs

        return _list_exec_runs(self._live_conn)[:limit]

    def get_exec_run(self, exec_run_id: str) -> dict[str, Any] | None:
        from ztb.store.exec_io import get_exec_run as _get_exec_run

        return _get_exec_run(self._live_conn, exec_run_id)
