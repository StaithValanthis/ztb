from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame, Series

from ztb.engine.metrics import MetricsResult
from ztb.strategies.base import Strategy
from ztb.validation.conversion import SignalToFillConversion
from ztb.validation.deflated_sharpe import DeflatedSharpeResult, compute_deflated_sharpe
from ztb.validation.lookahead import LookaheadResult
from ztb.validation.scoring import evaluate_acceptance_criteria
from ztb.validation.walk_forward import WalkForwardConfig, WalkForwardResult, run_walk_forward


class FlatStrat(Strategy):
    name = "flat"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(0.0, index=df.index)


class LongStrat(Strategy):
    name = "long"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(1.0, index=df.index)


def _make_pass_result() -> tuple[WalkForwardResult, DeflatedSharpeResult, LookaheadResult]:
    n = 2000
    df = DataFrame(
        {
            "open": [100.0 + i * 0.05 for i in range(n)],
            "high": [101.0 + i * 0.05 for i in range(n)],
            "low": [99.0 + i * 0.05 for i in range(n)],
            "close": [100.0 + i * 0.05 + np.random.randn() * 0.5 for i in range(n)],
            "volume": [1000.0] * n,
        },
        index=pd.date_range("2020-01-01", periods=n, freq="h"),
    )
    strat = LongStrat()
    wf = run_walk_forward(strat, df, WalkForwardConfig(n_windows=3, min_trades=1))
    dsr = compute_deflated_sharpe(
        sharpe=wf.aggregate.sharpe or 0.0,
        n_observations=max(int(wf.aggregate.exposure_time), 1),
        n_trials=1,
    )
    look = LookaheadResult(passed=True, details=[], bars_checked=100, mode="frame")
    return wf, dsr, look


def test_evaluate_acceptance_criteria_pass() -> None:
    wf, dsr, look = _make_pass_result()
    result = evaluate_acceptance_criteria(wf, dsr, look)
    assert "pass" in result
    assert "exit_code" in result
    assert "criteria" in result
    assert len(result["criteria"]) == 8


def test_evaluate_acceptance_criteria_fail_on_lookahead() -> None:
    wf, dsr, look = _make_pass_result()
    look = LookaheadResult(
        passed=False,
        details=["Signal mismatch at bar 5"],
        bars_checked=100,
        mode="frame",
    )
    result = evaluate_acceptance_criteria(wf, dsr, look)
    c7 = [c for c in result["criteria"] if c["id"] == 7][0]
    assert not c7["pass"]
    assert not result["pass"]
    assert result["exit_code"] == 1


def test_evaluate_acceptance_criteria_fail_on_sharpe() -> None:
    empty_agg = MetricsResult(
        total_return=None,
        sharpe=None,
        sortino=None,
        max_drawdown=None,
        max_drawdown_duration=None,
        num_trades=0,
        profit_factor=None,
        win_rate=None,
        turnover=0.0,
        exposure_time=0.0,
        sufficient_sample=False,
        reason="no data",
    )
    wf = WalkForwardResult(
        per_window=[],
        aggregate=empty_agg,
        stability=None,
        n_windows_credible=0,
        n_windows_total=4,
        config=WalkForwardConfig(),
    )
    dsr = DeflatedSharpeResult(dsr=0.5, n_trials_equivalent=1, is_significant=False)
    look = LookaheadResult(passed=True, details=[], bars_checked=0, mode="frame")
    result = evaluate_acceptance_criteria(wf, dsr, look)
    assert not result["pass"]
    assert result["exit_code"] == 1


def test_all_eight_criteria_present() -> None:
    wf, dsr, look = _make_pass_result()
    result = evaluate_acceptance_criteria(wf, dsr, look)
    ids = sorted(c["id"] for c in result["criteria"])
    assert ids == [1, 2, 3, 4, 5, 6, 7, 8]


def test_criterion_names_are_correct() -> None:
    wf, dsr, look = _make_pass_result()
    result = evaluate_acceptance_criteria(wf, dsr, look)
    names = [c["name"] for c in result["criteria"]]
    assert "OOS Sharpe (cost-aware)" in names
    assert "Deflated Sharpe ratio" in names
    assert "OOS max DD" in names
    assert "OOS win rate" in names
    assert "Walk-forward credible windows" in names
    assert "Walk-forward stability" in names
    assert "Look-ahead tripwire" in names
    assert "Min trades OOS" in names


def test_exit_code_0_on_pass() -> None:
    wf, dsr, look = _make_pass_result()
    result = evaluate_acceptance_criteria(wf, dsr, look)
    if result["pass"]:
        assert result["exit_code"] == 0
    else:
        assert result["exit_code"] == 1


def test_exit_code_1_on_fail() -> None:
    empty_agg = MetricsResult(
        total_return=None,
        sharpe=None,
        sortino=None,
        max_drawdown=None,
        max_drawdown_duration=None,
        num_trades=0,
        profit_factor=None,
        win_rate=None,
        turnover=0.0,
        exposure_time=0.0,
        sufficient_sample=False,
        reason="no data",
    )
    wf = WalkForwardResult(
        per_window=[],
        aggregate=empty_agg,
        stability=None,
        n_windows_credible=0,
        n_windows_total=4,
        config=WalkForwardConfig(),
    )
    dsr = DeflatedSharpeResult(dsr=0.3, n_trials_equivalent=1, is_significant=False)
    look = LookaheadResult(passed=True, details=[], bars_checked=0, mode="frame")
    result = evaluate_acceptance_criteria(wf, dsr, look)
    assert result["exit_code"] == 1


def test_custom_min_trades() -> None:
    wf, dsr, look = _make_pass_result()
    result = evaluate_acceptance_criteria(wf, dsr, look, min_trades_total=10)
    c8 = [c for c in result["criteria"] if c["id"] == 8][0]
    assert c8["threshold"] == ">= 10"


def _make_signal_to_fill(rate: float, sufficient: bool = True) -> SignalToFillConversion:
    return SignalToFillConversion(
        conversion_rate=rate,
        runs_with_signals=5 if sufficient else 2,
        runs_with_real_fills=int(5 * rate) if sufficient else 1,
        sufficient_sample=sufficient,
    )


def test_nine_criteria_with_conversion() -> None:
    wf, dsr, look = _make_pass_result()
    stf = _make_signal_to_fill(1.0, True)
    result = evaluate_acceptance_criteria(wf, dsr, look, signal_to_fill=stf)
    assert len(result["criteria"]) == 9


def test_conversion_rate_fails_below_threshold() -> None:
    wf, dsr, look = _make_pass_result()
    stf = _make_signal_to_fill(0.50, True)
    result = evaluate_acceptance_criteria(wf, dsr, look, signal_to_fill=stf)
    c9 = [c for c in result["criteria"] if c["id"] == 9][0]
    assert not c9["pass"]
    assert result["exit_code"] == 1


def test_conversion_rate_passes_at_threshold() -> None:
    wf, dsr, look = _make_pass_result()
    stf = _make_signal_to_fill(0.80, True)
    result = evaluate_acceptance_criteria(wf, dsr, look, signal_to_fill=stf)
    c9 = [c for c in result["criteria"] if c["id"] == 9][0]
    assert c9["pass"]
    assert c9["value"] == 0.80


def test_eight_criteria_without_conversion() -> None:
    wf, dsr, look = _make_pass_result()
    result = evaluate_acceptance_criteria(wf, dsr, look)
    assert len(result["criteria"]) == 8


def test_eight_criteria_insufficient_sample() -> None:
    wf, dsr, look = _make_pass_result()
    stf = _make_signal_to_fill(1.0, False)
    result = evaluate_acceptance_criteria(wf, dsr, look, signal_to_fill=stf)
    assert len(result["criteria"]) == 8


def test_all_nine_criterion_ids_present() -> None:
    wf, dsr, look = _make_pass_result()
    stf = _make_signal_to_fill(1.0, True)
    result = evaluate_acceptance_criteria(wf, dsr, look, signal_to_fill=stf)
    assert sorted(c["id"] for c in result["criteria"]) == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_criterion_names_include_conversion() -> None:
    wf, dsr, look = _make_pass_result()
    stf = _make_signal_to_fill(1.0, True)
    result = evaluate_acceptance_criteria(wf, dsr, look, signal_to_fill=stf)
    names = [c["name"] for c in result["criteria"]]
    assert "Signal-to-fill conversion rate" in names


def test_exit_code_0_with_conversion_pass() -> None:
    wf, dsr, look = _make_pass_result()
    stf = _make_signal_to_fill(1.0, True)
    result = evaluate_acceptance_criteria(wf, dsr, look, signal_to_fill=stf)
    if result["pass"]:
        assert result["exit_code"] == 0
    else:
        assert result["exit_code"] == 1


def test_exit_code_1_with_conversion_fail() -> None:
    wf, dsr, look = _make_pass_result()
    stf = _make_signal_to_fill(0.0, True)
    result = evaluate_acceptance_criteria(wf, dsr, look, signal_to_fill=stf)
    assert result["exit_code"] == 1
