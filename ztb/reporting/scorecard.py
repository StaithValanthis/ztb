from __future__ import annotations

from typing import Any

from ztb.reporting.format import MAX_DD_LIMIT, MIN_TRADES, OOS_SHARPE_FLOOR, pass_fail


def build_scorecard(
    run: dict[str, Any],
    metrics: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    equity: list[dict[str, Any]],
    risk_decisions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    generated_at = run.get("created_at", "unknown")

    metrics_by_scope: dict[str, dict[str, Any]] = {}
    for m in metrics:
        scope = m["scope"]
        pf_results = {}
        if scope == "oos":
            pf_results["oos_sharpe"] = pass_fail(m.get("sharpe"), OOS_SHARPE_FLOOR)[1]
            pf_results["max_dd"] = pass_fail(m.get("max_drawdown"), MAX_DD_LIMIT)[1]
            pf_results["min_trades"] = pass_fail(float(m.get("num_trades", 0)), float(MIN_TRADES))[
                1
            ]

        metrics_by_scope[scope] = {
            "total_return": m.get("total_return"),
            "sharpe": m.get("sharpe"),
            "sortino": m.get("sortino"),
            "max_drawdown": m.get("max_drawdown"),
            "num_trades": m.get("num_trades", 0),
            "profit_factor": m.get("profit_factor"),
            "win_rate": m.get("win_rate"),
            "turnover": m.get("turnover", 0.0),
            "exposure_time": m.get("exposure_time", 0.0),
            "pass_fail": pf_results,
        }

    trade_pnls = [t.get("pnl", 0.0) for t in trades]
    trade_comms = [t.get("commission", 0.0) for t in trades]
    trade_slips = [t.get("slippage", 0.0) for t in trades]

    trades_summary = {
        "total": len(trades),
        "avg_pnl": sum(trade_pnls) / len(trade_pnls) if trade_pnls else 0.0,
        "avg_commission": sum(trade_comms) / len(trade_comms) if trade_comms else 0.0,
        "avg_slippage": sum(trade_slips) / len(trade_slips) if trade_slips else 0.0,
    }

    eq_values = [e.get("equity", 0.0) for e in equity]
    equity_summary = {
        "start_equity": eq_values[0] if eq_values else 0.0,
        "end_equity": eq_values[-1] if eq_values else 0.0,
        "peak_equity": max(eq_values) if eq_values else 0.0,
        "low_equity": min(eq_values) if eq_values else 0.0,
    }

    import json

    risk_block: dict[str, Any] = {
        "risk_aware": bool(run.get("risk_aware", 0)),
        "max_portfolio_dd_realized": run.get("max_portfolio_dd_realized"),
        "kill_count": int(run.get("kill_count", 0)),
        "mean_gross_leverage": run.get("mean_gross_leverage"),
        "risk_decisions": risk_decisions or [],
    }

    return {
        "generated_at": generated_at,
        "strategy_name": run.get("strategy_name", ""),
        "symbol": run.get("symbol", ""),
        "timeframe": run.get("timeframe", ""),
        "code_version": run.get("code_version", ""),
        "parameters": json.loads(run.get("parameters", "{}"))
        if isinstance(run.get("parameters"), str)
        else run.get("parameters", {}),
        "sufficient_sample": bool(run.get("sufficient_sample", False)),
        "metrics": metrics_by_scope,
        "trades_summary": trades_summary,
        "equity_summary": equity_summary,
        "risk": risk_block,
    }
