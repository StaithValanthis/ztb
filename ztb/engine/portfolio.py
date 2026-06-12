from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pandas import Series


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
    cash = initial_cash
    pos = 0.0
    avg_price = 0.0
    trades: list[dict[str, Any]] = []
    equity: list[float] = []
    timestamps: list[pd.Timestamp] = []

    for i, idx in enumerate(signals.index):
        price = float(close.iloc[i])
        target_frac = float(signals.iloc[i])

        equity_before = cash + pos * price
        target_qty = target_frac * equity_before / price if price > 0 else 0.0

        pnl = 0.0
        delta = target_qty - pos

        if i == 0 and abs(target_qty) > 0:
            avg_price = price
        elif abs(delta) > 1e-12:
            if pos > 0:
                if target_qty > 0:
                    if delta > 0:
                        avg_price = (avg_price * pos + delta * price) / target_qty
                    else:
                        pnl = (price - avg_price) * abs(delta)
                else:
                    pnl = (price - avg_price) * pos
                    avg_price = price if target_qty < 0 else 0.0
            elif pos < 0:
                if target_qty < 0:
                    if delta < 0:
                        avg_price = (avg_price * abs(pos) + abs(delta) * price) / abs(target_qty)
                    else:
                        pnl = (avg_price - price) * abs(delta)
                else:
                    pnl = (avg_price - price) * abs(pos)
                    avg_price = price if target_qty > 0 else 0.0
            else:
                avg_price = price

        if abs(delta) > 1e-12:
            costs = abs(delta) * price * (commission + slippage)
            net_pnl = pnl - costs

            if delta > 0:
                cash -= delta * price * (1 + commission + slippage)
            else:
                cash += abs(delta) * price * (1 - commission - slippage)

            trades.append(
                {
                    "timestamp": idx,
                    "side": "buy" if delta > 0 else "sell",
                    "price": price,
                    "size": abs(delta),
                    "pnl": net_pnl,
                    "commission": abs(delta) * price * commission,
                    "slippage": abs(delta) * price * slippage,
                }
            )

            pos = target_qty

        equity.append(cash + pos * price)
        timestamps.append(idx)

    return PortfolioState(
        cash=cash,
        position=pos,
        positions={"": pos},
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
    cash = initial_cash
    positions: dict[str, float] = {sym: 0.0 for sym in symbols}
    avg_prices: dict[str, float] = {sym: 0.0 for sym in symbols}
    trades: list[dict[str, Any]] = []
    equity: list[float] = []
    timestamps: list[pd.Timestamp] = []

    for i, idx in enumerate(index):
        pre_trade_equity = cash + sum(
            positions[sym] * float(closes[sym].iloc[i]) for sym in symbols
        )

        for sym in symbols:
            price = float(closes[sym].iloc[i])
            target_frac = float(signals[sym].iloc[i])
            target_qty = target_frac * pre_trade_equity / price if price > 0 else 0.0

            pos = positions[sym]
            avg_price = avg_prices[sym]

            pnl = 0.0
            delta = target_qty - pos

            if i == 0 and abs(target_qty) > 0:
                avg_prices[sym] = price
            elif abs(delta) > 1e-12:
                if pos > 0:
                    if target_qty > 0:
                        if delta > 0:
                            avg_prices[sym] = (avg_price * pos + delta * price) / target_qty
                        else:
                            pnl = (price - avg_price) * abs(delta)
                    else:
                        pnl = (price - avg_price) * pos
                        avg_prices[sym] = price if target_qty < 0 else 0.0
                elif pos < 0:
                    if target_qty < 0:
                        if delta < 0:
                            avg_prices[sym] = (avg_price * abs(pos) + abs(delta) * price) / abs(
                                target_qty
                            )
                        else:
                            pnl = (avg_price - price) * abs(delta)
                    else:
                        pnl = (avg_price - price) * abs(pos)
                        avg_prices[sym] = price if target_qty > 0 else 0.0
                else:
                    avg_prices[sym] = price

            if abs(delta) > 1e-12:
                costs = abs(delta) * price * (commission + slippage)
                net_pnl = pnl - costs

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

                positions[sym] = target_qty

        total_equity = cash + sum(positions[sym] * float(closes[sym].iloc[i]) for sym in symbols)
        equity.append(total_equity)
        timestamps.append(idx)

    total_position = sum(abs(v) for v in positions.values())
    return PortfolioState(
        cash=cash,
        position=total_position * (1 if any(v > 0 for v in positions.values()) else -1),
        positions=positions,
        equity=equity,
        timestamps=timestamps,
        trades=trades,
    )
