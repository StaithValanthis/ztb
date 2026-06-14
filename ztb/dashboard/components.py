from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st


def render_metrics_table(metrics: list[dict[str, Any]]) -> None:
    if not metrics:
        st.info("No metrics available.")
        return
    rows = []
    for m in metrics:
        rows.append(
            {
                "Scope": m["scope"].upper(),
                "Return %": f"{m['total_return'] * 100:.2f}%"
                if m.get("total_return") is not None
                else "N/A",
                "Sharpe": f"{m['sharpe']:.3f}" if m.get("sharpe") is not None else "N/A",
                "Sortino": f"{m['sortino']:.3f}" if m.get("sortino") is not None else "N/A",
                "Max DD %": f"{m['max_drawdown'] * 100:.2f}%"
                if m.get("max_drawdown") is not None
                else "N/A",
                "Trades": m.get("num_trades", 0),
                "Win Rate %": f"{m['win_rate'] * 100:.1f}%"
                if m.get("win_rate") is not None
                else "N/A",
                "Profit Factor": f"{m['profit_factor']:.3f}"
                if m.get("profit_factor") is not None
                else "N/A",
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True)


def render_equity_chart(equity: list[dict[str, Any]]) -> None:
    if not equity:
        st.info("No equity curve data.")
        return
    df = pd.DataFrame(equity)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.set_index("timestamp")
    st.line_chart(df["equity"])


def render_trades_table(trades: list[dict[str, Any]]) -> None:
    if not trades:
        st.info("No trades.")
        return
    df = pd.DataFrame(trades)
    cols = [
        c for c in ["timestamp", "side", "size", "price", "pnl", "commission"] if c in df.columns
    ]
    st.dataframe(df[cols], use_container_width=True)


def render_scorecard(scorecard: dict[str, Any]) -> None:
    if not scorecard:
        st.info("Scorecard not available.")
        return
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Strategy", scorecard.get("strategy_name", "?"))
    with col2:
        st.metric("Sufficient Sample", "\u2713" if scorecard.get("sufficient_sample") else "\u2717")

    metrics = scorecard.get("metrics", {})
    for scope in ("full", "is", "oos"):
        m = metrics.get(scope)
        if not m:
            continue
        st.subheader(f"{scope.upper()} Metrics")
        sc = m.get("pass_fail", {})
        pf_str = " | ".join(f"{k}: {v}" for k, v in sc.items()) if sc else ""
        st.caption(pf_str) if pf_str else None

        row = {
            "Return %": f"{m['total_return'] * 100:.2f}%"
            if m.get("total_return") is not None
            else "N/A",
            "Sharpe": f"{m['sharpe']:.3f}" if m.get("sharpe") is not None else "N/A",
            "Max DD %": f"{m['max_drawdown'] * 100:.2f}%"
            if m.get("max_drawdown") is not None
            else "N/A",
            "Trades": m.get("num_trades", 0),
            "Win Rate %": f"{m['win_rate'] * 100:.1f}%" if m.get("win_rate") is not None else "N/A",
            "PF": f"{m['profit_factor']:.3f}" if m.get("profit_factor") is not None else "N/A",
        }
        st.dataframe(pd.DataFrame([row]), use_container_width=True)
