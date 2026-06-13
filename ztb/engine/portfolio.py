from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pandas import Series

from ztb.engine.pnl import PnLCalculator


@dataclass
class PortfolioState:
    cash: float
    position: float
    positions: dict[str, float] = field(default_factory=dict)
    equity: list[float] = field(default_factory=list)
    timestamps: list[pd.Timestamp] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)


def single_symbol_portfolio(
    signals: Series,
    close: Series,
    initial_cash: float = 100_000.0,
    commission: float = 0.0005,
    slippage: float = 0.0005,
) -> PortfolioState:
    pnl = PnLCalculator(initial_cash=initial_cash)
    trades: list[dict[str, Any]] = []
    equity: list[float] = []
    timestamps: list[pd.Timestamp] = []

    for i, idx in enumerate(signals.index):
        price = float(close.iloc[i])
        target_frac = float(signals.iloc[i])
        current_equity = pnl.equity(price)
        target_qty = target_frac * current_equity / price if price > 0 else 0.0
        delta = target_qty - pnl.position

        if abs(delta) > 1e-12:
            if i == 0:
                pnl.apply_fill(delta, price)
            else:
                realized_before = pnl.realized_pnl
                comm_cost = abs(delta) * price * commission
                slip_cost = abs(delta) * price * slippage
                pnl.apply_fill(delta, price, commission=comm_cost, slippage=slip_cost)
                trade_pnl = pnl.realized_pnl - realized_before
                trades.append(
                    {
                        "timestamp": idx,
                        "side": "buy" if delta > 0 else "sell",
                        "price": price,
                        "size": abs(delta),
                        "pnl": trade_pnl,
                        "commission": comm_cost,
                        "slippage": slip_cost,
                    }
                )

        equity.append(pnl.equity(price))
        timestamps.append(idx)

    cash = (
        equity[-1] - abs(pnl.position) * float(close.iloc[-1]) if len(equity) > 0 else initial_cash
    )
    return PortfolioState(
        cash=cash,
        position=pnl.position,
        positions={"": pnl.position},
        equity=equity,
        timestamps=timestamps,
        trades=trades,
    )


def multi_symbol_portfolio(
    signals: dict[str, Series],
    closes: dict[str, Series],
    initial_cash: float = 100_000.0,
    commission: float = 0.0005,
    slippage: float = 0.0005,
) -> PortfolioState:
    symbols = sorted(signals.keys())
    if not symbols:
        return PortfolioState(cash=initial_cash, position=0.0, positions={})

    index = signals[symbols[0]].index
    pnl_calculators: dict[str, PnLCalculator] = {
        sym: PnLCalculator(initial_cash=initial_cash / len(symbols)) for sym in symbols
    }
    trades: list[dict[str, Any]] = []
    equity_list: list[float] = []
    timestamps: list[pd.Timestamp] = []

    for i, idx in enumerate(index):
        pre_trade_equity = sum(
            pnl_calculators[sym].equity(float(closes[sym].iloc[i])) for sym in symbols
        )
        total_equity = 0.0
        for sym in symbols:
            price = float(closes[sym].iloc[i])
            target_frac = float(signals[sym].iloc[i])
            calc = pnl_calculators[sym]
            target_qty = target_frac * pre_trade_equity / price if price > 0 else 0.0
            delta = target_qty - calc.position

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
    total_position = sum(abs(v) for v in positions.values())
    return PortfolioState(
        cash=initial_cash,
        position=total_position * (1 if any(v > 0 for v in positions.values()) else -1),
        positions=positions,
        equity=equity_list,
        timestamps=timestamps,
        trades=trades,
    )
