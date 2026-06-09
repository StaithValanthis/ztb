from __future__ import annotations

from pandas import Series

from ztb.engine.metrics import compute_metrics


def _rising_equity(n: int = 100) -> Series:
    return Series([100_000.0 * (1.0 + 0.001 * i) for i in range(n)])


def test_metrics_short_series_no_trades() -> None:
    eq = Series([100.0])
    m = compute_metrics(eq, [])
    assert m.num_trades == 0
    assert m.credible is False


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


def test_credible_false_with_few_trades() -> None:
    eq = _rising_equity(50)
    trades = [{"pnl": 10.0, "size": 1.0}]
    m = compute_metrics(eq, trades, min_trades=30)
    assert m.credible is False
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
