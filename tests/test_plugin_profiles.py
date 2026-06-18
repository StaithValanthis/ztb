from __future__ import annotations

from ztb.strategies.base import _DEFAULT_RISK_PROFILE, RiskProfile
from ztb.strategies.registry import get, list_names

_BEARS = {
    "bearish_resumption": (0.03, 0.06, 2.0),
    "bear_bounce_exhaustion": (0.03, 0.05, 2.0),
    "bear_flag_continuation_short": (0.04, 0.08, 2.0),
    "bear_vol_continuation": (0.04, 0.06, 2.0),
}


def test_sma_cross_profile() -> None:
    p = get("sma_cross")().get_risk_profile()
    assert p.sl_pct == 0.05 and p.tp_pct == 0.10


def test_bear_profiles_sl_tp_leverage() -> None:
    for name, (sl, tp, lev) in _BEARS.items():
        p = get(name)().get_risk_profile()
        assert p.sl_pct == sl, name
        assert p.tp_pct == tp, name
        assert p.leverage == lev, name


def test_bears_no_executor_trailing_or_scaleouts() -> None:
    # Bears trail in generate_signals -> must NOT also set executor trailing.
    for name in _BEARS:
        p = get(name)().get_risk_profile()
        assert p.trail_pct is None and p.trail_atr_mult is None, name
        assert p.scale_outs is None, name


def test_bears_declare_explicit_profile() -> None:
    for name in _BEARS:
        assert get(name).risk_profile is not _DEFAULT_RISK_PROFILE, name


def test_all_registered_strategies_have_risk_profile() -> None:
    names = list_names()
    assert names
    for name in names:
        p = get(name)().get_risk_profile()
        assert isinstance(p, RiskProfile)
