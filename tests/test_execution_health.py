from __future__ import annotations

import os
import tempfile

from ztb.execution.live_guard import LiveGuard
from ztb.reporting.health import HealthReport, check_health


def test_health_report_dataclass() -> None:
    r = HealthReport(exec_run_id="exec_test_001")
    assert r.exec_run_id == "exec_test_001"
    assert r.healthy is False
    assert r.issues == []
    assert r.checked_at == ""  # populated by check_health() only


def test_health_report_from_check_has_timestamp() -> None:
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        r = check_health("exec_test", store_path=db_path)
        assert r.checked_at != ""
    finally:
        os.unlink(db_path)


def test_check_health_nonexistent_run() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        report = check_health("exec_nonexistent", store_path=db_path)
        assert isinstance(report, HealthReport)
        assert report.exec_run_id == "exec_nonexistent"
    finally:
        os.unlink(db_path)


def test_check_health_armed_state() -> None:
    LiveGuard.disarm()
    report = check_health("exec_test")
    assert report.armed is False
    LiveGuard.arm("1")
    report_armed = check_health("exec_test")
    assert report_armed.armed is True
    LiveGuard.disarm()


def test_health_report_fields() -> None:
    r = check_health("exec_demo_run")
    assert hasattr(r, "healthy")
    assert hasattr(r, "store_connected")
    assert hasattr(r, "tag")
    assert hasattr(r, "issues")


def test_health_report_unhealthy_on_store_issue() -> None:
    r = check_health("exec_test", store_path="/nonexistent/path/db.sqlite")
    assert not r.healthy
    assert not r.store_connected


def test_health_issues_list_includes_unhealthy_store() -> None:
    r = check_health("exec_test_fail")
    if not r.store_connected:
        assert (
            any("Store" in i for i in r.issues)
            or any("store" in i.lower() for i in r.issues)
            or len(r.issues) > 0
        )
