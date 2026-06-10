from __future__ import annotations

from ztb.engine.backtest import BacktestResult
from ztb.engine.metrics import MetricsResult
from ztb.engine.portfolio import PortfolioState
from ztb.reporting.format import (
    MAX_DD_LIMIT,
    MIN_TRADES,
    OOS_SHARPE_FLOOR,
    format_backtest_result,
    pass_fail,
)
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
        {
            "scope": "full",
            "total_return": 0.15,
            "sharpe": 1.5,
            "sortino": 2.0,
            "max_drawdown": -0.05,
            "max_drawdown_duration": 3,
            "num_trades": 50,
            "profit_factor": 2.0,
            "win_rate": 0.55,
            "turnover": 100.0,
            "exposure_time": 200.0,
            "credible": 1,
        },
        {
            "scope": "is",
            "total_return": 0.20,
            "sharpe": 2.0,
            "sortino": 2.5,
            "max_drawdown": -0.03,
            "max_drawdown_duration": 2,
            "num_trades": 35,
            "profit_factor": 2.5,
            "win_rate": 0.60,
            "turnover": 70.0,
            "exposure_time": 140.0,
            "credible": 1,
        },
        {
            "scope": "oos",
            "total_return": 0.10,
            "sharpe": 1.0,
            "sortino": 1.5,
            "max_drawdown": -0.05,
            "max_drawdown_duration": 3,
            "num_trades": 15,
            "profit_factor": 1.5,
            "win_rate": 0.50,
            "turnover": 30.0,
            "exposure_time": 60.0,
            "credible": 1,
        },
    ]


def _sample_trades() -> list[dict]:
    return [
        {
            "timestamp": "2020-01-01 01:00",
            "side": "buy",
            "price": 100.0,
            "size": 1.0,
            "pnl": 10.0,
            "commission": 0.05,
            "slippage": 0.05,
        },
        {
            "timestamp": "2020-01-01 02:00",
            "side": "sell",
            "price": 101.0,
            "size": 1.0,
            "pnl": 0.95,
            "commission": 0.05,
            "slippage": 0.05,
        },
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


# RP-3b: pass_fail with higher_is_better=False (drawdown)
def test_pass_fail_lower_is_better() -> None:
    r = pass_fail(-0.25, -0.25, higher_is_better=False)
    assert r == (True, "PASS")
    r = pass_fail(-0.20, -0.25, higher_is_better=False)
    assert r == (False, "FAIL: -0.2 > -0.25")
    r = pass_fail(-0.30, -0.25, higher_is_better=False)
    assert r == (True, "PASS")


# RP-3c: format_backtest_result produces correct output
def test_format_backtest_result() -> None:
    m_full = MetricsResult(
        total_return=0.15,
        sharpe=1.5,
        sortino=2.0,
        max_drawdown=-0.05,
        max_drawdown_duration=3,
        num_trades=50,
        profit_factor=2.0,
        win_rate=0.55,
        turnover=100.0,
        exposure_time=200.0,
        credible=True,
    )
    m_is = MetricsResult(
        total_return=0.20,
        sharpe=2.0,
        sortino=2.5,
        max_drawdown=-0.03,
        max_drawdown_duration=2,
        num_trades=35,
        profit_factor=2.5,
        win_rate=0.60,
        turnover=70.0,
        exposure_time=140.0,
        credible=True,
    )
    m_oos = MetricsResult(
        total_return=0.10,
        sharpe=1.0,
        sortino=1.5,
        max_drawdown=-0.05,
        max_drawdown_duration=3,
        num_trades=15,
        profit_factor=1.5,
        win_rate=0.50,
        turnover=30.0,
        exposure_time=60.0,
        credible=True,
    )
    ps = PortfolioState(cash=100000.0, position=0.0, trades=[], equity=[], timestamps=[])
    result = BacktestResult(
        strategy_name="sma_cross",
        symbol="BTCUSDT",
        timeframe="60",
        full=m_full,
        is_=m_is,
        oos=m_oos,
        portfolio=ps,
        trades=[],
        splits={},
        parameters={},
    )
    output = format_backtest_result(result)
    assert "sma_cross" in output
    assert "BTCUSDT" in output
    assert "FULL" in output
    assert "IS" in output
    assert "OOS" in output
    assert "0.1500" in output  # total_return formatted with 4 decimals
    assert "1.500" in output  # sharpe formatted with 3 decimals


# RP-3d: format_backtest_result with non-credible
def test_format_backtest_result_non_credible() -> None:
    m_full = MetricsResult(
        total_return=None,
        sharpe=None,
        sortino=None,
        max_drawdown=None,
        max_drawdown_duration=0,
        num_trades=2,
        profit_factor=None,
        win_rate=None,
        turnover=0.0,
        exposure_time=0.0,
        credible=False,
        reason="not enough trades",
    )
    m_oos = MetricsResult(
        total_return=None,
        sharpe=None,
        sortino=None,
        max_drawdown=None,
        max_drawdown_duration=0,
        num_trades=0,
        profit_factor=None,
        win_rate=None,
        turnover=0.0,
        exposure_time=0.0,
        credible=False,
        reason="no trades in OOS",
    )
    m_is = MetricsResult(
        total_return=0.0,
        sharpe=0.0,
        sortino=0.0,
        max_drawdown=0.0,
        max_drawdown_duration=0,
        num_trades=0,
        profit_factor=0.0,
        win_rate=0.0,
        turnover=0.0,
        exposure_time=0.0,
        credible=True,
    )
    ps = PortfolioState(cash=100000.0, position=0.0, trades=[], equity=[], timestamps=[])
    result = BacktestResult(
        strategy_name="test",
        symbol="X",
        timeframe="60",
        full=m_full,
        is_=m_is,
        oos=m_oos,
        portfolio=ps,
        trades=[],
        splits={},
        parameters={},
    )
    output = format_backtest_result(result)
    assert "N/A" in output
    assert "not enough trades" in output
    assert "no trades in OOS" in output


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


# RP-8: fmt_pct formatting
def test_fmt_pct() -> None:
    from ztb.reporting.format import fmt_pct

    assert fmt_pct(0.0) == "0.00%"
    assert fmt_pct(0.0513) == "5.13%"
    assert fmt_pct(-0.05) == "-5.00%"
    assert fmt_pct(1.0) == "100.00%"
    assert fmt_pct(0.5, 1) == "50.0%"
    assert fmt_pct(None) == "N/A"


# RP-9: Discord payload with pass_fail data in full scope
def test_discord_payload_with_pass_fail() -> None:
    sc = build_scorecard(_sample_run(), _sample_metrics(), _sample_trades(), _sample_equity())
    sc["metrics"]["full"]["pass_fail"] = {"oos_sharpe": "PASS", "max_dd": "FAIL"}
    payload = format_discord_payload(sc)
    assert len(payload) == 1
    fields = payload[0]["fields"]
    assert len(fields) == 8
    assert any(f["name"] == "oos_sharpe" for f in fields)


# RP-10: send_discord success path (mocked)
def test_send_discord_success(monkeypatch) -> None:
    class MockResponse:
        is_success = True

    def mock_post(*args, **kwargs):
        return MockResponse()

    monkeypatch.setattr("httpx.post", mock_post)
    result = send_discord([{"title": "test"}], "http://example.com/webhook")
    assert result is True


# RP-11: format_forwardtest_result produces correct output
def test_format_forwardtest_result() -> None:
    from ztb.engine.forwardtest import ForwardtestResult
    from ztb.reporting.format import format_forwardtest_result

    m = MetricsResult(
        total_return=0.05,
        sharpe=0.8,
        sortino=1.0,
        max_drawdown=-0.03,
        max_drawdown_duration=2,
        num_trades=10,
        profit_factor=1.2,
        win_rate=0.50,
        turnover=20.0,
        exposure_time=50.0,
        credible=True,
    )
    ps = PortfolioState(cash=95000.0, position=0.5, trades=[], equity=[], timestamps=[])
    result = ForwardtestResult(
        strategy_name="test_strat",
        symbol="BTCUSDT",
        timeframe="60",
        metrics=m,
        portfolio=ps,
        trades=[],
        parameters={},
        warmup_bars=50,
        total_bars=200,
    )
    output = format_forwardtest_result(result)
    assert "Forward Test" in output
    assert "test_strat" in output
    assert "BTCUSDT" in output
    assert "Warmup bars: 50" in output
    assert "Total bars: 200" in output
    assert "0.0500" in output
    assert "0.800" in output


# RP-12: format_forwardtest_result with non-credible
def test_format_forwardtest_result_non_credible() -> None:
    from ztb.engine.forwardtest import ForwardtestResult
    from ztb.reporting.format import format_forwardtest_result

    m = MetricsResult(
        total_return=None,
        sharpe=None,
        sortino=None,
        max_drawdown=None,
        max_drawdown_duration=0,
        num_trades=2,
        profit_factor=None,
        win_rate=None,
        turnover=0.0,
        exposure_time=0.0,
        credible=False,
        reason="not enough trades",
    )
    ps = PortfolioState(cash=100000.0, position=0.0, trades=[], equity=[], timestamps=[])
    result = ForwardtestResult(
        strategy_name="test",
        symbol="X",
        timeframe="60",
        metrics=m,
        portfolio=ps,
        trades=[],
        warmup_bars=10,
        total_bars=100,
    )
    output = format_forwardtest_result(result)
    assert "N/A" in output
    assert "not enough trades" in output


# RP-13: format_forwardtest_result with decay
def test_format_forwardtest_result_with_decay() -> None:
    from ztb.engine.forwardtest import ForwardtestResult
    from ztb.reporting.format import format_forwardtest_result

    m = MetricsResult(
        total_return=0.05,
        sharpe=0.8,
        sortino=1.0,
        max_drawdown=-0.03,
        max_drawdown_duration=2,
        num_trades=10,
        profit_factor=1.2,
        win_rate=0.50,
        turnover=20.0,
        exposure_time=50.0,
        credible=True,
    )
    ps = PortfolioState(cash=95000.0, position=0.5, trades=[], equity=[], timestamps=[])
    result = ForwardtestResult(
        strategy_name="test_strat",
        symbol="BTCUSDT",
        timeframe="60",
        metrics=m,
        portfolio=ps,
        trades=[],
        parameters={},
        warmup_bars=50,
        total_bars=200,
        decay_score=0.15,
        decay_alarm=(True, "sharpe dropped"),
    )
    output = format_forwardtest_result(result)
    assert "Forward Test" in output
    assert "0.150" in output
