from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pandas import Series

from ztb.engine.pnl import PnLCalculator
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
    pnl = PnLCalculator(initial_cash=initial_cash)
    decisions: list[dict[str, Any]] = []
    adjusted: list[float] = []
    equity_values: list[float] = []

    for i, idx in enumerate(signals.index):
        price = float(close.iloc[i])
        target_frac = float(signals.iloc[i])
        current_equity = pnl.equity(price)
        equity_values.append(current_equity)

        if i == 0:
            risk_manager.kill_switch.update(current_equity)

        target_qty = target_frac * current_equity / price if price > 0 else 0.0

        portfolio_state: dict[str, Any] = {
            "cash": initial_cash,
            "positions": {"_": pnl.position},
        }
        proposed = {"_": target_qty}
        prices = {"_": price}

        decision = risk_manager.evaluate(
            portfolio_state, proposed, prices, current_equity, timestamp=str(idx)
        )

        if decision.action == RiskDecisionAction.halt:
            target_frac = 0.0

        current_dd = risk_manager._compute_current_dd(current_equity)
        scalar = 1.0
        if current_dd > 0.0:
            scalar = dd_budget_scalar(
                current_dd,
                risk_manager.config.max_portfolio_dd,
                risk_manager.config.dd_budget_scalar_power,
            )

        final_target_frac = target_frac * scalar
        final_target_qty = final_target_frac * current_equity / price if price > 0 else 0.0

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

        delta = final_target_qty - pnl.position
        if abs(delta) > 1e-12:
            if i == 0:
                pnl.apply_fill(delta, price)
            else:
                realized_before = pnl.realized_pnl
                comm_cost = abs(delta) * price * commission
                slip_cost = abs(delta) * price * slippage
                pnl.apply_fill(delta, price, commission=comm_cost, slippage=slip_cost)
                trade_pnl = pnl.realized_pnl - realized_before
                decisions[-1]["trade_pnl"] = trade_pnl

        adjusted.append(final_target_frac)

        if i == 0:
            risk_manager.update_portfolio_equity(current_equity)
        else:
            new_equity = pnl.equity(price)
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
    pnl_calculators: dict[str, PnLCalculator] = {
        sym: PnLCalculator(initial_cash=initial_cash / len(symbols)) for sym in symbols
    }
    trades: list[dict[str, Any]] = []
    equity_list: list[float] = []
    timestamps: list[pd.Timestamp] = []

    for i, idx in enumerate(index):
        total_equity = 0.0
        for sym in symbols:
            price = float(closes[sym].iloc[i])
            target = float(signals[sym].iloc[i])
            calc = pnl_calculators[sym]
            delta = target - calc.position

            if abs(delta) > 1e-12:
                if i == 0:
                    calc.apply_fill(delta, price)
                else:
                    realized_before = calc.realized_pnl
                    comm_cost = abs(delta) * price * commission
                    slip_cost = abs(delta) * price * slippage
                    calc.apply_fill(delta, price, commission=comm_cost, slippage=slip_cost)
                    trade_pnl = calc.realized_pnl - realized_before
                    trades.append(
                        {
                            "timestamp": idx,
                            "symbol": sym,
                            "side": "buy" if delta > 0 else "sell",
                            "price": price,
                            "size": abs(delta),
                            "pnl": trade_pnl,
                            "commission": comm_cost,
                            "slippage": slip_cost,
                        }
                    )

            total_equity += calc.equity(price)

        equity_list.append(total_equity)
        timestamps.append(idx)

    positions = {sym: calc.position for sym, calc in pnl_calculators.items()}
    return MultiSymbolPortfolioState(
        cash=initial_cash,
        positions=positions,
        equity=equity_list,
        timestamps=timestamps,
        trades=trades,
    )
