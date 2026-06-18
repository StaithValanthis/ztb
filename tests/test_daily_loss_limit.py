from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from ztb.execution.executor import Executor
from ztb.execution.models import ExecRunConfig, Mode


class _Strat:
    name = "t"
    symbols = ["BTCUSDT"]
    timeframe = "60"
    params: dict = {}
    warmup = 1

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(dtype=float)


def _exe(limit, realized=0.0, cash=10000.0):
    cfg = ExecRunConfig(mode=Mode.DEMO, initial_cash=cash, daily_loss_limit_pct=limit)
    e = Executor(_Strat(), config=cfg, client=None)
    e._pnl = SimpleNamespace(realized_pnl=realized)
    return e


def test_config_field_default_disabled() -> None:
    assert ExecRunConfig(mode=Mode.DEMO).daily_loss_limit_pct == 0.0


def test_disabled_never_breaches() -> None:
    e = _exe(0.0, realized=-9999.0)
    assert e._daily_loss_breached("2026-06-18 00:00:00") is False


def test_not_breached_below_limit() -> None:
    e = _exe(0.05, realized=-300.0)  # limit = 5% * 10000 = 500
    assert e._daily_loss_breached("2026-06-18 00:00:00") is False


def test_breached_at_limit() -> None:
    e = _exe(0.05, realized=0.0)
    e._daily_loss_breached("2026-06-18 00:00:00")  # snapshot day-start = 0
    e._pnl.realized_pnl = -600.0
    assert e._daily_loss_breached("2026-06-18 12:00:00") is True


def test_resets_at_utc_day_boundary() -> None:
    e = _exe(0.05, realized=0.0)
    assert e._daily_loss_breached("2026-06-18 00:00:00") is False
    e._pnl.realized_pnl = -600.0
    assert e._daily_loss_breached("2026-06-18 12:00:00") is True  # same day -> breached
    # new UTC day: snapshot resets to -600, today's delta = 0 -> not breached
    assert e._daily_loss_breached("2026-06-19 00:00:00") is False
