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


def risk_based_target_qty(
    equity: float,
    entry_price: float,
    sl_pct: float,
    risk_per_trade_pct: float,
    min_qty: float = 0.0,
) -> float:
    if sl_pct <= 0.0 or risk_per_trade_pct <= 0.0 or entry_price <= 0.0 or equity <= 0.0:
        return 0.0
    risk_amount = equity * risk_per_trade_pct
    target_qty = risk_amount / (entry_price * sl_pct)
    if min_qty > 0.0 and target_qty < min_qty:
        return 0.0
    return target_qty


def single_symbol_portfolio(
    signals: Series,
    close: Series,
    high: Series | None = None,
    low: Series | None = None,
    initial_cash: float = 100_000.0,
    commission: float = 0.0005,
    slippage: float = 0.0005,
    sl_pct: float = 0.0,
    tp_pct: float = 0.0,
) -> PortfolioState:
    pnl = PnLCalculator(initial_cash=initial_cash)
    trades: list[dict[str, Any]] = []
    equity: list[float] = []
    timestamps: list[pd.Timestamp] = []
    open_trade_sl_price: float | None = None
    open_trade_tp_price: float | None = None
    open_trade_qty: float = 0.0

    for i, idx in enumerate(signals.index):
        price = float(close.iloc[i])
        target_frac = float(signals.iloc[i])
        current_equity = pnl.equity(price)
        target_qty = target_frac * current_equity / price if price > 0 else 0.0
        delta = target_qty - pnl.position

        sl_hit = False
        tp_hit = False
        sl_tp_exit_reason: str | None = None

        if open_trade_sl_price is not None or open_trade_tp_price is not None:
            bar_high = float(high.iloc[i]) if high is not None else price
            bar_low = float(low.iloc[i]) if low is not None else price
            if open_trade_sl_price is not None and bar_low <= open_trade_sl_price:
                sl_hit = True
                sl_tp_exit_reason = "stop_loss"
                exit_price = open_trade_sl_price
            elif open_trade_tp_price is not None and bar_high >= open_trade_tp_price:
                tp_hit = True
                sl_tp_exit_reason = "take_profit"
                exit_price = open_trade_tp_price

            if sl_hit or tp_hit:
                close_delta = -open_trade_qty
                realized_before = pnl.realized_pnl
                comm_cost = abs(close_delta) * exit_price * commission
                slip_cost = abs(close_delta) * exit_price * slippage
                pnl.apply_fill(close_delta, exit_price, commission=comm_cost, slippage=slip_cost)
                trade_pnl = pnl.realized_pnl - realized_before
                trades.append(
                    {
                        "timestamp": idx,
                        "side": "sell" if open_trade_qty > 0 else "buy",
                        "price": exit_price,
                        "size": abs(close_delta),
                        "pnl": trade_pnl,
                        "commission": comm_cost,
                        "slippage": slip_cost,
                        "sl_price": open_trade_sl_price,
                        "tp_price": open_trade_tp_price,
                        "exit_reason": sl_tp_exit_reason,
                    }
                )
                open_trade_sl_price = None
                open_trade_tp_price = None
                open_trade_qty = 0.0
                target_qty = 0.0
                target_frac = 0.0
                delta = -pnl.position

        if abs(delta) > 1e-12:
            realized_before = pnl.realized_pnl
            old_pos = pnl.position
            comm_cost = abs(delta) * price * commission
            slip_cost = abs(delta) * price * slippage
            pnl.apply_fill(delta, price, commission=comm_cost, slippage=slip_cost)
            trade_pnl = pnl.realized_pnl - realized_before
            trade_entry = {
                "timestamp": idx,
                "side": "buy" if delta > 0 else "sell",
                "price": price,
                "size": abs(delta),
                "pnl": trade_pnl,
                "commission": comm_cost,
                "slippage": slip_cost,
            }
            if abs(old_pos) < 1e-12 and abs(delta) > 1e-12 and (sl_pct > 0.0 or tp_pct > 0.0):
                if delta > 0:
                    trade_entry["sl_price"] = price * (1.0 - sl_pct) if sl_pct > 0.0 else None
                    trade_entry["tp_price"] = price * (1.0 + tp_pct) if tp_pct > 0.0 else None
                else:
                    trade_entry["sl_price"] = price * (1.0 + sl_pct) if sl_pct > 0.0 else None
                    trade_entry["tp_price"] = price * (1.0 - tp_pct) if tp_pct > 0.0 else None
                trade_entry["exit_reason"] = "signal"
                open_trade_sl_price = trade_entry["sl_price"]
                open_trade_tp_price = trade_entry["tp_price"]
                open_trade_qty = delta if delta > 0 else -delta
            if abs(pnl.position) < 1e-12 and not sl_hit and not tp_hit:
                open_trade_sl_price = None
                open_trade_tp_price = None
                open_trade_qty = 0.0
            trades.append(trade_entry)

        equity.append(pnl.equity(price))
        timestamps.append(idx)

    cash = equity[-1] - pnl.position * float(close.iloc[-1]) if len(equity) > 0 else initial_cash
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
