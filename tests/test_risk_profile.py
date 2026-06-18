from __future__ import annotations

import pytest

from ztb.strategies.base import (
    _DEFAULT_RISK_PROFILE,
    RiskProfile,
    ScaleOutTier,
    Strategy,
    TradeManagementProfile,
)


def test_dataclasses_exist_and_default_all_none() -> None:
    p = RiskProfile()
    assert p.sl_pct is None and p.tp_pct is None and p.leverage is None
    assert p.trail_pct is None and p.activation_pct is None
    assert p.trail_atr_mult is None and p.scale_outs is None
    assert TradeManagementProfile is RiskProfile


def test_scaleout_tier_validation() -> None:
    ScaleOutTier(at_pct=0.02, close_frac=0.5)
    with pytest.raises(ValueError):
        ScaleOutTier(at_pct=0.0, close_frac=0.5)
    with pytest.raises(ValueError):
        ScaleOutTier(at_pct=0.02, close_frac=0.0)
    with pytest.raises(ValueError):
        ScaleOutTier(at_pct=0.02, close_frac=1.5)


def test_riskprofile_range_validation() -> None:
    RiskProfile(sl_pct=0.05, tp_pct=0.10, leverage=2.0, trail_pct=0.02)
    with pytest.raises(ValueError):
        RiskProfile(sl_pct=0.6)
    with pytest.raises(ValueError):
        RiskProfile(tp_pct=20.0)
    with pytest.raises(ValueError):
        RiskProfile(leverage=0.5)
    with pytest.raises(ValueError):
        RiskProfile(leverage=200.0)
    with pytest.raises(ValueError):
        RiskProfile(trail_atr_mult=0.0)  # must be > 0 (use None to disable)


def test_zero_allowed_as_explicit_disable() -> None:
    p = RiskProfile(sl_pct=0.0, tp_pct=0.0)
    assert p.sl_pct == 0.0 and p.tp_pct == 0.0


def test_scale_outs_ascending_and_sum_le_one() -> None:
    RiskProfile(scale_outs=(ScaleOutTier(0.02, 0.5), ScaleOutTier(0.04, 0.5)))
    with pytest.raises(ValueError):
        RiskProfile(scale_outs=(ScaleOutTier(0.04, 0.5), ScaleOutTier(0.02, 0.5)))
    with pytest.raises(ValueError):
        RiskProfile(scale_outs=(ScaleOutTier(0.02, 0.6), ScaleOutTier(0.04, 0.6)))


def test_strategy_base_default_profile() -> None:
    assert Strategy.risk_profile is _DEFAULT_RISK_PROFILE
    assert _DEFAULT_RISK_PROFILE.sl_pct is None
