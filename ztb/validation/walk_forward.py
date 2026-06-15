from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from pandas import DataFrame, Series

from ztb.engine.backtest import BacktestConfig, run_backtest
from ztb.engine.metrics import MetricsResult, compute_metrics
from ztb.strategies.base import Strategy


@dataclass
class WalkForwardConfig:
    n_windows: int = 4
    train_ratio: float = 0.7
    step_size: int | None = None
    min_train_bars: int = 500
    min_oos_bars: int = 100
    warmup: int | None = None
    min_trades: int = 30
    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0005


@dataclass
class WalkForwardResult:
    per_window: list[MetricsResult]
    aggregate: MetricsResult
    stability: float | None
    n_windows_credible: int
    n_windows_total: int
    config: WalkForwardConfig


def run_walk_forward(
    strategy: Strategy,
    data: DataFrame,
    config: WalkForwardConfig | None = None,
) -> WalkForwardResult:
    if config is None:
        config = WalkForwardConfig()

    n = len(data)
    step = n // (config.n_windows + 1) if config.step_size is None else config.step_size

    window_results: list[MetricsResult] = []
    credible_count = 0

    for i in range(config.n_windows):
        start = i * step
        end = start + (n - start) // 1
        if i < config.n_windows - 1:
            remaining = config.n_windows - i
            end = start + (n - start) // remaining if remaining > 0 else n
            end = min(start + (n - start), n)
        else:
            end = n

        window_data = data.iloc[start:end].copy()
        window_len = len(window_data)

        train_end = start + int(window_len * config.train_ratio)
        if train_end <= start + config.min_train_bars:
            train_end = start + config.min_train_bars
        if train_end >= end - config.min_oos_bars:
            train_end = end - config.min_oos_bars
        if train_end <= start:
            train_end = start + 1

        oos_start = train_end
        if end - oos_start < config.min_oos_bars:
            oos_start = end - config.min_oos_bars
        if oos_start <= start:
            oos_start = start + 1

        bt_config = BacktestConfig(
            initial_cash=config.initial_cash,
            commission=config.commission,
            slippage=config.slippage,
            is_fraction=(train_end - start) / max(window_len, 1),
            min_trades=config.min_trades,
        )
        bt_results = run_backtest(strategy, window_data, bt_config)

        oos_equity_series: Series | None = None
        oos_start_idx = max(0, oos_start - start)
        if bt_results.portfolio.timestamps and len(bt_results.portfolio.equity) > oos_start_idx:
            oos_timestamps = bt_results.portfolio.timestamps[oos_start_idx:]
            oos_equity_values = bt_results.portfolio.equity[oos_start_idx:]
            oos_equity_series = Series(oos_equity_values, index=oos_timestamps)

        if oos_equity_series is not None and len(oos_equity_series) > 1:
            oos_trades: list[dict[str, Any]] = []
            if bt_results.trades:
                oos_start_ts = (
                    bt_results.portfolio.timestamps[oos_start_idx]
                    if oos_start_idx < len(bt_results.portfolio.timestamps)
                    else None
                )
                if oos_start_ts is not None:
                    oos_trades = [
                        t
                        for t in bt_results.trades
                        if str(t.get("timestamp", "")) >= str(oos_start_ts)
                    ]

            oos_metrics = compute_metrics(
                oos_equity_series,
                oos_trades,
                timeframe=strategy.timeframe,
                min_trades=config.min_trades,
            )
            window_results.append(oos_metrics)
            if oos_metrics.sufficient_sample:
                credible_count += 1

    if not window_results:
        empty_metrics = MetricsResult(
            total_return=None,
            sharpe=None,
            sortino=None,
            max_drawdown=None,
            max_drawdown_duration=None,
            num_trades=0,
            profit_factor=None,
            win_rate=None,
            turnover=0.0,
            exposure_time=0.0,
            sufficient_sample=False,
            reason="no windows produced valid OOS metrics",
        )
        return WalkForwardResult(
            per_window=[],
            aggregate=empty_metrics,
            stability=None,
            n_windows_credible=0,
            n_windows_total=config.n_windows,
            config=config,
        )

    def _median_of(attr: str) -> float | None:
        vals = [getattr(w, attr) for w in window_results if getattr(w, attr) is not None]
        return float(np.median(vals)) if vals else None

    total_return = _median_of("total_return")
    sharpe = _median_of("sharpe")
    sortino = _median_of("sortino")
    max_dd = _median_of("max_drawdown")
    profit_factor = _median_of("profit_factor")
    win_rate = _median_of("win_rate")
    num_trades = sum(w.num_trades for w in window_results)
    turnover = sum(w.turnover for w in window_results)
    exposure_time = sum(w.exposure_time for w in window_results)

    window_sharpes = [w.sharpe for w in window_results if w.sharpe is not None]

    stability: float | None = None
    if len(window_sharpes) >= 2:
        std_sharpe = float(np.std(window_sharpes, ddof=1))
        mean_sharpe = float(np.mean(window_sharpes))
        if abs(mean_sharpe) > 1e-10:
            stability = std_sharpe / abs(mean_sharpe)

    credits = sum(1 for w in window_results if w.sufficient_sample)
    sufficient_sample = credits >= 3 and stability is not None and stability <= 0.5

    max_dd_dur = (
        max((w.max_drawdown_duration or 0) for w in window_results) if window_results else 0
    )

    reason = (
        "aggregated across walk-forward windows"
        if sufficient_sample
        else "insufficient credible windows or stability too high"
    )

    aggregate = MetricsResult(
        total_return=total_return,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown=max_dd,
        max_drawdown_duration=max_dd_dur,
        num_trades=num_trades,
        profit_factor=profit_factor,
        win_rate=win_rate,
        turnover=turnover,
        exposure_time=exposure_time,
        sufficient_sample=sufficient_sample,
        reason=reason,
    )

    return WalkForwardResult(
        per_window=window_results,
        aggregate=aggregate,
        stability=stability,
        n_windows_credible=credits,
        n_windows_total=config.n_windows,
        config=config,
    )


def _safe_median(values: list[float]) -> float | None:
    if not values:
        return None
    return float(np.median(values))
