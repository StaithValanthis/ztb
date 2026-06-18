from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from ztb.execution.bybit_client import BybitClient, ClientConfig
from ztb.execution.executor import Executor
from ztb.execution.models import ExecRunConfig, Mode, OrderSide
from ztb.strategies.base import RiskProfile


def _bybit(monkeypatch):
    c = BybitClient(ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO))
    calls: list = []
    monkeypatch.setattr(c, "_request", lambda m, p, body=None, **k: (calls.append(body), {"ok": 1})[1])
    return c, calls


def test_trading_stop_includes_trailing_when_set(monkeypatch) -> None:
    c, calls = _bybit(monkeypatch)
    c.set_trading_stop(
        "BTCUSDT", OrderSide.BUY, 0.01, stop_loss=64000.0, trailing_stop=1300.0, active_price=66000.0
    )
    b = calls[0]
    assert b["trailingStop"] == "1300.0"
    assert b["activePrice"] == "66000.0"


def test_trading_stop_omits_trailing_when_zero(monkeypatch) -> None:
    c, calls = _bybit(monkeypatch)
    c.set_trading_stop("BTCUSDT", OrderSide.BUY, 0.01, stop_loss=64000.0)
    assert "trailingStop" not in calls[0]
    assert "activePrice" not in calls[0]


class _FakeClient:
    def __init__(self) -> None:
        self.ts_calls: list = []

    def set_trading_stop(self, **kw):
        self.ts_calls.append(kw)
        return {}


class _Strat:
    name = "t"
    symbols = ["BTCUSDT"]
    timeframe = "60"
    params: dict = {}
    warmup = 1

    def __init__(self, profile: RiskProfile) -> None:
        self.risk_profile = profile

    def get_risk_profile(self) -> RiskProfile:
        return self.risk_profile

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(dtype=float)


def _exe(profile):
    e = Executor(_Strat(profile), config=ExecRunConfig(mode=Mode.DEMO), client=_FakeClient())
    e.state = SimpleNamespace(last_bar_ts="", strategy_name="t")
    return e, e.client


def test_executor_trailing_pct_long() -> None:
    e, c = _exe(RiskProfile(sl_pct=0.02, trail_pct=0.02, activation_pct=0.01))
    e._apply_sl_tp(
        "BTCUSDT", OrderSide.BUY, 0.01, 65000.0, 0.02, 0.0, trail_pct=0.02, activation_pct=0.01
    )
    kw = c.ts_calls[0]
    assert abs(kw["trailing_stop"] - 65000.0 * 0.02) < 1e-6
    assert abs(kw["active_price"] - 65000.0 * 1.01) < 1e-6
    assert kw["stop_loss"] > 0  # hard SL floor still set alongside trailing


def test_executor_trailing_atr() -> None:
    e, c = _exe(RiskProfile(trail_atr_mult=2.0))
    e._apply_sl_tp("BTCUSDT", OrderSide.BUY, 0.01, 65000.0, 0.0, 0.0, trail_atr_mult=2.0, atr=500.0)
    assert abs(c.ts_calls[0]["trailing_stop"] - 1000.0) < 1e-6


def test_executor_trailing_short_activation_below_entry() -> None:
    e, c = _exe(RiskProfile(trail_pct=0.02, activation_pct=0.01))
    e._apply_sl_tp(
        "BTCUSDT", OrderSide.SELL, -0.01, 65000.0, 0.0, 0.0, trail_pct=0.02, activation_pct=0.01
    )
    assert abs(c.ts_calls[0]["active_price"] - 65000.0 * 0.99) < 1e-6


def test_executor_no_trailing_when_unset() -> None:
    e, c = _exe(RiskProfile(sl_pct=0.02))
    e._apply_sl_tp("BTCUSDT", OrderSide.BUY, 0.01, 65000.0, 0.02, 0.0)
    assert c.ts_calls[0]["trailing_stop"] == 0.0
