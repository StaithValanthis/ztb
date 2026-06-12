from __future__ import annotations

from typing import Any

import numpy as np
from pandas import DataFrame

from ztb.risk.dd_budget import dd_budget_scalar
from ztb.risk.heat import compute_heat, heat_cap_check
from ztb.risk.killswitch import KillSwitch
from ztb.risk.models import RiskConfig, RiskDecision, RiskDecisionAction


class RiskManager:
    def __init__(
        self,
        config: RiskConfig | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self.config = config or RiskConfig()
        self.kill_switch = kill_switch or KillSwitch(
            account_killswitch_dd=self.config.account_killswitch_dd,
            cooldown_bars=self.config.cooldown_bars,
        )
        self._decisions: list[RiskDecision] = []
        self._cov: np.ndarray[Any, Any] | None = None
        self._returns_df: DataFrame | None = None

    @property
    def decisions(self) -> list[RiskDecision]:
        return list(self._decisions)

    def update_portfolio_equity(self, current_equity: float) -> None:
        self.kill_switch.update(current_equity)

    def set_returns(self, returns_df: DataFrame) -> None:
        self._returns_df = returns_df

    def set_covariance(self, cov: np.ndarray[Any, Any]) -> None:
        self._cov = cov

    def _compute_current_dd(self, current_equity: float) -> float:
        hwm = self.kill_switch.hwm
        if hwm <= 0 or not np.isfinite(hwm):
            return 1.0
        return max(0.0, (hwm - current_equity) / hwm)

    def evaluate(
        self,
        portfolio_state: dict[str, Any],
        proposed_positions: dict[str, float],
        prices: dict[str, float],
        current_equity: float,
        timestamp: str = "",
    ) -> RiskDecision:
        if self.kill_switch.check_trip(current_equity):
            self.kill_switch.update(current_equity)
            decision = RiskDecision(
                action=RiskDecisionAction.halt,
                reason=self.kill_switch.trip_reason,
                max_pos_size=0.0,
                max_leverage=0.0,
                max_notional=0.0,
                current_dd=self._compute_current_dd(current_equity),
                current_heat=None,
                hwm=self.kill_switch.hwm,
                timestamp=timestamp,
                symbol=",".join(sorted(proposed_positions.keys())),
            )
            self._decisions.append(decision)
            return decision

        if not proposed_positions or not prices:
            decision = RiskDecision(
                action=RiskDecisionAction.proceed,
                reason="no positions",
                max_pos_size=0.0,
                max_leverage=self.config.max_leverage,
                max_notional=current_equity * self.config.max_leverage,
                current_dd=self._compute_current_dd(current_equity),
                current_heat=None,
                hwm=self.kill_switch.hwm,
                timestamp=timestamp,
                symbol="",
            )
            self._decisions.append(decision)
            return decision

        equity = current_equity
        gross_notional = sum(
            abs(pos * prices.get(sym, 0.0)) for sym, pos in proposed_positions.items()
        )
        gross_leverage = gross_notional / equity if equity > 0 else 0.0

        max_notional = equity * self.config.max_leverage

        if gross_leverage > self.config.max_leverage:
            scale = self.config.max_leverage / gross_leverage
            reduced_positions = {sym: pos * scale for sym, pos in proposed_positions.items()}
            decision = RiskDecision(
                action=RiskDecisionAction.reduce,
                reason=f"leverage {gross_leverage:.4f} exceeds max {self.config.max_leverage}",
                max_pos_size=0.0,
                max_leverage=self.config.max_leverage,
                max_notional=max_notional,
                current_dd=self._compute_current_dd(current_equity),
                current_heat=None,
                hwm=self.kill_switch.hwm,
                timestamp=timestamp,
                symbol=",".join(sorted(reduced_positions.keys())),
            )
            self._decisions.append(decision)
            return decision

        for sym, pos in proposed_positions.items():
            pos_value = abs(pos * prices.get(sym, 0.0))
            pos_pct = pos_value / equity if equity > 0 else 0.0
            if pos_pct > self.config.max_position_pct:
                max_units = (self.config.max_position_pct * equity) / prices.get(sym, 1.0)
                clipped_pos = max_units if pos > 0 else -max_units
                proposed_positions = proposed_positions.copy()
                proposed_positions[sym] = clipped_pos
                decision = RiskDecision(
                    action=RiskDecisionAction.reduce,
                    reason=(
                        f"position {sym} {pos_pct:.4f} of equity "
                        f"exceeds max {self.config.max_position_pct}"
                    ),
                    max_pos_size=max_units,
                    max_leverage=self.config.max_leverage,
                    max_notional=max_notional,
                    current_dd=self._compute_current_dd(current_equity),
                    current_heat=None,
                    hwm=self.kill_switch.hwm,
                    timestamp=timestamp,
                    symbol=sym,
                )
                self._decisions.append(decision)
                return decision

        if self._cov is not None and len(proposed_positions) > 1:
            symbols = sorted(proposed_positions.keys())
            pos_values = [abs(proposed_positions[s] * prices.get(s, 0.0)) for s in symbols]
            total_abs = sum(pos_values)
            if total_abs > 0:
                weights = np.array([v / total_abs for v in pos_values])
                port_heat = compute_heat(weights, self._cov)
                passed, msg = heat_cap_check(port_heat, self.config.max_heat)
                if not passed:
                    decision = RiskDecision(
                        action=RiskDecisionAction.reduce,
                        reason=msg,
                        max_pos_size=0.0,
                        max_leverage=self.config.max_leverage,
                        max_notional=max_notional,
                        current_dd=self._compute_current_dd(current_equity),
                        current_heat=port_heat,
                        hwm=self.kill_switch.hwm,
                        timestamp=timestamp,
                        symbol=",".join(symbols),
                    )
                    self._decisions.append(decision)
                    return decision
                current_heat = port_heat
            else:
                current_heat = None
        else:
            current_heat = None

        current_dd = self._compute_current_dd(current_equity)
        scalar = dd_budget_scalar(
            current_dd,
            self.config.max_portfolio_dd,
            self.config.dd_budget_scalar_power,
        )

        decision = RiskDecision(
            action=RiskDecisionAction.proceed,
            reason=f"dd_budget_scalar={scalar:.4f}" if scalar < 1.0 else "",
            max_pos_size=0.0,
            max_leverage=self.config.max_leverage,
            max_notional=max_notional * scalar,
            current_dd=current_dd,
            current_heat=current_heat,
            hwm=self.kill_switch.hwm,
            timestamp=timestamp,
            symbol=",".join(sorted(proposed_positions.keys())),
        )
        self._decisions.append(decision)
        return decision

    def cooldown_tick(self) -> None:
        self.kill_switch.cooldown_tick()

    def reset_kill_switch(self, current_equity: float) -> None:
        self.kill_switch.reset(current_equity)
