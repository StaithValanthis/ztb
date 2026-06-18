from __future__ import annotations

from pandas import Series

from ztb.engine.metrics import compute_metrics


def _rising_equity(n: int = 100) -> Series:
    return Series([100_000.0 * (1.0 + 0.001 * i) for i in range(n)])


def test_metrics_short_series_no_trades() -> None:
    eq = Series([100.0])
    m = compute_metrics(eq, [])
    assert m.num_trades == 0
    assert m.sufficient_sample is False


def test_metrics_rising() -> None:
    eq = _rising_equity(100)
    m = compute_metrics(eq, [], min_trades=0)
    assert m.total_return is not None and m.total_return > 0
    assert m.sharpe is not None and m.sharpe > 0
    assert m.max_drawdown is not None and m.max_drawdown <= 0.0


def test_sharpe_positive() -> None:
    eq = _rising_equity(100)
    m = compute_metrics(eq, [], min_trades=0)
    assert m.sharpe is not None and m.sharpe > 0.0


def test_max_drawdown_non_positive() -> None:
    eq = _rising_equity(100)
    m = compute_metrics(eq, [], min_trades=0)
    assert m.max_drawdown is not None and m.max_drawdown <= 0.0


def test_profit_factor() -> None:
    eq = _rising_equity(100)
    trades = [{"pnl": 100.0, "size": 1.0}, {"pnl": -20.0, "size": 1.0}]
    m = compute_metrics(eq, trades, min_trades=0)
    assert m.profit_factor is not None and m.profit_factor == 5.0


def test_win_rate() -> None:
    eq = _rising_equity(100)
    trades = [{"pnl": 100.0, "size": 1.0}, {"pnl": -20.0, "size": 1.0}]
    m = compute_metrics(eq, trades, min_trades=0)
    assert m.win_rate == 0.5


def test_turnover_zero_with_no_trades() -> None:
    eq = _rising_equity(100)
    m = compute_metrics(eq, [])
    assert m.turnover == 0.0


def test_sufficient_sample_false_with_few_trades() -> None:
    eq = _rising_equity(50)
    trades = [{"pnl": 10.0, "size": 1.0}]
    m = compute_metrics(eq, trades, min_trades=30)
    assert m.sufficient_sample is False
    assert "insufficient" in m.reason


def test_turnover() -> None:
    eq = _rising_equity(100)
    trades = [{"pnl": 100.0, "size": 10.0}, {"pnl": -20.0, "size": 5.0}]
    m = compute_metrics(eq, trades, min_trades=0)
    assert m.turnover == 15.0


def test_total_return_none_when_no_data() -> None:
    eq = Series([100.0])
    m = compute_metrics(eq, [])
    assert m.total_return is None


def test_resolve_periods_per_year_numeric_and_named() -> None:
    from ztb.engine.metrics import resolve_periods_per_year

    # named timeframes unchanged
    assert resolve_periods_per_year("60") == 365 * 24
    assert resolve_periods_per_year("1") == 365 * 24 * 60
    assert resolve_periods_per_year("D") == 365
    # numeric (minute) timeframes derived exactly — 4h was the mis-annualized one
    assert resolve_periods_per_year("240") == 365 * 24 * 60 / 240  # 2190, not 8760
    assert resolve_periods_per_year("30") == 365 * 24 * 60 / 30
    assert resolve_periods_per_year("120") == 365 * 24 * 60 / 120
    # garbage falls back to hourly, never crashes
    assert resolve_periods_per_year("garbage") == 365 * 24
    assert resolve_periods_per_year("0") == 365 * 24


def test_4h_sharpe_not_double_counted() -> None:
    # a 4h series must NOT be annualized as if hourly (the old 2x-inflation bug)
    import numpy as np
    from pandas import Series

    from ztb.engine.metrics import compute_metrics

    rng = np.random.default_rng(0)
    eq = Series(1000.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, 500)))
    m4h = compute_metrics(eq, [{"x": 1}] * 40, timeframe="240", min_trades=0)
    m1h = compute_metrics(eq, [{"x": 1}] * 40, timeframe="60", min_trades=0)
    assert m4h.sharpe is not None and m1h.sharpe is not None
    # same equity, coarser bar -> strictly lower annualized Sharpe (sqrt(2190/8760)=0.5x)
    assert abs(m4h.sharpe - m1h.sharpe * (2190 / 8760) ** 0.5) < 1e-6
