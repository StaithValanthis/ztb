from __future__ import annotations

from typing import Any


def format_discord_payload(scorecard: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = scorecard.get("metrics", {})
    oos = metrics.get("oos", {})
    full = metrics.get("full", {})

    oos_sharpe = oos.get("sharpe", "N/A")
    oos_return = oos.get("total_return", "N/A")
    oos_dd = oos.get("max_drawdown", "N/A")

    embed: dict[str, Any] = {
        "title": f"Backtest: {scorecard.get('strategy_name', '?')} / {scorecard.get('symbol', '?')}",  # noqa: E501
        "color": 0x00FF00 if scorecard.get("credible", False) else 0xFF0000,
        "fields": [
            {"name": "Strategy", "value": scorecard.get("strategy_name", "?"), "inline": True},
            {"name": "Symbol", "value": scorecard.get("symbol", "?"), "inline": True},
            {"name": "Timeframe", "value": scorecard.get("timeframe", "?"), "inline": True},
            {"name": "OOS Sharpe", "value": str(oos_sharpe), "inline": True},
            {"name": "OOS Return", "value": str(oos_return), "inline": True},
            {"name": "OOS Max DD", "value": str(oos_dd), "inline": True},
        ],
        "footer": {
            "text": f"v{scorecard.get('code_version', '?')} | {scorecard.get('generated_at', '?')}"
        },
    }

    pf = full.get("pass_fail", {})
    results = []
    for k, v in pf.items():
        results.append({"name": k, "value": v, "inline": True})
    if results:
        embed["fields"].extend(results)

    return [embed]


def send_discord(payload: list[dict[str, Any]], webhook_url: str | None = None) -> bool:
    if not webhook_url:
        return False
    try:
        import httpx

        resp = httpx.post(webhook_url, json={"embeds": payload}, timeout=10.0)
        return resp.is_success
    except Exception:
        return False
