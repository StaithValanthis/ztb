from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ztb.store.results import connect as store_connect


@dataclass
class HealthReport:
    healthy: bool = False
    exec_run_id: str = ""
    mode: str = ""
    armed: bool = False
    tag: str = ""
    bars_processed: int = 0
    last_bar_ts: str = ""
    position: float = 0.0
    realized_pnl: float = 0.0
    status: str = ""
    store_connected: bool = False
    heartbeat_age_sec: float = 0.0
    killswitch_tripped: bool = False
    issues: list[str] = field(default_factory=list)
    checked_at: str = ""


def _get_current_tag() -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:20]
    except Exception:
        pass
    return "unknown"


def check_health(exec_run_id: str, store_path: str | None = None) -> HealthReport:
    report = HealthReport(
        exec_run_id=exec_run_id,
        checked_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        tag=_get_current_tag(),
    )

    try:
        conn = store_connect(store_path)
        report.store_connected = True

        from ztb.store.exec_io import ensure_exec_tables, get_exec_run

        ensure_exec_tables(conn)
        run_info = get_exec_run(conn, exec_run_id)
        if run_info is not None:
            report.mode = run_info.get("mode", "")
            report.bars_processed = int(run_info.get("bars_processed", 0))
            report.last_bar_ts = run_info.get("last_bar_ts", "")
            report.position = float(run_info.get("current_position", 0.0))
            report.realized_pnl = float(run_info.get("realized_pnl", 0.0))
            report.status = run_info.get("status", "")

            from ztb.store.exec_io import get_kill_events

            events = get_kill_events(conn, exec_run_id)
            report.killswitch_tripped = bool(events)
            if events:
                report.issues.append(f"Killswitch tripped: {events[-1].get('reason', '')}")
        else:
            report.issues.append(f"Execution run {exec_run_id} not found")

        conn.close()
    except Exception as exc:
        report.store_connected = False
        report.issues.append(f"Store error: {exc}")

    from ztb.execution.live_guard import LiveGuard

    report.armed = LiveGuard.is_armed()

    if not report.store_connected:
        report.issues.append("Store not connected")
    if report.issues:
        report.healthy = False
    else:
        report.healthy = True

    return report
