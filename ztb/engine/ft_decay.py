from __future__ import annotations

from dataclasses import dataclass

from ztb.engine.metrics import MetricsResult


@dataclass
class DecayConfig:
    min_sample: int = 504
    sharpe_floor_frac: float = 0.5
    maxdd_mult: float = 1.5


def _rel_gap(x: float | None, y: float | None) -> float:
    if x is None or y is None:
        return 0.0
    denom = max(abs(y), 1e-12)
    return abs(x - y) / denom


def compute_decay_score(
    live_metrics: MetricsResult,
    baseline_metrics: MetricsResult,
) -> float:
    sharpe_gap = _rel_gap(live_metrics.sharpe, baseline_metrics.sharpe)
    ret_gap = _rel_gap(live_metrics.total_return, baseline_metrics.total_return)
    pf_gap = _rel_gap(live_metrics.profit_factor, baseline_metrics.profit_factor)
    raw = 0.5 * sharpe_gap + 0.3 * ret_gap + 0.2 * pf_gap
    return max(0.0, min(1.0, raw))


def check_decay_alarm(
    live_metrics: MetricsResult,
    baseline_metrics: MetricsResult,
    n_bars: int,
    config: DecayConfig | None = None,
) -> tuple[bool, str]:
    if config is None:
        config = DecayConfig()
    if n_bars < config.min_sample:
        return False, f"n_bars={n_bars} < min_sample={config.min_sample}"
    reasons: list[str] = []
    if (
        live_metrics.sharpe is not None
        and baseline_metrics.sharpe is not None
        and live_metrics.sharpe < config.sharpe_floor_frac * baseline_metrics.sharpe
    ):
        reasons.append(
            f"sharpe {live_metrics.sharpe:.4f} < "
            f"floor {config.sharpe_floor_frac} * {baseline_metrics.sharpe:.4f}"
        )
    if (
        live_metrics.max_drawdown is not None
        and baseline_metrics.max_drawdown is not None
        and live_metrics.max_drawdown < 0
        and baseline_metrics.max_drawdown < 0
        and abs(live_metrics.max_drawdown) > config.maxdd_mult * abs(baseline_metrics.max_drawdown)
    ):
        reasons.append(
            f"max_drawdown {live_metrics.max_drawdown:.4f} exceeds "
            f"mult {config.maxdd_mult} * {baseline_metrics.max_drawdown:.4f}"
        )
    if reasons:
        return True, "; ".join(reasons)
    return False, "no alarm"
