from __future__ import annotations

import pandas as pd
import streamlit as st

from ztb.dashboard.components import (
    render_equity_chart,
    render_metrics_table,
    render_scorecard,
    render_trades_table,
)
from ztb.dashboard.data_access import DashboardData
from ztb.reporting.scorecard import build_scorecard

st.set_page_config(
    page_title="ztb Dashboard",
    page_icon="\U0001f4ca",
    layout="wide",
)

st.title("ztb Dashboard")
st.caption("Read-only view of backtest and forward-test results from the ztb result store.")


@st.cache_resource
def get_data() -> DashboardData:
    return DashboardData()


data = get_data()

run_type_filter = st.radio("Run type", ["All", "Backtest", "Forward"], horizontal=True)
if run_type_filter == "Forward":
    runs = data.list_forward_runs()
elif run_type_filter == "Backtest":
    all_runs = data.list_runs()
    runs = [r for r in all_runs if r.get("run_type", "backtest") == "backtest"]
else:
    runs = data.list_runs()

if not runs:
    st.info("No runs found. Run `ztb backtest --persist` or `ztb forwardtest --persist` first.")
    st.stop()

labels = {
    (
        f"{r['strategy_name']} / {r['symbol']} [{r['timeframe']}]"
        f" ({r.get('run_type', 'backtest')}) ({r['run_id'][:8]}...)"
    ): r["run_id"]
    for r in runs
}
selected_label = st.selectbox("Select a run", list(labels.keys()))

if selected_label:
    run_id = labels[selected_label]
    run_info = data.get_run(run_id)
    metrics = data.get_metrics(run_id)
    trades = data.get_trades(run_id)
    equity = data.get_equity(run_id)

    if run_info:
        st.subheader("Run Info")
        rtype = run_info.get("run_type", "backtest").upper()
        cols = st.columns(6)
        cols[0].metric("Strategy", run_info["strategy_name"])
        cols[1].metric("Symbol", run_info["symbol"])
        cols[2].metric("Timeframe", run_info["timeframe"])
        cols[3].metric("Type", rtype)
        cols[4].metric("Run ID", run_info["run_id"][:12] + "...")
        risk_aware = bool(run_info.get("risk_aware", 0))
        cols[5].metric("Risk", "ON" if risk_aware else "OFF")

        if metrics:
            st.subheader("Performance Metrics")
            render_metrics_table(metrics)

            if rtype == "BACKTEST":
                st.subheader("Scorecard")
                try:
                    sc = build_scorecard(run_info, metrics, trades, equity)
                    render_scorecard(sc)
                except Exception:
                    st.info("Scorecard not available for this run.")
    else:
        st.info("No metrics recorded for this run.")

    if equity:
        st.subheader("Equity Curve")
        render_equity_chart(equity)

    if trades:
        st.subheader("Trades")
        render_trades_table(trades)

    risk_aware = bool(run_info.get("risk_aware", 0)) if run_info else False
    if risk_aware:
        st.subheader("Risk Info")
        risk_d = data.get_risk_decisions(run_id)
        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("Kill Count", int(run_info.get("kill_count", 0)))
        rc2.metric(
            "Mean Gross Lev",
            f"{float(run_info['mean_gross_leverage']):.4f}"
            if run_info.get("mean_gross_leverage") is not None
            else "N/A",
        )
        rc3.metric(
            "Max DD Realized",
            f"{float(run_info['max_portfolio_dd_realized'])*100:.2f}%"
            if run_info.get("max_portfolio_dd_realized") is not None
            else "N/A",
        )
        if risk_d:
            st.dataframe(
                pd.DataFrame(risk_d)[
                    ["timestamp", "action", "reason", "current_dd", "current_heat"]
                ],
                use_container_width=True,
            )
