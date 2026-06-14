from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from pandas import DataFrame

from ztb.engine.backtest import BacktestConfig, BacktestResult, run_backtest
from ztb.strategies.base import Strategy


@dataclass
class WalkforwardWindow:
    window_idx: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_result: BacktestResult
    test_result: BacktestResult
    train_duration_bars: int = 0
    test_duration_bars: int = 0


@dataclass
class WalkforwardResult:
    strategy_name: str
    symbol: str
    timeframe: str
    windows: list[WalkforwardWindow]
    n_windows: int
    total_bars: int
    config: WalkforwardConfig
    avg_oos_sharpe: float | None = None
    avg_oos_return: float | None = None
    avg_oos_maxdd: float | None = None
    avg_oos_trades: float = 0.0
    sharpe_consistency: float = 0.0
    return_consistency: float = 0.0
    maxdd_consistency: float = 0.0
    all_windows_valid: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class WalkforwardConfig:
    n_windows: int = 4
    train_ratio: float = 0.7
    min_train_bars: int = 100
    min_test_bars: int = 30
    initial_cash: float = 100_000.0
    commission: float = 0.0005
    slippage: float = 0.0005
    min_trades: int = 5
    risk_enabled: bool = False


def _make_windows(n_bars: int, cfg: WalkforwardConfig) -> list[dict[str, int]]:
    windows: list[dict[str, int]] = []
    total_available = n_bars
    total_test_bars = total_available - int(total_available * cfg.train_ratio)
    test_per_window = total_test_bars // cfg.n_windows
    train_per_window = int(total_available * cfg.train_ratio) // cfg.n_windows

    for i in range(cfg.n_windows):
        train_end = int(total_available * cfg.train_ratio) + i * test_per_window
        train_start = i * train_per_window
        test_start = train_end
        test_end = test_start + test_per_window

        if i == cfg.n_windows - 1:
            test_end = n_bars

        train_duration = train_end - train_start
        test_duration = test_end - test_start

        if train_duration < cfg.min_train_bars or test_duration < cfg.min_test_bars:
            continue

        windows.append({
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
        })

    if len(windows) < cfg.n_windows:
        fallback_test = max(n_bars // (cfg.n_windows * 2), cfg.min_test_bars)
        fallback_train = max(n_bars - fallback_test, cfg.min_train_bars)
        return _fallback_windows(n_bars, cfg.n_windows, fallback_train, fallback_test)

    return windows


def _fallback_windows(
    n_bars: int, n_windows: int, train_size: int, test_size: int
) -> list[dict[str, int]]:
    windows: list[dict[str, int]] = []
    step = test_size
    for i in range(n_windows):
        test_start = min(train_size + i * step, n_bars - test_size)
        train_start = 0
        train_end = test_start
        test_end = test_start + test_size
        if test_end > n_bars:
            test_end = n_bars
        if test_end - test_start < 1:
            continue
        windows.append({
            "train_start": train_start,
            "train_end": train_end,
            "test_start": test_start,
            "test_end": test_end,
        })
    return windows


def run_walkforward(
    strategy: Strategy,
    data: DataFrame,
    config: WalkforwardConfig | None = None,
) -> WalkforwardResult:
    if config is None:
        config = WalkforwardConfig()

    required_cols = {"open", "high", "low", "close", "volume"}
    missing = required_cols - set(data.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    n_bars = len(data)
    windows_spec = _make_windows(n_bars, config)
    if not windows_spec:
        raise ValueError(
            f"Cannot create any walk-forward windows: {n_bars} bars "
            f"with train_ratio={config.train_ratio}, n_windows={config.n_windows}"
        )

    bt_cfg = BacktestConfig(
        initial_cash=config.initial_cash,
        commission=config.commission,
        slippage=config.slippage,
        min_trades=config.min_trades,
        risk_enabled=config.risk_enabled,
    )

    windows: list[WalkforwardWindow] = []
    for i, spec in enumerate(windows_spec):
        ts, te = spec["train_start"], spec["train_end"]
        tst, tte = spec["test_start"], spec["test_end"]

        train_data = data.iloc[ts:te]
        test_data = data.iloc[tst:tte]

        strategy.symbols = [strategy.symbols[0] if strategy.symbols else ""]

        train_result = run_backtest(strategy, train_data, bt_cfg)
        test_result = run_backtest(strategy, test_data, bt_cfg)

        windows.append(WalkforwardWindow(
            window_idx=i,
            train_start=ts,
            train_end=te,
            test_start=tst,
            test_end=tte,
            train_result=train_result,
            test_result=test_result,
            train_duration_bars=te - ts,
            test_duration_bars=tte - tst,
        ))

    oos_sharpes = [
        w.test_result.oos.sharpe for w in windows
        if w.test_result.oos.sharpe is not None
    ]
    oos_returns = [
        w.test_result.oos.total_return for w in windows
        if w.test_result.oos.total_return is not None
    ]
    oos_maxdds = [
        w.test_result.oos.max_drawdown for w in windows
        if w.test_result.oos.max_drawdown is not None
    ]
    oos_trades = [w.test_result.oos.num_trades for w in windows]

    avg_oos_sharpe = float(np.mean(oos_sharpes)) if oos_sharpes else None
    avg_oos_return = float(np.mean(oos_returns)) if oos_returns else None
    avg_oos_maxdd = float(np.mean(oos_maxdds)) if oos_maxdds else None
    avg_oos_trades = float(np.mean(oos_trades)) if oos_trades else 0.0

    sharpe_consistency = (
        float(np.std(oos_sharpes)) / max(abs(avg_oos_sharpe), 1e-10)
        if oos_sharpes and avg_oos_sharpe else 0.0
    )
    return_consistency = (
        float(np.std(oos_returns)) / max(abs(avg_oos_return), 1e-10)
        if oos_returns and avg_oos_return else 0.0
    )
    maxdd_consistency = (
        float(np.std(oos_maxdds)) / max(abs(avg_oos_maxdd), 1e-10)
        if oos_maxdds and avg_oos_maxdd else 0.0
    )

    all_windows_valid = all(
        w.test_result.oos.sufficient_sample for w in windows
    )

    return WalkforwardResult(
        strategy_name=strategy.name,
        symbol=strategy.symbols[0] if strategy.symbols else "",
        timeframe=strategy.timeframe,
        windows=windows,
        n_windows=len(windows),
        total_bars=n_bars,
        config=config,
        avg_oos_sharpe=avg_oos_sharpe,
        avg_oos_return=avg_oos_return,
        avg_oos_maxdd=avg_oos_maxdd,
        avg_oos_trades=avg_oos_trades,
        sharpe_consistency=sharpe_consistency,
        return_consistency=return_consistency,
        maxdd_consistency=maxdd_consistency,
        all_windows_valid=all_windows_valid,
        parameters=dict(strategy.params),
    )
