from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from ztb.engine.pnl import PnLCalculator
from ztb.execution.executor import Executor
from ztb.execution.models import ExecRunConfig, Mode, OrderSide
from ztb.strategies.base import RiskProfile, ScaleOutTier


class _FakeClient:
    def __init__(self) -> None:
        self.orders: list = []
        self.ts: list = []

    def get_qty_step(self, symbol, category="linear"):
        return 0.001

    def get_min_order_qty(self, symbol, category="linear"):
        return 0.001

    def place_order(self, symbol, side, qty, order_type=None, order_link_id="", reduce_only=False, **kw):
        self.orders.append((side, qty, reduce_only, order_link_id))
        return {"orderId": "x"}

    def set_trading_stop(self, **kw):
        self.ts.append(kw)
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
    return e, e.client


def test_seed_scale_outs_long() -> None:
    prof = RiskProfile(scale_outs=(ScaleOutTier(0.02, 0.5), ScaleOutTier(0.04, 0.5)))
    e, _ = _exe(prof)
    e._seed_scale_outs("BTCUSDT", 0.01, 65000.0, "b1", prof.scale_outs)
    tiers = e._active_sl_tp["BTCUSDT"]["scale_tiers"]
    assert len(tiers) == 2
    assert abs(tiers[0]["at_price"] - 65000.0 * 1.02) < 1e-6
    assert abs(tiers[1]["at_price"] - 65000.0 * 1.04) < 1e-6
    assert e._active_sl_tp["BTCUSDT"]["entry_qty"] == 0.01


def test_scale_out_tier_fires_reduce_only() -> None:
    prof = RiskProfile(sl_pct=0.02, scale_outs=(ScaleOutTier(0.02, 0.5),))
    e, c = _exe(prof)
    e._pnl.apply_fill(0.01, 65000.0)
    e._seed_scale_outs("BTCUSDT", 0.01, 65000.0, "b1", prof.scale_outs)
    e._check_scale_outs("BTCUSDT", 66400.0)  # crosses 66300
    assert len(c.orders) == 1
    side, qty, reduce_only, _lid = c.orders[0]
    assert side == OrderSide.SELL and reduce_only is True
    assert abs(qty - 0.005) < 1e-6
    assert e._active_sl_tp["BTCUSDT"]["scale_tiers"][0]["fired"] is True
    assert abs(e._active_sl_tp["BTCUSDT"]["fired_frac"] - 0.5) < 1e-9
    assert len(c.ts) >= 1  # SL re-asserted on the remainder
    assert "scale_tiers" in e._active_sl_tp["BTCUSDT"]  # state preserved across re-assert


def test_scale_out_idempotent() -> None:
    prof = RiskProfile(scale_outs=(ScaleOutTier(0.02, 0.5),))
    e, c = _exe(prof)
    e._pnl.apply_fill(0.01, 65000.0)
    e._seed_scale_outs("BTCUSDT", 0.01, 65000.0, "b1", prof.scale_outs)
    e._check_scale_outs("BTCUSDT", 66400.0)
    e._check_scale_outs("BTCUSDT", 66400.0)
    assert len(c.orders) == 1


def test_scale_out_short_fires_on_drop() -> None:
    prof = RiskProfile(scale_outs=(ScaleOutTier(0.02, 0.5),))
    e, c = _exe(prof)
    e._pnl.apply_fill(-0.01, 65000.0)
    e._seed_scale_outs("BTCUSDT", -0.01, 65000.0, "b1", prof.scale_outs)
    e._check_scale_outs("BTCUSDT", 63600.0)  # below 63700
    assert len(c.orders) == 1
    side, _qty, reduce_only, _lid = c.orders[0]
    assert side == OrderSide.BUY and reduce_only is True


def test_scale_out_no_fire_when_not_crossed() -> None:
    prof = RiskProfile(scale_outs=(ScaleOutTier(0.02, 0.5),))
    e, c = _exe(prof)
    e._pnl.apply_fill(0.01, 65000.0)
    e._seed_scale_outs("BTCUSDT", 0.01, 65000.0, "b1", prof.scale_outs)
    e._check_scale_outs("BTCUSDT", 65500.0)
    assert len(c.orders) == 0


def test_no_scale_outs_is_noop() -> None:
    e, c = _exe(RiskProfile(sl_pct=0.02))
    e._pnl.apply_fill(0.01, 65000.0)
    e._check_scale_outs("BTCUSDT", 70000.0)
    assert len(c.orders) == 0
