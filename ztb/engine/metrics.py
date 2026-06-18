from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from pandas import Series

PERIODS_PER_YEAR: dict[str, float] = {
    "1": 365 * 24 * 60,
    "5": 365 * 24 * 12,
    "15": 365 * 24 * 4,
    "60": 365 * 24,
    "D": 365,
    "W": 52,
    "M": 12,
}

_MINUTES_PER_YEAR = 365.0 * 24.0 * 60.0


def resolve_periods_per_year(timeframe: str) -> float:
    """Periods/year for Sharpe/Sortino annualization.

    Named timeframes use the table above; a NUMERIC timeframe (minutes per bar,
    e.g. "240" = 4h, "30", "120") is derived EXACTLY rather than silently
    defaulting to hourly (8760). That old default mis-annualized every timeframe
    not in the table — 4h Sharpe came out ~2x too high, making the validation
    edge gate too lenient (false positives). Unknown/garbage falls back to hourly.
    """
    if timeframe in PERIODS_PER_YEAR:
        return PERIODS_PER_YEAR[timeframe]
    try:
        minutes = int(timeframe)
    except (TypeError, ValueError):
        return 365.0 * 24.0
    return _MINUTES_PER_YEAR / minutes if minutes > 0 else 365.0 * 24.0


@dataclass
class MetricsResult:
    total_return: float | None
    sharpe: float | None
    sortino: float | None
    max_drawdown: float | None
    max_drawdown_duration: int | None
    num_trades: int
    profit_factor: float | None
    win_rate: float | None
    turnover: float
    exposure_time: float
    sufficient_sample: bool
    reason: str = ""


def compute_metrics(
    equity: Series,
    trades: list[dict[str, Any]],
    timeframe: str = "60",
    periods_per_year: float | None = None,
    min_trades: int = 30,
) -> MetricsResult:
    ppy = resolve_periods_per_year(timeframe) if periods_per_year is None else periods_per_year

    n_trades = len(trades)

    if n_trades < min_trades or len(equity) < 2:
        if n_trades == 0 and len(equity) < 2:
            reason = "insufficient data: no trades and < 2 equity points"
        elif n_trades < min_trades:
            reason = f"insufficient data: {n_trades} trades < {min_trades} minimum"
        else:
            reason = f"insufficient data: {len(equity)} equity points < 2"
        return MetricsResult(
            total_return=None,
            sharpe=None,
            sortino=None,
            max_drawdown=None,
            max_drawdown_duration=None,
            num_trades=n_trades,
            profit_factor=None,
            win_rate=None,
            turnover=0.0,
            exposure_time=0.0,
            sufficient_sample=False,
            reason=reason,
        )

    returns = equity.pct_change().dropna()
    if len(returns) == 0:
        return MetricsResult(
            total_return=None,
            sharpe=None,
            sortino=None,
            max_drawdown=None,
            max_drawdown_duration=None,
            num_trades=n_trades,
            profit_factor=None,
            win_rate=None,
            turnover=0.0,
            exposure_time=0.0,
            sufficient_sample=False,
            reason="zero returns after equity pct_change",
        )

    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)

    mean_ret = float(returns.mean())
    std_ret = float(returns.std())

    sharpe: float | None = 0.0 if std_ret == 0.0 else float((mean_ret / std_ret) * np.sqrt(ppy))

    downside = returns[returns < 0]
    downside_std = float(downside.std()) if len(downside) > 1 else 0.0
    if downside_std == 0.0:
        sortino: float | None = 0.0
    else:
        sortino = float((mean_ret / downside_std) * np.sqrt(ppy))

    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    dd = (cumulative - running_max) / running_max
    max_dd = float(dd.min())

    dd_series = dd
    in_dd = dd_series < 0
    durations: list[int] = []
    current = 0
    for val in in_dd:
        if val:
            current += 1
        else:
            if current > 0:
                durations.append(current)
            current = 0
    if current > 0:
        durations.append(current)
    max_dd_duration = max(durations) if durations else 0

    gross_pnl = 0.0
    gross_loss = 0.0
    wins = 0
    for t in trades:
        pnl = t.get("pnl", 0.0)
        if pnl > 0:
            gross_pnl += pnl
            wins += 1
        elif pnl < 0:
            gross_loss += abs(pnl)

    profit_factor: float | None
    if gross_loss == 0.0:
        profit_factor = gross_pnl / 1.0 if gross_pnl > 0 else None
    else:
        profit_factor = gross_pnl / gross_loss

    win_rate = float(wins / n_trades) if n_trades > 0 else None

    turnover = float(sum(abs(t.get("size", 0.0)) for t in trades))

    exposure = float(len(returns))

    return MetricsResult(
        total_return=total_return,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd,
        max_drawdown_duration=max_dd_duration,
        num_trades=n_trades,
        profit_factor=profit_factor,
        win_rate=win_rate,
        turnover=turnover,
        exposure_time=exposure,
        sufficient_sample=True,
    )
