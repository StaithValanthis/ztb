from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pandas import DataFrame, Series

from ztb.engine.metrics import MetricsResult, compute_metrics

if TYPE_CHECKING:
    from ztb.engine.ft_decay import DecayConfig
from ztb.engine.portfolio import PortfolioState, single_symbol_portfolio
from ztb.risk.manager import RiskManager
from ztb.risk.models import RiskConfig
from ztb.risk.portfolio import risk_adjusted_signals
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
    decay_score: float | None = None
    decay_alarm: tuple[bool, str] | None = None
    baseline_run_id: str | None = None
    risk_aware: bool = False
    risk_decisions: list[dict[str, Any]] = field(default_factory=list)
    kill_count: int = 0
    mean_gross_leverage: float | None = None
    max_portfolio_dd_realized: float | None = None


@dataclass
class ForwardtestConfig:
    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0005
    warmup_bars: int = 100
    min_trades: int = 5
    risk_enabled: bool = True
    risk_config: RiskConfig | None = None
    oos_start: int = 0


def run_forwardtest(
    strategy: Strategy,
    data: DataFrame,
    config: ForwardtestConfig | None = None,
    baseline_metrics: MetricsResult | None = None,
    decay_cfg: DecayConfig | None = None,
    baseline_run_id: str | None = None,
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
            sig = float(adj_signals.iloc[i])
            eq = adj_equity[i]
            if eq > 0 and abs(sig) > 0:
                total_gross_leverage += abs(sig)
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

    trailing_dd = portfolio.equity[:]
    peak = trailing_dd[0] if trailing_dd else 0.0
    max_dd_realized = 0.0
    for eq in trailing_dd:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd_realized:
            max_dd_realized = dd

    decay_score: float | None = None
    decay_alarm: tuple[bool, str] | None = None
    if baseline_metrics is not None:
        from ztb.engine.ft_decay import DecayConfig, check_decay_alarm, compute_decay_score

        if decay_cfg is None:
            decay_cfg = DecayConfig()
        decay_score = compute_decay_score(metrics, baseline_metrics)
        alarm = check_decay_alarm(metrics, baseline_metrics, len(forward_equity), decay_cfg)
        decay_alarm = alarm

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
        decay_score=decay_score,
        decay_alarm=decay_alarm,
        baseline_run_id=baseline_run_id,
        risk_aware=config.risk_enabled,
        risk_decisions=risk_decisions,
        kill_count=kill_count,
        mean_gross_leverage=(
            total_gross_leverage / leverage_samples if leverage_samples > 0 else None
        ),
        max_portfolio_dd_realized=max_dd_realized,
    )


def _trade_idx(trade: dict[str, Any], timestamps: list[Any]) -> int:
    ts = trade["timestamp"]
    for i, t in enumerate(timestamps):
        if t == ts:
            return i
    return len(timestamps)
