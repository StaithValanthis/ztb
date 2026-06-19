from __future__ import annotations

from typing import Any

from ztb.validation.conversion import SignalToFillConversion
from ztb.validation.deflated_sharpe import DeflatedSharpeResult
from ztb.validation.lookahead import LookaheadResult
from ztb.validation.walk_forward import WalkForwardResult


def evaluate_acceptance_criteria(
    wf_result: WalkForwardResult,
    dsr_result: DeflatedSharpeResult,
    lookahead_result: LookaheadResult,
    min_trades_total: int = 50,
    signal_to_fill: SignalToFillConversion | None = None,
) -> dict[str, Any]:
    criteria: list[dict[str, Any]] = []
    agg = wf_result.aggregate

    oos_sharpe = agg.sharpe if agg.sharpe is not None else 0.0
    c1 = oos_sharpe >= 0.5
    criteria.append(
        {
            "id": 1,
            "name": "OOS Sharpe (cost-aware)",
            "pass": c1,
            "value": oos_sharpe,
            "threshold": ">= 0.5",
        }
    )

    c2 = dsr_result.is_significant
    criteria.append(
        {
            "id": 2,
            "name": "Deflated Sharpe ratio",
            "pass": c2,
            "value": dsr_result.dsr,
            "threshold": ">= 0.95",
        }
    )

    max_dd = agg.max_drawdown if agg.max_drawdown is not None else 0.0
    c3 = max_dd >= -0.25
    criteria.append(
        {
            "id": 3,
            "name": "OOS max DD",
            "pass": c3,
            "value": max_dd,
            "threshold": "<= 25%",
        }
    )

    win_rate = agg.win_rate if agg.win_rate is not None else 0.0
    c4 = win_rate >= 0.30
    criteria.append(
        {
            "id": 4,
            "name": "OOS win rate",
            "pass": c4,
            "value": win_rate,
            "threshold": ">= 30%",
        }
    )

    c5 = wf_result.n_windows_credible >= 3
    criteria.append(
        {
            "id": 5,
            "name": "Walk-forward credible windows",
            "pass": c5,
            "value": wf_result.n_windows_credible,
            "threshold": ">= 3",
        }
    )

    stability = wf_result.stability if wf_result.stability is not None else 999.0
    c6 = stability <= 0.5
    criteria.append(
        {
            "id": 6,
            "name": "Walk-forward stability",
            "pass": c6,
            "value": stability,
            "threshold": "<= 0.5",
        }
    )

    c7 = lookahead_result.passed
    criteria.append(
        {
            "id": 7,
            "name": "Look-ahead tripwire",
            "pass": c7,
            "value": "PASS" if c7 else "FAIL",
            "threshold": "PASS",
        }
    )

    total_trades = agg.num_trades
    c8 = total_trades >= min_trades_total
    criteria.append(
        {
            "id": 8,
            "name": "Min trades OOS",
            "pass": c8,
            "value": total_trades,
            "threshold": f">= {min_trades_total}",
        }
    )

    # In-sample + full-period robustness (2026-06-19). The OOS-window aggregate alone passed
    # strategies that only worked in a recent regime (e.g. ETH 50/200: +OOS but -14% full /
    # negative in-sample). These require the edge to also hold in-sample and over the FULL
    # period, and bound the TRUE (non-windowed) max drawdown that the per-window median hides.
    is_m = getattr(wf_result, "is_metrics", None)
    full_m = getattr(wf_result, "full_metrics", None)
    if is_m is not None:
        is_pf = is_m.profit_factor if is_m.profit_factor is not None else 0.0
        is_ret = is_m.total_return if is_m.total_return is not None else 0.0
        criteria.append(
            {
                "id": 9,
                "name": "In-sample profitable",
                "pass": is_pf >= 1.0 and is_ret > 0.0,
                "value": is_pf,
                "threshold": ">= 1.0 PF",
            }
        )
    if full_m is not None:
        full_ret = full_m.total_return if full_m.total_return is not None else 0.0
        criteria.append(
            {
                "id": 10,
                "name": "Full-period return",
                "pass": full_ret > 0.0,
                "value": full_ret,
                "threshold": "> 0",
            }
        )
        full_dd = full_m.max_drawdown if full_m.max_drawdown is not None else 0.0
        criteria.append(
            {
                "id": 11,
                "name": "Full-period max DD",
                "pass": full_dd >= -0.35,
                "value": full_dd,
                "threshold": "<= 35%",
            }
        )

    if signal_to_fill is not None and signal_to_fill.sufficient_sample:
        c9 = signal_to_fill.conversion_rate >= 0.80
        criteria.append(
            {
                "id": 12,
                "name": "Signal-to-fill conversion rate",
                "pass": c9,
                "value": signal_to_fill.conversion_rate,
                "threshold": ">= 80%",
            }
        )

    overall_pass = all(c["pass"] for c in criteria)
    exit_code = 0 if overall_pass else 1

    return {
        "pass": overall_pass,
        "exit_code": exit_code,
        "criteria": criteria,
    }
