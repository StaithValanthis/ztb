from __future__ import annotations

from ztb.strategies.base import RiskProfile
from ztb.strategies.registry import get, list_names


def test_sma_cross_profile() -> None:
    p = get("sma_cross")().get_risk_profile()
    assert p.sl_pct == 0.05 and p.tp_pct == 0.10


def test_all_registered_strategies_have_risk_profile() -> None:
    names = list_names()
    assert names
    for name in names:
        p = get(name)().get_risk_profile()
        assert isinstance(p, RiskProfile)
