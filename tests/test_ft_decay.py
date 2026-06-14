from __future__ import annotations

from ztb.engine.ft_decay import DecayConfig, check_decay_alarm, compute_decay_score
from ztb.engine.metrics import MetricsResult


def _metrics(
    sharpe: float | None = 1.5,
    total_return: float | None = 0.25,
    profit_factor: float | None = 2.0,
    max_drawdown: float | None = -0.10,
    sufficient_sample: bool = True,
) -> MetricsResult:
    return MetricsResult(
        total_return=total_return,
        sharpe=sharpe,
        sortino=None,
        max_drawdown=max_drawdown,
        max_drawdown_duration=10,
        num_trades=100,
        profit_factor=profit_factor,
        win_rate=0.5,
        turnover=1000.0,
        exposure_time=0.8,
        sufficient_sample=sufficient_sample,
    )


def test_score_zero_when_identical() -> None:
    baseline = _metrics()
    live = _metrics()
    score = compute_decay_score(live, baseline)
    assert score == 0.0


def test_score_positive_when_live_diverges() -> None:
    baseline = _metrics(sharpe=1.5, total_return=0.25, profit_factor=2.0)
    live = _metrics(sharpe=0.5, total_return=0.05, profit_factor=1.2)
    score = compute_decay_score(live, baseline)
    assert 0.0 < score <= 1.0


def test_score_monotonic_increasing() -> None:
    baseline = _metrics(sharpe=1.5)
    scores: list[float] = []
    for live_sharpe in [1.5, 1.2, 0.9, 0.6, 0.3]:
        live = _metrics(sharpe=live_sharpe)
        scores.append(compute_decay_score(live, baseline))
    for i in range(len(scores) - 1):
        assert scores[i] <= scores[i + 1], (
            f"score decreased at index {i}: {scores[i]} > {scores[i + 1]}"
        )


def test_score_clipped_at_zero() -> None:
    baseline = _metrics()
    live = _metrics(sharpe=1.5, total_return=0.25, profit_factor=2.0)
    score = compute_decay_score(live, baseline)
    assert score >= 0.0


def test_score_clipped_at_one() -> None:
    baseline = _metrics(sharpe=1.5)
    live = _metrics(sharpe=-20.0, total_return=-0.5, profit_factor=-5.0)
    score = compute_decay_score(live, baseline)
    assert score <= 1.0


def test_score_handles_none_metrics() -> None:
    baseline = _metrics(sharpe=None, total_return=None, profit_factor=None)
    live = _metrics(sharpe=None, total_return=None, profit_factor=None)
    score = compute_decay_score(live, baseline)
    assert score == 0.0

    baseline = _metrics(sharpe=1.5, total_return=0.25, profit_factor=2.0)
    live = _metrics(sharpe=None, total_return=None, profit_factor=None)
    score = compute_decay_score(live, baseline)
    assert score >= 0.0

    baseline = _metrics(sharpe=None, total_return=None, profit_factor=None)
    live = _metrics(sharpe=1.5, total_return=0.25, profit_factor=2.0)
    score = compute_decay_score(live, baseline)
    assert score >= 0.0


def test_alarm_triggers_on_sharpe_floor() -> None:
    baseline = _metrics(sharpe=1.5)
    live = _metrics(sharpe=0.74)
    config = DecayConfig(min_sample=0, sharpe_floor_frac=0.5)
    triggered, reason = check_decay_alarm(live, baseline, n_bars=100, config=config)
    assert triggered is True
    assert "sharpe" in reason


def test_alarm_not_triggered_above_sharpe_floor() -> None:
    baseline = _metrics(sharpe=1.5)
    live = _metrics(sharpe=0.76)
    config = DecayConfig(min_sample=0, sharpe_floor_frac=0.5)
    triggered, reason = check_decay_alarm(live, baseline, n_bars=100, config=config)
    assert triggered is False


def test_alarm_triggers_on_maxdd_mult() -> None:
    baseline = _metrics(max_drawdown=-0.10)
    live = _metrics(max_drawdown=-0.16)
    config = DecayConfig(min_sample=0, maxdd_mult=1.5)
    triggered, reason = check_decay_alarm(live, baseline, n_bars=100, config=config)
    assert triggered is True
    assert "max_drawdown" in reason


def test_alarm_not_triggered_below_maxdd_mult() -> None:
    baseline = _metrics(max_drawdown=-0.10)
    live = _metrics(max_drawdown=-0.14)
    config = DecayConfig(min_sample=0, maxdd_mult=1.5)
    triggered, reason = check_decay_alarm(live, baseline, n_bars=100, config=config)
    assert triggered is False


def test_alarm_suppressed_when_below_min_sample() -> None:
    baseline = _metrics(sharpe=1.5)
    live = _metrics(sharpe=0.1)
    config = DecayConfig(min_sample=504, sharpe_floor_frac=0.5)
    triggered, reason = check_decay_alarm(live, baseline, n_bars=100, config=config)
    assert triggered is False
    assert "n_bars" in reason


def test_alarm_uses_default_config() -> None:
    baseline = _metrics(sharpe=1.5)
    live = _metrics(sharpe=0.1)
    triggered, reason = check_decay_alarm(live, baseline, n_bars=10000)
    assert triggered is True


def test_alarm_no_alarm_when_not_triggered() -> None:
    baseline = _metrics(sharpe=1.5, max_drawdown=-0.10)
    live = baseline
    config = DecayConfig(min_sample=0)
    triggered, reason = check_decay_alarm(live, baseline, n_bars=504, config=config)
    assert triggered is False
    assert reason == "no alarm"


def test_alarm_handles_none_sharpe() -> None:
    baseline = _metrics(sharpe=None)
    live = _metrics(sharpe=None)
    config = DecayConfig(min_sample=0)
    triggered, _ = check_decay_alarm(live, baseline, n_bars=100, config=config)
    assert triggered is False


def test_alarm_handles_none_maxdd() -> None:
    baseline = _metrics(max_drawdown=None)
    live = _metrics(max_drawdown=None)
    config = DecayConfig(min_sample=0)
    triggered, _ = check_decay_alarm(live, baseline, n_bars=100, config=config)
    assert triggered is False


def test_score_uses_metricsresult_type() -> None:
    m = _metrics()
    score = compute_decay_score(m, m)
    assert isinstance(score, float)
    assert score == 0.0
