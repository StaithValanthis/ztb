from __future__ import annotations

from ztb.reporting.format import MAX_DD_LIMIT, MIN_TRADES, OOS_SHARPE_FLOOR, pass_fail
from ztb.reporting.notify import format_discord_payload, send_discord
from ztb.reporting.scorecard import build_scorecard


def _sample_run() -> dict:
    return {
        "run_id": "test_1",
        "strategy_name": "sma_cross",
        "symbol": "BTCUSDT",
        "timeframe": "60",
        "code_version": "0.4.0",
        "parameters": '{"fast": 10, "slow": 30}',
        "created_at": "2026-06-10T12:00:00",
        "credible": 1,
    }


def _sample_metrics() -> list[dict]:
    return [
        {"scope": "full", "total_return": 0.15, "sharpe": 1.5, "sortino": 2.0,
         "max_drawdown": -0.05, "max_drawdown_duration": 3, "num_trades": 50,
         "profit_factor": 2.0, "win_rate": 0.55, "turnover": 100.0,
         "exposure_time": 200.0, "credible": 1},
        {"scope": "is", "total_return": 0.20, "sharpe": 2.0, "sortino": 2.5,
         "max_drawdown": -0.03, "max_drawdown_duration": 2, "num_trades": 35,
         "profit_factor": 2.5, "win_rate": 0.60, "turnover": 70.0,
         "exposure_time": 140.0, "credible": 1},
        {"scope": "oos", "total_return": 0.10, "sharpe": 1.0, "sortino": 1.5,
         "max_drawdown": -0.05, "max_drawdown_duration": 3, "num_trades": 15,
         "profit_factor": 1.5, "win_rate": 0.50, "turnover": 30.0,
         "exposure_time": 60.0, "credible": 1},
    ]


def _sample_trades() -> list[dict]:
    return [
        {"timestamp": "2020-01-01 01:00", "side": "buy", "price": 100.0,
         "size": 1.0, "pnl": 10.0, "commission": 0.05, "slippage": 0.05},
        {"timestamp": "2020-01-01 02:00", "side": "sell", "price": 101.0,
         "size": 1.0, "pnl": 0.95, "commission": 0.05, "slippage": 0.05},
    ]


def _sample_equity() -> list[dict]:
    return [
        {"timestamp": "2020-01-01 00:00", "equity": 100000.0},
        {"timestamp": "2020-01-01 01:00", "equity": 101000.0},
        {"timestamp": "2020-01-01 02:00", "equity": 102000.0},
    ]


# RP-1: Scorecard golden file
def test_build_scorecard_shape() -> None:
    sc = build_scorecard(_sample_run(), _sample_metrics(), _sample_trades(), _sample_equity())
    assert "generated_at" in sc
    assert "metrics" in sc
    assert "trades_summary" in sc
    assert "equity_summary" in sc
    assert sc["generated_at"] == "2026-06-10T12:00:00"
    assert sc["strategy_name"] == "sma_cross"
    for scope in ("full", "is", "oos"):
        assert scope in sc["metrics"]


# RP-2: Timestamps from record, not now()
def test_scorecard_timestamp_from_record() -> None:
    sc = build_scorecard(_sample_run(), _sample_metrics(), _sample_trades(), _sample_equity())
    assert sc["generated_at"] == "2026-06-10T12:00:00"


# RP-3: Threshold boundaries
def test_pass_fail_boundaries() -> None:
    assert pass_fail(0.5, 0.5) == (True, "PASS")
    assert pass_fail(0.499, 0.5) == (False, "FAIL: 0.499 < 0.5")
    assert pass_fail(-0.25, -0.25) == (True, "PASS")
    assert pass_fail(-0.30, -0.25) == (False, "FAIL: -0.3 < -0.25")
    assert pass_fail(None, 0.5) == (False, "FAIL: no data")
    assert pass_fail(0.5, 0.5) == (True, "PASS")


def test_default_thresholds() -> None:
    assert OOS_SHARPE_FLOOR == 0.5
    assert MAX_DD_LIMIT == -0.25
    assert MIN_TRADES == 30


# RP-4: Discord payload shape
def test_discord_payload_shape() -> None:
    sc = build_scorecard(_sample_run(), _sample_metrics(), _sample_trades(), _sample_equity())
    payload = format_discord_payload(sc)
    assert isinstance(payload, list)
    assert len(payload) == 1
    embed = payload[0]
    assert "title" in embed
    assert "fields" in embed
    assert len(embed["fields"]) >= 6


# RP-5: Fail-soft no-webhook
def test_send_discord_no_webhook() -> None:
    sc = build_scorecard(_sample_run(), _sample_metrics(), _sample_trades(), _sample_equity())
    payload = format_discord_payload(sc)
    result = send_discord(payload, None)
    assert result is False


# RP-6: Fail-soft unreachable
def test_send_discord_unreachable() -> None:
    sc = build_scorecard(_sample_run(), _sample_metrics(), _sample_trades(), _sample_equity())
    payload = format_discord_payload(sc)
    result = send_discord(payload, "http://127.0.0.1:1/nonexistent")
    assert result is False


# RP-7: No secret in scorecard/payload
def test_no_secret_in_scorecard() -> None:
    sc = build_scorecard(_sample_run(), _sample_metrics(), _sample_trades(), _sample_equity())
    serialized = str(sc)
    assert "ZTB_" not in serialized
    assert "sk-" not in serialized
    assert "api_key" not in serialized.lower()
