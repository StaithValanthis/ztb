from __future__ import annotations

from dataclasses import dataclass

from ztb.execution.executor import _PROFILE_DEFAULTS, _resolve_profile_field
from ztb.strategies.base import RiskProfile


class _Strat:
    def __init__(self, profile: RiskProfile | None = None, params: dict | None = None) -> None:
        self.risk_profile = profile if profile is not None else RiskProfile()
        self.params = params if params is not None else {}

    def get_risk_profile(self) -> RiskProfile:
        return self.risk_profile


@dataclass
class _Cfg:
    sl_pct: float = 0.02
    tp_pct: float = 0.03
    max_leverage: float = 3.0


def test_profile_beats_params_and_config() -> None:
    s = _Strat(profile=RiskProfile(sl_pct=0.05), params={"sl_pct": 0.07})
    assert _resolve_profile_field(s, _Cfg(), "sl_pct") == 0.05


def test_params_backcompat_when_profile_field_none() -> None:
    s = _Strat(profile=RiskProfile(), params={"sl_pct": 0.07})
    assert _resolve_profile_field(s, _Cfg(), "sl_pct") == 0.07


def test_config_when_no_profile_no_params() -> None:
    s = _Strat(profile=RiskProfile(), params={})
    assert _resolve_profile_field(s, _Cfg(sl_pct=0.02), "sl_pct") == 0.02


def test_cli_zero_sentinel_returned_not_reenabled() -> None:
    # config.sl_pct = 0.0 (CLI omitted the flag) must be returned as 0.0,
    # NOT silently re-enabled to the 0.02 hard default.
    s = _Strat(profile=RiskProfile(), params={})
    assert _resolve_profile_field(s, _Cfg(sl_pct=0.0), "sl_pct") == 0.0


def test_profile_zero_disables_over_params() -> None:
    s = _Strat(profile=RiskProfile(sl_pct=0.0), params={"sl_pct": 0.07})
    assert _resolve_profile_field(s, _Cfg(), "sl_pct") == 0.0


def test_leverage_maps_to_max_leverage() -> None:
    s = _Strat(profile=RiskProfile())
    assert _resolve_profile_field(s, _Cfg(max_leverage=3.0), "leverage") == 3.0
    s2 = _Strat(profile=RiskProfile(leverage=2.0))
    assert _resolve_profile_field(s2, _Cfg(max_leverage=3.0), "leverage") == 2.0


def test_params_backcompat_only_sl_tp_not_leverage() -> None:
    s = _Strat(profile=RiskProfile(), params={"leverage": 5.0})
    # leverage is NOT read from params by the generic helper -> falls to config
    assert _resolve_profile_field(s, _Cfg(max_leverage=3.0), "leverage") == 3.0


def test_hard_default_when_config_attr_missing() -> None:
    class _BareCfg:
        pass

    s = _Strat(profile=RiskProfile())
    assert _resolve_profile_field(s, _BareCfg(), "tp_pct") == _PROFILE_DEFAULTS["tp_pct"]
    assert _resolve_profile_field(s, _BareCfg(), "trail_pct") == _PROFILE_DEFAULTS["trail_pct"]
