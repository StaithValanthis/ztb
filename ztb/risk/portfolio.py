from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pandas import Series

from ztb.risk.dd_budget import dd_budget_scalar
from ztb.risk.manager import RiskManager
from ztb.risk.models import RiskDecisionAction


@dataclass
class MultiSymbolPortfolioState:
    cash: float
    positions: dict[str, float]
    equity: list[float] = field(default_factory=list)
    timestamps: list[pd.Timestamp] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    multi_symbol: bool = True


def risk_adjusted_signals(
    signals: Series,
    close: Series,
    risk_manager: RiskManager,
    initial_cash: float = 100_000.0,
    commission: float = 0.0005,
    slippage: float = 0.0005,
) -> tuple[Series, list[dict[str, Any]], list[float]]:
    cash = initial_cash
    pos = 0.0
    decisions: list[dict[str, Any]] = []
    adjusted: list[float] = []
    equity_values: list[float] = []

    for i, idx in enumerate(signals.index):
        price = float(close.iloc[i])
        target = float(signals.iloc[i])
        current_equity = cash + pos * price
        equity_values.append(current_equity)

        if i == 0:
            risk_manager.kill_switch.update(current_equity)

        portfolio_state: dict[str, Any] = {
            "cash": cash,
            "positions": {"_": pos},
        }
        proposed = {"_": target}
        prices = {"_": price}

        decision = risk_manager.evaluate(
            portfolio_state, proposed, prices, current_equity, timestamp=str(idx)
        )

        if decision.action == RiskDecisionAction.halt:
            target = 0.0

        current_dd = risk_manager._compute_current_dd(current_equity)
        scalar = 1.0
        if current_dd > 0.0:
            scalar = dd_budget_scalar(
                current_dd,
                risk_manager.config.max_portfolio_dd,
                risk_manager.config.dd_budget_scalar_power,
            )

        final_target = target * scalar

        decisions.append(
            {
                "action": decision.action.value,
                "reason": decision.reason,
                "timestamp": str(idx),
                "symbol": "_",
                "max_pos_size": decision.max_pos_size,
                "max_leverage": decision.max_leverage,
                "max_notional": decision.max_notional,
                "current_dd": decision.current_dd,
                "current_heat": decision.current_heat,
                "hwm": decision.hwm,
            }
        )

        delta = final_target - pos
        if abs(delta) > 1e-12:
            if delta > 0:
                cash -= delta * price * (1 + commission + slippage)
            else:
                cash += abs(delta) * price * (1 - commission - slippage)
            pos = final_target

        adjusted.append(pos)

        if i == 0:
            risk_manager.update_portfolio_equity(current_equity)
        else:
            new_equity = cash + pos * price
            risk_manager.update_portfolio_equity(new_equity)
        risk_manager.cooldown_tick()

    return Series(adjusted, index=signals.index), decisions, equity_values


def multi_symbol_portfolio(
    signals: dict[str, Series],
    closes: dict[str, Series],
    initial_cash: float = 100_000.0,
    commission: float = 0.0005,
    slippage: float = 0.0005,
) -> MultiSymbolPortfolioState:
    symbols = sorted(signals.keys())
    if not symbols:
        return MultiSymbolPortfolioState(cash=initial_cash, positions={})

    index = signals[symbols[0]].index
    cash = initial_cash
    positions: dict[str, float] = {sym: 0.0 for sym in symbols}
    avg_prices: dict[str, float] = {sym: 0.0 for sym in symbols}
    trades: list[dict[str, Any]] = []
    equity: list[float] = []
    timestamps: list[pd.Timestamp] = []

    for i, idx in enumerate(index):
        for sym in symbols:
            price = float(closes[sym].iloc[i])
            target = float(signals[sym].iloc[i])
            pos = positions[sym]
            avg_price = avg_prices[sym]

            pnl = 0.0

            if i == 0:
                if abs(target) > 0:
                    avg_prices[sym] = price
                positions[sym] = target
            elif abs(target - pos) > 1e-12:
                delta = target - pos

                if pos > 0:
                    if target > 0:
                        if delta > 0:
                            avg_prices[sym] = (avg_price * pos + delta * price) / target
                        else:
                            pnl = (price - avg_price) * abs(delta)
                    else:
                        pnl = (price - avg_price) * pos
                        avg_prices[sym] = price if target < 0 else 0.0
                elif pos < 0:
                    if target < 0:
                        if delta < 0:
                            avg_prices[sym] = (avg_price * abs(pos) + abs(delta) * price) / abs(
                                target
                            )
                        else:
                            pnl = (avg_price - price) * abs(delta)
                    else:
                        pnl = (avg_price - price) * abs(pos)
                        avg_prices[sym] = price if target > 0 else 0.0
                else:
                    avg_prices[sym] = price

                costs = abs(delta) * price * (commission + slippage)
                net_pnl = pnl - costs

                if abs(delta) > 0:
                    if delta > 0:
                        cash -= delta * price * (1 + commission + slippage)
                    else:
                        cash += abs(delta) * price * (1 - commission - slippage)

                trades.append(
                    {
                        "timestamp": idx,
                        "symbol": sym,
                        "side": "buy" if delta > 0 else "sell",
                        "price": price,
                        "size": abs(delta),
                        "pnl": net_pnl,
                        "commission": abs(delta) * price * commission,
                        "slippage": abs(delta) * price * slippage,
                    }
                )

                positions[sym] = target

        total_equity = cash + sum(positions[sym] * float(closes[sym].iloc[i]) for sym in symbols)
        equity.append(total_equity)
        timestamps.append(idx)

    return MultiSymbolPortfolioState(
        cash=cash,
        positions=positions,
        equity=equity,
        timestamps=timestamps,
        trades=trades,
    )
