from __future__ import annotations

import streamlit as st

from ztb.execution.live_guard import LiveGuard
from ztb.reporting.health import check_health


def render_live_page() -> None:
    st.subheader("Live Status")

    col1, col2, col3 = st.columns(3)
    armed = LiveGuard.is_armed()
    col1.metric("Armed", "YES \U0001f534" if armed else "NO \U0001f7e2")
    col2.metric("Mode", "LIVE" if armed else "DEMO / DISARMED")
    col3.metric("Guard", "LiveGuard" if armed else "Safe (disarmed)")

    exec_run_id = st.text_input("Exec Run ID", value="")
    store_path = st.text_input("Store Path", value="")

    if exec_run_id and st.button("Check Health"):
        try:
            report = check_health(exec_run_id, store_path or None)
            st.json(
                {
                    "healthy": report.healthy,
                    "exec_run_id": report.exec_run_id,
                    "mode": report.mode,
                    "armed": report.armed,
                    "tag": report.tag,
                    "bars_processed": report.bars_processed,
                    "last_bar_ts": report.last_bar_ts,
                    "position": report.position,
                    "realized_pnl": report.realized_pnl,
                    "status": report.status,
                    "store_connected": report.store_connected,
                    "killswitch_tripped": report.killswitch_tripped,
                    "issues": report.issues,
                }
            )
        except Exception as exc:
            st.error(f"Health check failed: {exc}")

    st.markdown("---")
    st.caption("Read-only live monitoring. Killswitch status is fetched from the store.")
