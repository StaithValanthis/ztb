from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ztb.engine.metrics import MetricsResult
from ztb.validation.dsr import compute_dsr
from ztb.validation.walkforward import WalkforwardResult


@dataclass
class Scorecard:
    overall_score: float
    oos_sharpe_score: float
    dsr_score: float
    walkforward_score: float
    consistency_score: float
    drawdown_score: float
    details: dict[str, Any] = field(default_factory=dict)


def _sharpe_score(sharpe: float | None) -> float:
    if sharpe is None or sharpe <= 0.0:
        return 0.0
    if sharpe >= 3.0:
        return 1.0
    return sharpe / 3.0


def _dsr_weight(dsr: float) -> float:
    return min(dsr, 1.0)


def _walkforward_score(wf: WalkforwardResult | None) -> float:
    if wf is None:
        return 0.0
    if wf.n_windows == 0:
        return 0.0

    scores: list[float] = []

    if wf.avg_oos_sharpe is not None:
        scores.append(_sharpe_score(wf.avg_oos_sharpe))

    cv_sharpe = wf.sharpe_consistency
    if cv_sharpe < 0.5:
        scores.append(1.0)
    elif cv_sharpe < 1.0:
        scores.append(1.0 - (cv_sharpe - 0.5) * 2.0)
    else:
        scores.append(0.0)

    valid_ratio = wf.all_windows_valid
    scores.append(1.0 if valid_ratio else 0.3)

    return sum(scores) / len(scores) if scores else 0.0


def _consistency_score(wf: WalkforwardResult | None) -> float:
    if wf is None or wf.n_windows < 2:
        return 0.5

    cv_sharpe = wf.sharpe_consistency
    cv_return = wf.return_consistency
    cv_maxdd = wf.maxdd_consistency

    scores = [
        1.0 / (1.0 + cv_sharpe),
        1.0 / (1.0 + cv_return),
        1.0 / (1.0 + cv_maxdd),
    ]
    return sum(scores) / len(scores)


def _drawdown_score(max_drawdown: float | None) -> float:
    if max_drawdown is None or max_drawdown >= 0.0:
        return 0.0
    dd_abs = abs(max_drawdown)
    if dd_abs <= 0.05:
        return 1.0
    if dd_abs <= 0.10:
        return 0.8
    if dd_abs <= 0.20:
        return 0.5
    if dd_abs <= 0.30:
        return 0.2
    return 0.0


def compute_scorecard(
    oos_metrics: MetricsResult | None = None,
    returns_series: Any = None,
    walkforward_result: WalkforwardResult | None = None,
    num_trials: int = 1,
    periods_per_year: float = 365 * 24,
) -> Scorecard:
    oos_sharpe = oos_metrics.sharpe if oos_metrics else None
    oos_maxdd = oos_metrics.max_drawdown if oos_metrics else None

    sharpe_score = _sharpe_score(oos_sharpe)

    if returns_series is not None and oos_sharpe is not None and oos_sharpe > 0:
        dsr_val = compute_dsr(
            sharpe=oos_sharpe,
            returns=returns_series,
            num_trials=num_trials,
            periods_per_year=periods_per_year,
        )
    else:
        dsr_val = 0.0

    wf_s = _walkforward_score(walkforward_result)
    cons_s = _consistency_score(walkforward_result)
    dd_s = _drawdown_score(oos_maxdd)

    weights = {"sharpe": 0.25, "dsr": 0.20, "walkforward": 0.25, "consistency": 0.15, "dd": 0.15}
    overall = (
        weights["sharpe"] * sharpe_score
        + weights["dsr"] * dsr_val
        + weights["walkforward"] * wf_s
        + weights["consistency"] * cons_s
        + weights["dd"] * dd_s
    )

    return Scorecard(
        overall_score=round(overall, 4),
        oos_sharpe_score=round(sharpe_score, 4),
        dsr_score=round(dsr_val, 4),
        walkforward_score=round(wf_s, 4),
        consistency_score=round(cons_s, 4),
        drawdown_score=round(dd_s, 4),
        details={
            "weights": weights,
            "oos_sharpe": oos_sharpe,
            "num_trials": num_trials,
            "n_walkforward_windows": walkforward_result.n_windows if walkforward_result else 0,
            "all_windows_valid": bool(
                walkforward_result and walkforward_result.all_windows_valid
            ),
        },
    )
