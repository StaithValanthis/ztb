from __future__ import annotations

import time

from ztb.execution.killswitch import LiveKillSwitch


def test_default_not_tripped() -> None:
    ks = LiveKillSwitch()
    assert not ks.is_tripped
    assert ks.get_triggers() == []


def test_manual_trip() -> None:
    ks = LiveKillSwitch()
    ks.manual_trip("test kill")
    assert ks.is_tripped
    assert len(ks.get_triggers()) == 1
    assert ks.get_triggers()[0].source == "manual"


def test_reset() -> None:
    ks = LiveKillSwitch()
    ks.manual_trip("test")
    ks.reset()
    assert not ks.is_tripped
    assert ks.get_triggers() == []


def test_check_account_dd_triggers() -> None:
    ks = LiveKillSwitch(max_account_dd=0.1)
    ks.check_account_dd(100.0)
    assert not ks.is_tripped
    ks.check_account_dd(80.0)
    assert ks.is_tripped
    assert ks.get_triggers()[0].source == "account_dd"


def test_check_account_dd_hwm_tracking() -> None:
    ks = LiveKillSwitch(max_account_dd=0.2)
    ks.check_account_dd(100.0)
    ks.check_account_dd(90.0)
    assert not ks.is_tripped
    ks.check_account_dd(79.0)
    assert ks.is_tripped


def test_check_reconcile_drift() -> None:
    ks = LiveKillSwitch(max_reconcile_drift=0.01)
    assert not ks.check_reconcile_drift(0.005)
    assert ks.check_reconcile_drift(0.015)


def test_check_data_staleness() -> None:
    ks = LiveKillSwitch(max_data_staleness_sec=0.1)
    from datetime import UTC, datetime

    old_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    time.sleep(0.2)
    assert ks.check_data_staleness(old_ts)


def test_check_data_staleness_fresh() -> None:
    ks = LiveKillSwitch(max_data_staleness_sec=300.0)
    from datetime import UTC, datetime

    fresh_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert not ks.check_data_staleness(fresh_ts)


def test_check_heartbeat() -> None:
    ks = LiveKillSwitch(heartbeat_timeout_sec=0.1)
    ks.heartbeat()
    assert not ks.check_heartbeat()
    time.sleep(0.15)
    assert ks.check_heartbeat()


def test_get_triggers() -> None:
    ks = LiveKillSwitch()
    ks.manual_trip("first")
    ks.manual_trip("second")
    triggers = ks.get_triggers()
    assert len(triggers) == 2
    assert triggers[0].reason == "first"
    assert triggers[1].reason == "second"


def test_to_store_dict() -> None:
    ks = LiveKillSwitch(max_account_dd=0.1)
    ks.check_account_dd(100.0)
    ks.check_account_dd(85.0)
    d = ks.to_store_dict("exec_001")
    assert d["exec_run_id"] == "exec_001"
    assert d["tripped"] is True
    assert len(d["triggers"]) == 1
    assert d["triggers"][0]["source"] == "account_dd"
    assert d["hwm_equity"] == 100.0
    assert d["current_equity"] == 85.0


def test_triggers_property() -> None:
    ks = LiveKillSwitch()
    ks.manual_trip("test")
    assert len(ks.triggers) == 1
    assert ks.triggers[0].source == "manual"


def test_check_account_dd_hwm_zero() -> None:
    ks = LiveKillSwitch(max_account_dd=0.1)
    assert not ks.check_account_dd(-100.0)


def test_check_data_staleness_invalid_ts() -> None:
    ks = LiveKillSwitch(max_data_staleness_sec=0.1)
    assert not ks.check_data_staleness("not-a-timestamp")
    assert not ks.check_data_staleness("")
