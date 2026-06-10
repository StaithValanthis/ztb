from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pandas import DataFrame, Series

from ztb.engine.metrics import MetricsResult, compute_metrics
from ztb.engine.portfolio import PortfolioState, single_symbol_portfolio
from ztb.risk.manager import RiskManager
from ztb.risk.models import RiskConfig
from ztb.risk.portfolio import risk_adjusted_signals
from ztb.strategies.base import Strategy, StrategyError


@dataclass
class BacktestResult:
    strategy_name: str
    symbol: str
    timeframe: str
    full: MetricsResult
    is_: MetricsResult
    oos: MetricsResult
    portfolio: PortfolioState
    trades: list[dict[str, Any]]
    splits: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)
    risk_aware: bool = False
    risk_decisions: list[dict[str, Any]] = field(default_factory=list)
    kill_count: int = 0
    mean_gross_leverage: float | None = None
    max_portfolio_dd_realized: float | None = None


@dataclass
class BacktestConfig:
    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0005
    is_fraction: float = 0.7
    min_bars: int = 100
    min_trades: int = 30
    risk_enabled: bool = False
    risk_config: RiskConfig | None = None


def run_backtest(
    strategy: Strategy,
    data: DataFrame,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    if config is None:
        config = BacktestConfig()

    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    close = data["close"]

    signals = strategy.generate_signals(data)

    if len(signals) != len(data):
        raise ValueError(f"Signal length {len(signals)} != data length {len(data)}")

    if signals.index.dtype != data.index.dtype or not signals.index.equals(data.index):
        raise ValueError("Signal index does not match data index")

    if signals.iloc[: strategy.warmup].abs().max() > 1e-10:
        raise StrategyError(
            f"Strategy '{strategy.name}' emitted non-zero signals "
            f"within warmup period ({strategy.warmup})"
        )

    if signals.isna().any():
        raise StrategyError("Signals contain NaN values")

    if signals.abs().max() > 1.0 + 1e-10:
        raise StrategyError(f"Signals exceed [-1, 1] range: max abs {signals.abs().max()}")

    clipped = signals.clip(-1.0, 1.0)
    shifted = clipped.shift(1, fill_value=0.0)
    shifted.iloc[: strategy.warmup] = 0.0

    if config.risk_enabled:
        risk_mgr = RiskManager(config=config.risk_config)
        adj_signals, risk_decisions, adj_equity = risk_adjusted_signals(
            shifted,
            close,
            risk_mgr,
            initial_cash=config.initial_cash,
            commission=config.commission,
            slippage=config.slippage,
        )
        kill_count = sum(1 for d in risk_decisions if d["action"] == "halt")
        total_gross_leverage = 0.0
        leverage_samples = 0
        for i, _idx in enumerate(adj_signals.index):
            price = float(close.iloc[i])
            sig = float(adj_signals.iloc[i])
            eq = adj_equity[i]
            if eq > 0 and abs(sig) * price > 0:
                total_gross_leverage += abs(sig) * price / eq
                leverage_samples += 1
        shifted = adj_signals
    else:
        risk_decisions = []
        kill_count = 0
        total_gross_leverage = 0.0
        leverage_samples = 0

    portfolio = single_symbol_portfolio(
        signals=shifted,
        close=close,
        initial_cash=config.initial_cash,
        commission=config.commission,
        slippage=config.slippage,
    )

    equity_series = Series(portfolio.equity, index=portfolio.timestamps)

    trades = portfolio.trades

    full_metrics = compute_metrics(
        equity_series,
        trades,
        timeframe=strategy.timeframe,
        min_trades=config.min_trades,
    )

    split_idx = int(len(data) * config.is_fraction)
    if split_idx < config.min_bars:
        split_idx = len(data) // 2

    is_trades = [t for t in trades if t["timestamp"] < portfolio.timestamps[split_idx]]
    oos_trades = [t for t in trades if t["timestamp"] >= portfolio.timestamps[split_idx]]

    is_equity = equity_series.iloc[: split_idx + 1]
    is_metrics = compute_metrics(
        is_equity,
        is_trades,
        timeframe=strategy.timeframe,
        min_trades=config.min_trades,
    )

    oos_equity = equity_series.iloc[split_idx:]
    oos_metrics = compute_metrics(
        oos_equity,
        oos_trades,
        timeframe=strategy.timeframe,
        min_trades=config.min_trades,
    )

    trailing_dd = portfolio.equity[:]
    peak = trailing_dd[0] if trailing_dd else 0.0
    max_dd_realized = 0.0
    for eq in trailing_dd:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd_realized:
            max_dd_realized = dd

    return BacktestResult(
        strategy_name=strategy.name,
        symbol=strategy.symbols[0] if strategy.symbols else "",
        timeframe=strategy.timeframe,
        full=full_metrics,
        is_=is_metrics,
        oos=oos_metrics,
        portfolio=portfolio,
        trades=trades,
        splits={"is_end": split_idx, "n_bars": len(data)},
        parameters=dict(strategy.params),
        risk_aware=config.risk_enabled,
        risk_decisions=risk_decisions,
        kill_count=kill_count,
        mean_gross_leverage=(
            total_gross_leverage / leverage_samples if leverage_samples > 0 else None
        ),
        max_portfolio_dd_realized=max_dd_realized,
    )
