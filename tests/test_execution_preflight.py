from __future__ import annotations

from ztb.ops.preflight import PreflightReport, run_preflight


def test_run_preflight_basic() -> None:
    report = run_preflight()
    assert isinstance(report, PreflightReport)
    assert len(report.items) >= 4


def test_preflight_all_items_present() -> None:
    report = run_preflight()
    names = {i.name for i in report.items}
    assert "tag" in names
    assert "version" in names
    assert "live_guard" in names
    assert "risk_config" in names


def test_preflight_version_check() -> None:
    report = run_preflight(expected_version="1.0.0")
    ver_item = next(i for i in report.items if i.name == "version")
    assert ver_item.passed or "Installed ztb" in ver_item.detail or "error" in ver_item.detail


def test_preflight_live_guard_disarmed() -> None:
    from ztb.execution.live_guard import LiveGuard

    LiveGuard.disarm()
    report = run_preflight()
    guard_item = next(i for i in report.items if i.name == "live_guard")
    assert guard_item.passed
    assert "DISARMED" in guard_item.detail


def test_preflight_unknown_strategy() -> None:
    report = run_preflight(strategy_name="nonexistent_strategy")
    strat_item = next((i for i in report.items if i.name == "strategy"), None)
    assert strat_item is not None
    assert not strat_item.passed or "Strategy not found" in strat_item.detail


def test_preflight_report_serializable() -> None:
    report = run_preflight()
    assert isinstance(report.passed, bool)
    for item in report.items:
        assert isinstance(item.name, str)
        assert isinstance(item.passed, bool)
