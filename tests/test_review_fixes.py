from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from ztb.engine.pnl import PnLCalculator
from ztb.execution.executor import Executor
from ztb.execution.models import ExecRunConfig, Mode
from ztb.strategies.base import RiskProfile, ScaleOutTier


class _FakeClient:
    def __init__(self) -> None:
        self.orders: list = []

    def get_qty_step(self, symbol, category="linear"):
        return 0.001

    def get_min_order_qty(self, symbol, category="linear"):
        return 0.001

    def place_order(
        self, symbol, side, qty, order_type=None, order_link_id="", reduce_only=False, **kw
    ):
        self.orders.append((side, qty, reduce_only))
        return {"orderId": "x"}

    def set_trading_stop(self, **kw):
        return {}


class _Strat:
    name = "t"
    symbols = ["BTCUSDT"]
    timeframe = "60"
    params: dict = {}
    warmup = 1

    def __init__(self, profile) -> None:
        self.risk_profile = profile

    def get_risk_profile(self):
        return self.risk_profile

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(dtype=float)


def _exe(profile):
    e = Executor(_Strat(profile), config=ExecRunConfig(mode=Mode.DEMO), client=_FakeClient())
    e.state = SimpleNamespace(last_bar_ts="b1", strategy_name="t", symbol="BTCUSDT")
    e._pnl = PnLCalculator(initial_cash=10000.0)
    e._idempotency = None
    e._signal_initialized = True
    return e, e.client


def test_full_scaleout_clears_state_no_freeze() -> None:
    # close_frac sum == 1.0 -> fully scaled out -> state must be cleared (no freeze)
    prof = RiskProfile(sl_pct=0.02, scale_outs=(ScaleOutTier(0.02, 0.5), ScaleOutTier(0.04, 0.5)))
    e, c = _exe(prof)
    e._pnl.apply_fill(0.01, 65000.0)
    e._seed_scale_outs("BTCUSDT", 0.01, 65000.0, "b1", prof.scale_outs)
    e._check_scale_outs("BTCUSDT", 70000.0)  # crosses BOTH tiers -> fully out
    assert abs(e._pnl.position) < 1e-9
    assert "BTCUSDT" not in e._active_sl_tp  # state cleared
    assert e._signal_initialized is False  # signal reset so a fresh entry can re-arm


def test_riskprofile_forbids_trail_with_scaleouts() -> None:
    with pytest.raises(ValueError):
        RiskProfile(trail_pct=0.02, scale_outs=(ScaleOutTier(0.02, 0.5),))
    with pytest.raises(ValueError):
        RiskProfile(trail_atr_mult=2.0, scale_outs=(ScaleOutTier(0.02, 0.5),))


def test_partial_scaleout_keeps_state_and_fired_frac() -> None:
    prof = RiskProfile(sl_pct=0.02, scale_outs=(ScaleOutTier(0.02, 0.5), ScaleOutTier(0.10, 0.5)))
    e, _ = _exe(prof)
    e._pnl.apply_fill(0.01, 65000.0)
    e._seed_scale_outs("BTCUSDT", 0.01, 65000.0, "b1", prof.scale_outs)
    e._check_scale_outs("BTCUSDT", 66400.0)  # crosses only tier 0
    assert "BTCUSDT" in e._active_sl_tp
    assert abs(e._active_sl_tp["BTCUSDT"]["fired_frac"] - 0.5) < 1e-6
