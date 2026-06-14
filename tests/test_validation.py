from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame, Series

from ztb.strategies.base import Strategy
from ztb.validation.deflated_sharpe import DeflatedSharpeResult, compute_deflated_sharpe
from ztb.validation.lookahead import LookaheadResult, run_lookahead_tripwire
from ztb.validation.scoring import evaluate_acceptance_criteria
from ztb.validation.store import get_validation_run, save_validation_run
from ztb.validation.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    run_walk_forward,
)

# ── helpers ────────────────────────────────────────────────────


def _make_data(n_bars: int = 5000, seed: int = 42) -> DataFrame:
    rng = np.random.default_rng(seed)
    base = 100.0
    closes = base + np.cumsum(rng.normal(0, 0.5, n_bars))
    idx = pd.date_range("2020-01-01", periods=n_bars, freq="h")
    return DataFrame(
        {
            "open": closes - rng.uniform(0, 0.5, n_bars),
            "high": closes + rng.uniform(0, 1.0, n_bars),
            "low": closes - rng.uniform(0, 1.0, n_bars),
            "close": closes,
            "volume": rng.uniform(1000, 5000, n_bars),
        },
        index=idx,
    )


class FlatStrategy(Strategy):
    name = "flat"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(0.0, index=df.index)


class LongStrategy(Strategy):
    name = "long"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        return Series(1.0, index=df.index)


class SmaCrossLike(Strategy):
    name = "sma_like"
    symbols = []
    timeframe = "60"
    params = {"fast": 5, "slow": 20}
    warmup = 20

    def generate_signals(self, df: DataFrame) -> Series:
        fast = df["close"].rolling(5).mean()
        slow = df["close"].rolling(20).mean()
        signals = Series(0.0, index=df.index)
        signals[fast > slow] = 1.0
        signals[: self.warmup] = 0.0
        return signals


class LookaheadStrategy(Strategy):
    name = "lookahead"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        s = Series(0.0, index=df.index)
        s.iloc[:] = df["close"].shift(-1).fillna(0.0).values
        return s


class RandomSignalStrategy(Strategy):
    name = "random"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        rng = np.random.default_rng(42)
        return Series(rng.uniform(-1, 1, len(df)), index=df.index)


# ── Walk-forward tests ─────────────────────────────────────────


class TestWalkForwardConfig:
    def test_defaults(self):
        cfg = WalkForwardConfig()
        assert cfg.n_windows == 4
        assert cfg.train_ratio == 0.7
        assert cfg.step_size is None
        assert cfg.min_train_bars == 500
        assert cfg.min_oos_bars == 100
        assert cfg.warmup is None
        assert cfg.min_trades == 30

    def test_custom_values(self):
        cfg = WalkForwardConfig(n_windows=6, train_ratio=0.8, min_trades=50)
        assert cfg.n_windows == 6
        assert cfg.train_ratio == 0.8
        assert cfg.min_trades == 50


class TestWalkForward:
    def test_produces_n_windows(self):
        data = _make_data(6000)
        strat = SmaCrossLike()
        cfg = WalkForwardConfig(n_windows=4, min_trades=0, min_train_bars=100, min_oos_bars=50)
        result = run_walk_forward(strat, data, cfg)
        assert len(result.per_window) >= 1
        assert result.n_windows_total == 4

    def test_aggregate_uses_median(self):
        cfg = WalkForwardConfig(n_windows=4, min_trades=0, min_train_bars=100, min_oos_bars=50)
        data = _make_data(6000)
        strat = SmaCrossLike()
        result = run_walk_forward(strat, data, cfg)
        if result.aggregate.sharpe is not None and len(result.per_window) > 0:
            sharpes = [w.sharpe for w in result.per_window if w.sharpe is not None]
            if sharpes:
                expected = float(np.median(sharpes))
                assert abs(result.aggregate.sharpe - expected) < 1e-6

    def test_stability_computed(self):
        data = _make_data(6000)
        strat = SmaCrossLike()
        cfg = WalkForwardConfig(n_windows=4, min_trades=0, min_train_bars=100, min_oos_bars=50)
        result = run_walk_forward(strat, data, cfg)
        window_sharpes = [w.sharpe for w in result.per_window if w.sharpe is not None]
        if len(window_sharpes) >= 2 and abs(float(np.mean(window_sharpes))) > 1e-10:
            assert result.stability is not None
            assert result.stability >= 0.0

    def test_flat_strategy_returns_none_metrics(self):
        data = _make_data(2000)
        strat = FlatStrategy()
        cfg = WalkForwardConfig(n_windows=2, min_trades=0, min_train_bars=100, min_oos_bars=50)
        result = run_walk_forward(strat, data, cfg)
        assert result.aggregate is not None

    def test_return_type(self):
        data = _make_data(6000)
        strat = SmaCrossLike()
        cfg = WalkForwardConfig(n_windows=3, min_trades=0, min_train_bars=100, min_oos_bars=50)
        result = run_walk_forward(strat, data, cfg)
        assert isinstance(result, WalkForwardResult)
        assert isinstance(result.per_window, list)
        assert hasattr(result.aggregate, "sharpe")
        assert result.n_windows_total == 3
        assert result.config is cfg

    def test_safe_median_empty_returns_none(self):
        from ztb.validation.walk_forward import _safe_median

        assert _safe_median([]) is None
        assert _safe_median([1.0, 2.0, 3.0]) == 2.0
        assert _safe_median([1.0]) == 1.0

    def test_short_data_does_not_crash(self):
        strat = SmaCrossLike()
        data = _make_data(50)
        cfg = WalkForwardConfig(n_windows=2, min_trades=0, min_train_bars=5, min_oos_bars=3)
        result = run_walk_forward(strat, data, cfg)
        assert result.n_windows_total == 2

    def test_step_size_none_uses_auto(self):
        data = _make_data(2000)
        strat = SmaCrossLike()
        cfg = WalkForwardConfig(
            n_windows=4,
            min_trades=0,
            min_train_bars=50,
            min_oos_bars=25,
        )
        result = run_walk_forward(strat, data, cfg)
        assert result.n_windows_total == 4
        assert len(result.per_window) >= 1


# ── Deflated Sharpe tests ──────────────────────────────────────


class TestDeflatedSharpe:
    def test_sharpe_zero_n_trials_one_returns_approx_05(self):
        result = compute_deflated_sharpe(sharpe=0.0, n_observations=100, n_trials=1)
        assert abs(result.dsr - 0.5) < 0.01
        assert result.n_trials_equivalent == 1

    def test_sharpe_zero_n_trials_gt_one_returns_less_than_05(self):
        result = compute_deflated_sharpe(sharpe=0.0, n_observations=100, n_trials=10)
        assert result.dsr < 0.5

    def test_monotonically_decreases_with_n_trials(self):
        dsrs = []
        for n in [1, 2, 5, 10, 50, 100]:
            r = compute_deflated_sharpe(sharpe=0.0, n_observations=100, n_trials=n)
            dsrs.append(r.dsr)
        for i in range(1, len(dsrs)):
            assert dsrs[i] <= dsrs[i - 1] + 1e-10

    def test_n_trials_one_matches_normal_cdf(self):
        import math

        sharpe = 0.5
        n_obs = 100
        result = compute_deflated_sharpe(sharpe=sharpe, n_observations=n_obs, n_trials=1)
        expected = 0.5 * (1.0 + math.erf(sharpe * np.sqrt(n_obs) / math.sqrt(2.0)))
        assert abs(result.dsr - expected) < 0.01

    def test_negative_sharpe_below_05(self):
        result = compute_deflated_sharpe(sharpe=-0.5, n_observations=100, n_trials=1)
        assert result.dsr < 0.5

    def test_n_trials_zero_clamped_to_one(self):
        r0 = compute_deflated_sharpe(sharpe=0.0, n_observations=100, n_trials=0)
        r1 = compute_deflated_sharpe(sharpe=0.0, n_observations=100, n_trials=1)
        assert abs(r0.dsr - r1.dsr) < 1e-10

    def test_is_significant_at_threshold(self):
        result = compute_deflated_sharpe(sharpe=3.0, n_observations=1000, n_trials=1)
        assert result.is_significant is True
        assert result.dsr >= 0.95

    def test_dsr_return_type(self):
        result = compute_deflated_sharpe(sharpe=0.5, n_observations=100, n_trials=5)
        assert 0.0 <= result.dsr <= 1.0
        assert result.n_trials_equivalent == 5
        assert isinstance(result.is_significant, bool)

    def test_lo_correction_non_normal_returns(self):
        result = compute_deflated_sharpe(
            sharpe=0.5, n_observations=100, n_trials=1, skew=0.5, kurtosis=5.0
        )
        normal_result = compute_deflated_sharpe(sharpe=0.5, n_observations=100, n_trials=1)
        assert result.dsr != normal_result.dsr


# ── Look-ahead tripwire tests ──────────────────────────────────


class TestLookaheadTripwire:
    def test_sma_cross_passes(self):
        strat = SmaCrossLike()
        data = _make_data(200)
        result = run_lookahead_tripwire(strat, lambda: data)
        assert result.passed is True
        assert len(result.details) == 0
        assert result.mode == "frame"

    def test_lookahead_strategy_fails(self):
        strat = LookaheadStrategy()
        data = _make_data(200)
        result = run_lookahead_tripwire(strat, lambda: data)
        assert result.passed is False
        assert len(result.details) > 0

    def test_bars_checked_is_n_minus_1(self):
        strat = SmaCrossLike()
        data = _make_data(200)
        result = run_lookahead_tripwire(strat, lambda: data)
        assert result.bars_checked == len(data) - 1

    def test_empty_data_returns_pass(self):
        strat = SmaCrossLike()
        empty = DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = run_lookahead_tripwire(strat, lambda: empty)
        assert result.passed is True
        assert result.bars_checked == 0

    def test_missing_columns_returns_fail(self):
        strat = SmaCrossLike()
        bad = DataFrame({"close": [100.0]})
        result = run_lookahead_tripwire(strat, lambda: bad)
        assert result.passed is False

    def test_flat_strategy_passes(self):
        strat = FlatStrategy()
        data = _make_data(200)
        result = run_lookahead_tripwire(strat, lambda: data)
        assert result.passed is True

    def test_return_type(self):
        strat = SmaCrossLike()
        data = _make_data(200)
        result = run_lookahead_tripwire(strat, lambda: data)
        assert isinstance(result, LookaheadResult)
        assert isinstance(result.passed, bool)
        assert isinstance(result.details, list)
        assert isinstance(result.bars_checked, int)

    def test_volume_only_does_not_false_positive(self):
        class CloseOnly(Strategy):
            name = "close_only"
            symbols = []
            timeframe = "60"
            params = {}
            warmup = 0

            def generate_signals(self, df: DataFrame) -> Series:
                s = Series(0.0, index=df.index)
                s.iloc[50:] = (df["close"].diff() > 0).astype(float).iloc[50:]
                return s

        strat = CloseOnly()
        data = _make_data(200)
        result = run_lookahead_tripwire(strat, lambda: data)
        assert result.passed is True


# ── Scoring tests ──────────────────────────────────────────────


def _make_wf_result(
    sharpe: float = 1.0,
    max_dd: float = -0.1,
    win_rate: float = 0.5,
    num_trades: int = 100,
    n_credible: int = 4,
    stability: float | None = 0.3,
) -> WalkForwardResult:
    from ztb.engine.metrics import MetricsResult

    agg = MetricsResult(
        total_return=0.2,
        sharpe=sharpe,
        sortino=1.0,
        max_drawdown=max_dd,
        max_drawdown_duration=5,
        num_trades=num_trades,
        profit_factor=1.5,
        win_rate=win_rate,
        turnover=1000.0,
        exposure_time=500,
        sufficient_sample=True,
    )
    return WalkForwardResult(
        per_window=[],
        aggregate=agg,
        stability=stability,
        n_windows_credible=n_credible,
        n_windows_total=4,
        config=WalkForwardConfig(),
    )


def _make_dsr_result(dsr: float = 0.95) -> DeflatedSharpeResult:
    return DeflatedSharpeResult(dsr=dsr, n_trials_equivalent=1, is_significant=dsr >= 0.95)


def _make_lookahead_result(passed: bool = True) -> LookaheadResult:
    return LookaheadResult(passed=passed, details=[], bars_checked=100, mode="frame")


class TestScoring:
    def test_all_pass(self):
        wf = _make_wf_result()
        dsr = _make_dsr_result(0.97)
        la = _make_lookahead_result(True)
        sc = evaluate_acceptance_criteria(wf, dsr, la)
        assert sc["pass"] is True
        assert sc["exit_code"] == 0

    def test_sharpe_too_low_fails(self):
        wf = _make_wf_result(sharpe=0.1)
        dsr = _make_dsr_result(0.97)
        la = _make_lookahead_result(True)
        sc = evaluate_acceptance_criteria(wf, dsr, la)
        assert sc["pass"] is False
        assert sc["exit_code"] == 1
        c1 = [c for c in sc["criteria"] if c["id"] == 1][0]
        assert c1["pass"] is False

    def test_dsr_too_low_fails(self):
        wf = _make_wf_result()
        dsr = _make_dsr_result(0.5)
        la = _make_lookahead_result(True)
        sc = evaluate_acceptance_criteria(wf, dsr, la)
        assert sc["pass"] is False
        c2 = [c for c in sc["criteria"] if c["id"] == 2][0]
        assert c2["pass"] is False

    def test_max_dd_too_deep_fails(self):
        wf = _make_wf_result(max_dd=-0.5)
        dsr = _make_dsr_result(0.97)
        la = _make_lookahead_result(True)
        sc = evaluate_acceptance_criteria(wf, dsr, la)
        assert sc["pass"] is False
        c3 = [c for c in sc["criteria"] if c["id"] == 3][0]
        assert c3["pass"] is False

    def test_lookahead_fail_causes_overall_fail(self):
        wf = _make_wf_result()
        dsr = _make_dsr_result(0.97)
        la = _make_lookahead_result(False)
        sc = evaluate_acceptance_criteria(wf, dsr, la)
        assert sc["pass"] is False
        c7 = [c for c in sc["criteria"] if c["id"] == 7][0]
        assert c7["pass"] is False

    def test_not_enough_credible_windows_fails(self):
        wf = _make_wf_result(n_credible=1)
        dsr = _make_dsr_result(0.97)
        la = _make_lookahead_result(True)
        sc = evaluate_acceptance_criteria(wf, dsr, la)
        assert sc["pass"] is False
        c5 = [c for c in sc["criteria"] if c["id"] == 5][0]
        assert c5["pass"] is False

    def test_poor_stability_fails(self):
        wf = _make_wf_result(stability=1.5)
        dsr = _make_dsr_result(0.97)
        la = _make_lookahead_result(True)
        sc = evaluate_acceptance_criteria(wf, dsr, la)
        assert sc["pass"] is False
        c6 = [c for c in sc["criteria"] if c["id"] == 6][0]
        assert c6["pass"] is False

    def test_few_trades_fails(self):
        wf = _make_wf_result(num_trades=10)
        dsr = _make_dsr_result(0.97)
        la = _make_lookahead_result(True)
        sc = evaluate_acceptance_criteria(wf, dsr, la)
        assert sc["pass"] is False
        c8 = [c for c in sc["criteria"] if c["id"] == 8][0]
        assert c8["pass"] is False

    def test_returns_eight_criteria(self):
        wf = _make_wf_result()
        dsr = _make_dsr_result(0.97)
        la = _make_lookahead_result(True)
        sc = evaluate_acceptance_criteria(wf, dsr, la)
        assert len(sc["criteria"]) == 8

    def test_low_win_rate_fails(self):
        wf = _make_wf_result(win_rate=0.1)
        dsr = _make_dsr_result(0.97)
        la = _make_lookahead_result(True)
        sc = evaluate_acceptance_criteria(wf, dsr, la)
        assert sc["pass"] is False
        c4 = [c for c in sc["criteria"] if c["id"] == 4][0]
        assert c4["pass"] is False


# ── Store tests ────────────────────────────────────────────────


class TestStore:
    def test_save_and_load_round_trip(self, tmp_path):
        data = _make_data(2000)
        strat = SmaCrossLike()
        la = _make_lookahead_result(True)
        dsr = _make_dsr_result(0.95)
        cfg = WalkForwardConfig(n_windows=2, min_trades=0, min_train_bars=100, min_oos_bars=50)
        wf = run_walk_forward(strat, data, cfg)

        db_path = tmp_path / "test.db"
        from ztb.store.results import connect

        conn = connect(str(db_path))
        run_id = save_validation_run(
            conn, "sma_cross", "BTCUSDT", "60", True, wf, dsr.dsr, dsr.is_significant, la.passed
        )

        loaded = get_validation_run(conn, run_id)
        assert loaded is not None
        assert loaded["strategy"] == "sma_cross"
        assert loaded["symbol"] == "BTCUSDT"
        assert loaded["pass"] == 1
        assert loaded["n_windows"] == 2
        assert "windows" in loaded
        conn.close()

    def test_get_nonexistent_run(self, tmp_path):
        from ztb.store.results import connect

        conn = connect(str(tmp_path / "empty.db"))
        result = get_validation_run(conn, "nonexistent")
        assert result is None
        conn.close()

    def test_save_persists_window_data(self, tmp_path):
        data = _make_data(2000)
        strat = SmaCrossLike()
        la = _make_lookahead_result(True)
        dsr_result = _make_dsr_result(0.95)
        cfg = WalkForwardConfig(n_windows=2, min_trades=0, min_train_bars=100, min_oos_bars=50)
        wf = run_walk_forward(strat, data, cfg)

        from ztb.store.results import connect

        conn = connect(str(tmp_path / "test2.db"))
        run_id = save_validation_run(
            conn,
            "sma_cross",
            "BTCUSDT",
            "60",
            True,
            wf,
            dsr_result.dsr,
            dsr_result.is_significant,
            la.passed,
        )

        loaded = get_validation_run(conn, run_id)
        assert len(loaded["windows"]) == len(wf.per_window)
        for w in loaded["windows"]:
            assert "window_idx" in w
            assert "sharpe" in w
        conn.close()


# ── CLI validation gate tests ──────────────────────────────────


class TestValidateCLI:
    def test_validate_missing_strategy_exits_2(self):
        from click.testing import CliRunner

        from ztb.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "nonexistent", "BTCUSDT"])
        assert result.exit_code == 2

    def test_validate_help(self):
        from click.testing import CliRunner

        from ztb.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output
        assert "walk-forward-windows" in result.output

    def test_validate_missing_args(self):
        from click.testing import CliRunner

        from ztb.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["validate"])
        assert result.exit_code == 2

    def test_validate_no_data_is_error(self):
        from click.testing import CliRunner

        from ztb.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "sma_cross", "NONEXISTENT"])
        assert result.exit_code in (1, 2)


# ── Integration: full pipeline walk-forward + DSR + scoring ────


class TestValidationPipeline:
    def test_full_pipeline_returns_scorecard(self):
        data = _make_data(6000)
        strat = SmaCrossLike()
        cfg = WalkForwardConfig(n_windows=3, min_trades=0, min_train_bars=100, min_oos_bars=50)

        wf_result = run_walk_forward(strat, data, cfg)

        cols = ["open", "high", "low", "close", "volume"]
        la_result = run_lookahead_tripwire(strat, lambda: data[cols])

        oos_sharpe = wf_result.aggregate.sharpe if wf_result.aggregate.sharpe is not None else 0.0
        n_obs = int(wf_result.aggregate.exposure_time or 0)
        dsr_result = compute_deflated_sharpe(
            sharpe=oos_sharpe,
            n_observations=n_obs,
            n_trials=1,
        )

        sc = evaluate_acceptance_criteria(wf_result, dsr_result, la_result)
        assert "pass" in sc
        assert "exit_code" in sc
        assert len(sc["criteria"]) == 8
        assert sc["exit_code"] in (0, 1)

    def test_store_round_trip_validate_persist(self, tmp_path):
        data = _make_data(2000)
        strat = SmaCrossLike()
        cfg = WalkForwardConfig(n_windows=2, min_trades=0, min_train_bars=100, min_oos_bars=50)
        wf = run_walk_forward(strat, data, cfg)
        la = _make_lookahead_result(True)
        dsr_result = _make_dsr_result(0.95)
        sc = evaluate_acceptance_criteria(wf, dsr_result, la)

        from ztb.store.results import connect

        db_path = tmp_path / "store_round_trip.db"
        conn = connect(str(db_path))
        run_id = save_validation_run(
            conn,
            "sma_cross",
            "BTCUSDT",
            "60",
            sc["pass"],
            wf,
            dsr_result.dsr,
            dsr_result.is_significant,
            la.passed,
        )

        loaded = get_validation_run(conn, run_id)
        assert loaded is not None
        assert loaded["pass"] == (1 if sc["pass"] else 0)
        assert loaded["oos_sharpe"] == wf.aggregate.sharpe
        assert loaded["lookahead_pass"] == 1
        conn.close()
