from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class RiskDecisionAction(StrEnum):
    proceed = "proceed"
    reduce = "reduce"
    halt = "halt"


@dataclass(frozen=True)
class RiskDecision:
    action: RiskDecisionAction
    reason: str = ""
    max_pos_size: float = 0.0
    max_leverage: float = 0.0
    max_notional: float = 0.0
    current_dd: float | None = None
    current_heat: float | None = None
    hwm: float | None = None
    timestamp: str = ""
    symbol: str = ""


@dataclass
class RiskConfig:
    max_portfolio_dd: float = 0.25
    account_killswitch_dd: float = 0.25
    vol_target: float = 0.20
    max_leverage: float = 3.0
    max_position_pct: float = 0.50
    max_heat: float = 1.0
    max_correlation: float = 0.80
    dd_budget_scalar_power: float = 3.0
    cooldown_bars: int = 100
    min_notional: float = 5.0
    vol_lookback: int = 21
    corr_lookback: int = 21
    vol_floor: float = 0.05
    default_slippage: float = 0.0005
    default_commission: float = 0.0005

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_portfolio_dd": self.max_portfolio_dd,
            "account_killswitch_dd": self.account_killswitch_dd,
            "vol_target": self.vol_target,
            "max_leverage": self.max_leverage,
            "max_position_pct": self.max_position_pct,
            "max_heat": self.max_heat,
            "max_correlation": self.max_correlation,
            "dd_budget_scalar_power": self.dd_budget_scalar_power,
            "cooldown_bars": self.cooldown_bars,
            "min_notional": self.min_notional,
            "vol_lookback": self.vol_lookback,
            "corr_lookback": self.corr_lookback,
            "vol_floor": self.vol_floor,
            "default_slippage": self.default_slippage,
            "default_commission": self.default_commission,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> RiskConfig:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
