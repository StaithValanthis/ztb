from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pandas import DataFrame, Series

from ztb.engine.metrics import MetricsResult, compute_metrics
from ztb.engine.portfolio import PortfolioState, single_symbol_portfolio
from ztb.strategies.base import Strategy, StrategyError


@dataclass
class ForwardtestResult:
    strategy_name: str
    symbol: str
    timeframe: str
    metrics: MetricsResult
    portfolio: PortfolioState
    trades: list[dict[str, Any]]
    parameters: dict[str, Any] = field(default_factory=dict)
    warmup_bars: int = 0
    total_bars: int = 0


@dataclass
class ForwardtestConfig:
    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0005
    warmup_bars: int = 100
    min_trades: int = 5


def run_forwardtest(
    strategy: Strategy,
    data: DataFrame,
    config: ForwardtestConfig | None = None,
) -> ForwardtestResult:
    if config is None:
        config = ForwardtestConfig()

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

    if signals.isna().any():
        raise StrategyError("Signals contain NaN values")

    if signals.abs().max() > 1.0 + 1e-10:
        raise StrategyError(f"Signals exceed [-1, 1] range: max abs {signals.abs().max()}")

    clipped = signals.clip(-1.0, 1.0)
    shifted = clipped.shift(1, fill_value=0.0)
    shifted.iloc[: strategy.warmup] = 0.0

    portfolio = single_symbol_portfolio(
        signals=shifted,
        close=close,
        initial_cash=config.initial_cash,
        commission=config.commission,
        slippage=config.slippage,
    )

    warmup = max(strategy.warmup, config.warmup_bars)
    if warmup >= len(data):
        warmup = len(data) // 2

    forward_trades = [t for t in portfolio.trades if _trade_idx(t, portfolio.timestamps) >= warmup]
    forward_equity = Series(
        portfolio.equity[warmup:],
        index=portfolio.timestamps[warmup:],
    )

    metrics = compute_metrics(
        forward_equity,
        forward_trades,
        timeframe=strategy.timeframe,
        min_trades=config.min_trades,
    )

    return ForwardtestResult(
        strategy_name=strategy.name,
        symbol=strategy.symbols[0] if strategy.symbols else "",
        timeframe=strategy.timeframe,
        metrics=metrics,
        portfolio=portfolio,
        trades=forward_trades,
        parameters=dict(strategy.params),
        warmup_bars=warmup,
        total_bars=len(data),
    )


def _trade_idx(trade: dict[str, Any], timestamps: list[Any]) -> int:
    ts = trade["timestamp"]
    for i, t in enumerate(timestamps):
        if t == ts:
            return i
    return len(timestamps)
