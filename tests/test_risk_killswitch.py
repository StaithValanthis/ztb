from __future__ import annotations

from ztb.risk.killswitch import KillSwitch


def test_initial_state() -> None:
    ks = KillSwitch()
    assert ks.hwm == 0.0
    assert ks.tripped is False
    assert ks.cooldown_remaining == 0
    assert ks.trip_reason == ""


def test_update_increases_hwm() -> None:
    ks = KillSwitch()
    ks.update(100.0)
    assert ks.hwm == 100.0
    ks.update(150.0)
    assert ks.hwm == 150.0


def test_update_does_not_decrease_hwm() -> None:
    ks = KillSwitch()
    ks.update(100.0)
    ks.update(50.0)
    assert ks.hwm == 100.0


def test_check_trip_no_trip_without_hwm() -> None:
    ks = KillSwitch()
    tripped = ks.check_trip(100.0)
    assert tripped is False
    assert ks.hwm == 100.0


def test_check_trip_no_trip_below_threshold() -> None:
    ks = KillSwitch(account_killswitch_dd=0.25)
    ks.update(100.0)
    tripped = ks.check_trip(80.0)
    assert tripped is False


def test_check_trip_trips_at_threshold() -> None:
    ks = KillSwitch(account_killswitch_dd=0.25)
    ks.update(100.0)
    tripped = ks.check_trip(75.0)
    assert tripped is True
    assert ks.tripped is True
    assert ks.cooldown_remaining == ks.cooldown_bars
    assert "drawdown" in ks.trip_reason


def test_check_trip_trips_above_threshold() -> None:
    ks = KillSwitch(account_killswitch_dd=0.25)
    ks.update(100.0)
    tripped = ks.check_trip(70.0)
    assert tripped is True


def test_flatten_signal_returns_zero() -> None:
    ks = KillSwitch()
    assert ks.flatten_signal(1.0) == 0.0
    assert ks.flatten_signal(-0.5) == 0.0


def test_cooldown_tick_decrements() -> None:
    ks = KillSwitch(account_killswitch_dd=0.25, cooldown_bars=100)
    ks.update(100.0)
    ks.check_trip(70.0)
    assert ks.tripped is True
    assert ks.cooldown_remaining == 100
    ks.cooldown_tick()
    assert ks.cooldown_remaining == 99


def test_cooldown_auto_reset() -> None:
    ks = KillSwitch(account_killswitch_dd=0.25, cooldown_bars=3)
    ks.update(100.0)
    ks.check_trip(70.0)
    assert ks.tripped is True
    ks.cooldown_tick()
    assert ks.tripped is True
    ks.cooldown_tick()
    assert ks.tripped is True
    ks.cooldown_tick()
    assert ks.tripped is False
    assert ks.cooldown_remaining == 0


def test_reset() -> None:
    ks = KillSwitch(account_killswitch_dd=0.25, cooldown_bars=100)
    ks.update(100.0)
    ks.check_trip(70.0)
    ks.reset(current_equity=80.0)
    assert ks.hwm == 80.0
    assert ks.tripped is False
    assert ks.cooldown_remaining == 0
    assert ks.trip_reason == ""


def test_is_tripped() -> None:
    ks = KillSwitch()
    assert ks.is_tripped() is False
    ks.tripped = True
    assert ks.is_tripped() is True


def test_to_dict_round_trip() -> None:
    ks = KillSwitch(account_killswitch_dd=0.25, cooldown_bars=100)
    ks.update(100.0)
    ks.check_trip(70.0)
    d = ks.to_dict()
    assert d["hwm"] == 100.0
    assert d["tripped"] is True
    assert d["cooldown_remaining"] == 100
    assert "drawdown" in d["trip_reason"]
    assert d["account_killswitch_dd"] == 0.25
    assert d["cooldown_bars"] == 100

    ks2 = KillSwitch.from_dict(d)
    assert ks2.hwm == 100.0
    assert ks2.tripped is True
    assert ks2.cooldown_remaining == 100
    assert ks2.account_killswitch_dd == 0.25


def test_custom_dd_threshold() -> None:
    ks = KillSwitch(account_killswitch_dd=0.10)
    ks.update(100.0)
    assert ks.check_trip(91.0) is False
    ks = KillSwitch(account_killswitch_dd=0.10)
    ks.update(100.0)
    assert ks.check_trip(90.0) is True
    ks = KillSwitch(account_killswitch_dd=0.10)
    ks.update(100.0)
    assert ks.check_trip(85.0) is True


def test_no_trip_when_equity_above_hwm() -> None:
    ks = KillSwitch(account_killswitch_dd=0.25)
    ks.update(100.0)
    tripped = ks.check_trip(120.0)
    assert tripped is False
