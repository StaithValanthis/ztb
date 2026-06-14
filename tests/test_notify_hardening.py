from __future__ import annotations

from ztb.reporting.notify import format_discord_payload, send_discord, send_live_alert


def test_send_live_alert_no_webhook() -> None:
    result = send_live_alert("test_event", "test message")
    assert result is False


def test_send_live_alert_invalid_webhook() -> None:
    result = send_live_alert("test_event", "test message", webhook_url="http://invalid")
    assert result is False


def test_format_discord_payload_structure() -> None:
    scorecard = {
        "strategy_name": "test",
        "symbol": "BTCUSDT",
        "timeframe": "60",
        "code_version": "1.0.0",
        "generated_at": "2026-01-01T00:00:00Z",
        "sufficient_sample": True,
        "metrics": {
            "oos": {"sharpe": 1.5, "total_return": 0.1, "max_drawdown": -0.05},
            "full": {"pass_fail": {"sharpe": "PASS"}},
        },
    }
    payload = format_discord_payload(scorecard)
    assert isinstance(payload, list)
    assert len(payload) == 1
    embed = payload[0]
    assert embed["title"].startswith("Backtest")
    assert "fields" in embed


def test_send_discord_no_webhook() -> None:
    result = send_discord([])
    assert result is False
