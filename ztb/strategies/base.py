from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd
from pandas import Series

# Validation bounds mirror ExecRunConfig (ztb/execution/models.py).
_SL_LO, _SL_HI = 0.001, 0.50
_TP_LO, _TP_HI = 0.001, 10.0
_LEV_LO, _LEV_HI = 1.0, 100.0
_TRAIL_LO, _TRAIL_HI = 0.001, 0.50


@dataclass(frozen=True)
class ScaleOutTier:
    """One partial take-profit tier.

    Close ``close_frac`` of the ORIGINAL entry size when price reaches
    ``at_pct`` profit from the average entry (sign handled by side).
    """

    at_pct: float
    close_frac: float

    def __post_init__(self) -> None:
        if not (0.0 < self.at_pct <= 10.0):
            raise ValueError(f"ScaleOutTier.at_pct must be in (0, 10], got {self.at_pct}")
        if not (0.0 < self.close_frac <= 1.0):
            raise ValueError(f"ScaleOutTier.close_frac must be in (0, 1], got {self.close_frac}")


@dataclass(frozen=True)
class RiskProfile:
    """Per-strategy trade-management declaration.

    Every field is Optional. ``None`` means "this strategy does not manage this
    field" -> the executor falls through to the global ExecRunConfig, then a hard
    default. ``0.0`` is DISTINCT from ``None``: it is an explicit DISABLE (e.g.
    ``sl_pct=0.0`` = run with no stop-loss). The executor must preserve that
    distinction or a None->0.0 coercion would silently disable the stop-loss.
    Precedence per field: RiskProfile > strategy.params[sl/tp only] >
    ExecRunConfig > hard default.
    """

    sl_pct: float | None = None
    tp_pct: float | None = None
    leverage: float | None = None
    trail_pct: float | None = None
    activation_pct: float | None = None
    trail_atr_mult: float | None = None
    scale_outs: tuple[ScaleOutTier, ...] | None = None

    def __post_init__(self) -> None:
        def _rng(v: float | None, lo: float, hi: float, name: str) -> None:
            if v is not None and v != 0.0 and not (lo <= v <= hi):
                raise ValueError(f"RiskProfile.{name} must be in [{lo}, {hi}] or 0.0, got {v}")

        _rng(self.sl_pct, _SL_LO, _SL_HI, "sl_pct")
        _rng(self.tp_pct, _TP_LO, _TP_HI, "tp_pct")
        _rng(self.trail_pct, _TRAIL_LO, _TRAIL_HI, "trail_pct")
        if self.leverage is not None and not (_LEV_LO <= self.leverage <= _LEV_HI):
            raise ValueError(f"RiskProfile.leverage must be in [1, 100], got {self.leverage}")
        if self.activation_pct is not None and self.activation_pct < 0.0:
            raise ValueError(f"RiskProfile.activation_pct must be >= 0, got {self.activation_pct}")
        if self.trail_atr_mult is not None and self.trail_atr_mult <= 0.0:
            raise ValueError(f"RiskProfile.trail_atr_mult must be > 0, got {self.trail_atr_mult}")
        if self.scale_outs is not None:
            tiers = self.scale_outs
            for i in range(len(tiers) - 1):
                if tiers[i].at_pct >= tiers[i + 1].at_pct:
                    raise ValueError("RiskProfile.scale_outs must be strictly ascending by at_pct")
            if sum(t.close_frac for t in tiers) > 1.0 + 1e-9:
                raise ValueError("RiskProfile.scale_outs close_frac sum must be <= 1.0")
            if self.trail_pct is not None or self.trail_atr_mult is not None:
                raise ValueError(
                    "RiskProfile: trailing + scale_outs together is not supported "
                    "(the post-scale-out SL re-assert would drop the trailing stop)"
                )


# Contract-name alias.
TradeManagementProfile = RiskProfile

# Shared immutable default: all-None -> the executor falls through to config.
_DEFAULT_RISK_PROFILE = RiskProfile()


class Strategy(ABC):
    name: str
    symbols: list[str]
    timeframe: str
    params: dict[str, float | int | str]
    warmup: int
    risk_profile: RiskProfile = _DEFAULT_RISK_PROFILE  # override per plugin

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> Series: ...

    def get_risk_profile(self) -> RiskProfile:
        """Executor read path. Override to compute a profile dynamically from
        ``self.params``; the default returns the declared class attribute."""
        return self.risk_profile


class StrategyError(Exception):
    pass
