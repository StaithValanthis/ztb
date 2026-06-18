from __future__ import annotations

import pandas as pd

from ztb.execution.executor import Executor
from ztb.execution.models import ExecRunConfig, Mode
from ztb.strategies.base import RiskProfile


class _FakeClient:
    def __init__(self) -> None:
        self.lev_calls: list = []

    def set_leverage(self, symbol, buy_leverage, sell_leverage, category="linear"):
        self.lev_calls.append((symbol, buy_leverage, sell_leverage))
        return {}


class _Strat:
    name = "t"
    symbols = ["BTCUSDT"]
    timeframe = "60"
    params: dict = {}
    warmup = 1

    def __init__(self, profile: RiskProfile | None = None) -> None:
        self.risk_profile = profile if profile is not None else RiskProfile()

    def get_risk_profile(self) -> RiskProfile:
        return self.risk_profile

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(dtype=float)


def _exe(profile, dry_run=False):
    cfg = ExecRunConfig(mode=Mode.DEMO, dry_run=dry_run)
    client = _FakeClient()
    return Executor(_Strat(profile), config=cfg, client=client), client


def test_apply_leverage_when_declared() -> None:
    e, c = _exe(RiskProfile(leverage=2.0))
    e._apply_leverage("BTCUSDT")
    assert c.lev_calls == [("BTCUSDT", 2.0, 2.0)]


def test_apply_leverage_idempotent() -> None:
    e, c = _exe(RiskProfile(leverage=2.0))
    e._apply_leverage("BTCUSDT")
    e._apply_leverage("BTCUSDT")
    assert len(c.lev_calls) == 1


def test_no_leverage_when_not_declared() -> None:
    e, c = _exe(RiskProfile())
    e._apply_leverage("BTCUSDT")
    assert c.lev_calls == []


def test_no_leverage_in_dry_run() -> None:
    e, c = _exe(RiskProfile(leverage=2.0), dry_run=True)
    e._apply_leverage("BTCUSDT")
    assert c.lev_calls == []


def test_resolve_exchange_leverage() -> None:
    e, _ = _exe(RiskProfile(leverage=3.0))
    assert e._resolve_exchange_leverage() == 3.0
    e2, _ = _exe(RiskProfile())
    assert e2._resolve_exchange_leverage() is None


def test_resolve_sizing_leverage() -> None:
    e, _ = _exe(RiskProfile())  # no declared leverage -> config.max_leverage default 3.0
    assert e._resolve_sizing_leverage() == 3.0
    e2, _ = _exe(RiskProfile(leverage=2.0))
    assert e2._resolve_sizing_leverage() == 2.0
