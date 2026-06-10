from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ztb.features.indicators import atr, crossover, ema, rsi, sma


class TestSMA:
    def test_sma_hand_computed(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(s, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        assert result.iloc[2] == 2.0
        assert result.iloc[3] == 3.0
        assert result.iloc[4] == 4.0

    def test_sma_period_one(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0])
        result = sma(s, 1)
        assert result.iloc[0] == 1.0
        assert result.iloc[1] == 2.0
        assert result.iloc[2] == 3.0

    def test_sma_invalid_period(self) -> None:
        with pytest.raises(ValueError):
            sma(pd.Series([1.0, 2.0]), 0)

    def test_sma_index_preserved(self) -> None:
        idx = pd.date_range("2025-01-01", periods=10, freq="h", tz="UTC")
        s = pd.Series(np.random.randn(10), index=idx)
        result = sma(s, 3)
        assert result.index.equals(s.index)


class TestEMA:
    def test_ema_hand_computed(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = ema(s, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        k = 2 / (3 + 1)
        expected_3 = 1 * (1 - k) ** 2 + 2 * k * (1 - k) + 3 * k
        assert result.iloc[2] == pytest.approx(expected_3, abs=1e-8)

    def test_ema_invalid_period(self) -> None:
        with pytest.raises(ValueError):
            ema(pd.Series([1.0, 2.0]), 0)

    def test_ema_index_preserved(self) -> None:
        idx = pd.date_range("2025-01-01", periods=10, freq="h", tz="UTC")
        s = pd.Series(np.random.randn(10), index=idx)
        result = ema(s, 3)
        assert result.index.equals(s.index)


class TestRSI:
    def test_rsi_hand_computed(self) -> None:
        s = pd.Series(
            [
                45.0,
                46.0,
                47.0,
                48.0,
                47.0,
                46.0,
                47.0,
                48.0,
                49.0,
                50.0,
                49.0,
                48.0,
                47.0,
                48.0,
                49.0,
                50.0,
                51.0,
                52.0,
                51.0,
                50.0,
            ]
        )
        result = rsi(s, 5)
        valid = result.dropna()
        assert len(valid) > 0
        assert valid.min() >= 0
        assert valid.max() <= 100

    def test_rsi_bounds(self) -> None:
        np.random.seed(42)
        s = pd.Series(np.random.randn(200).cumsum() + 100)
        result = rsi(s, 14)
        valid = result.dropna()
        assert len(valid) > 0
        assert valid.min() >= 0
        assert valid.max() <= 100

    def test_rsi_constant_series(self) -> None:
        s = pd.Series([50.0] * 50)
        result = rsi(s, 14)
        assert isinstance(result, pd.Series)

    def test_rsi_invalid_period(self) -> None:
        with pytest.raises(ValueError):
            rsi(pd.Series([1.0, 2.0]), 0)

    def test_rsi_index_preserved(self) -> None:
        s = pd.Series(range(30), dtype=float)
        result = rsi(s, 14)
        assert result.index.equals(s.index)


class TestATR:
    def test_atr_hand_computed(self) -> None:
        high = pd.Series([12.0, 14.0, 16.0, 18.0])
        low = pd.Series([10.0, 11.0, 12.0, 13.0])
        close = pd.Series([11.0, 13.0, 15.0, 17.0])
        result = atr(high, low, close, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])
        tr0 = max(12 - 10, abs(12 - 11), abs(10 - 11))
        tr1 = max(14 - 11, abs(14 - 11), abs(11 - 11))
        tr2 = max(16 - 12, abs(16 - 13), abs(12 - 13))
        assert result.iloc[2] == pytest.approx((tr0 + tr1 + tr2) / 3, abs=1e-8)

    def test_atr_invalid_period(self) -> None:
        with pytest.raises(ValueError):
            atr(pd.Series([1.0]), pd.Series([1.0]), pd.Series([1.0]), 0)

    def test_atr_index_preserved(self) -> None:
        high = pd.Series([12.0, 14.0, 16.0])
        low = pd.Series([10.0, 11.0, 12.0])
        close = pd.Series([11.0, 13.0, 15.0])
        result = atr(high, low, close, 2)
        assert result.index.equals(high.index)


class TestCrossover:
    def test_crossover_detection(self) -> None:
        fast = pd.Series([1.0, 2.0, 3.0, 2.5, 2.0, 1.5])
        slow = pd.Series([2.0, 2.0, 2.0, 2.0, 2.0, 2.0])
        result = crossover(fast, slow)
        assert result.iloc[0] == 0
        assert result.iloc[5] == 1

    def test_crossover_no_cross(self) -> None:
        fast = pd.Series([5.0, 6.0, 7.0])
        slow = pd.Series([4.0, 4.0, 4.0])
        result = crossover(fast, slow)
        assert (result == 0).all()

    def test_crossover_always_below(self) -> None:
        fast = pd.Series([3.0, 3.0, 3.0])
        slow = pd.Series([5.0, 5.0, 5.0])
        result = crossover(fast, slow)
        assert (result == 0).all()

    def test_crossover_equal_series(self) -> None:
        s = pd.Series([1.0, 1.0, 1.0])
        result = crossover(s, s)
        assert (result == 0).all()


class TestNoLookaheadInvariance:
    def test_truncate_at_k_invariance_sma(self) -> None:
        np.random.seed(42)
        series = pd.Series(np.random.randn(200).cumsum() + 100)
        period = 20
        full = sma(series, period)
        for k in range(period + 5, len(series), 10):
            truncated = sma(series.iloc[:k], period)
            n_compare = min(k - period, 10)
            assert truncated.iloc[-n_compare:].equals(full.iloc[k - n_compare : k])

    def test_truncate_at_k_invariance_ema(self) -> None:
        np.random.seed(42)
        series = pd.Series(np.random.randn(200).cumsum() + 100)
        period = 20
        full = ema(series, period)
        for k in range(period + 5, len(series), 10):
            truncated = ema(series.iloc[:k], period)
            n_compare = min(k - period, 10)
            assert truncated.iloc[-n_compare:].equals(full.iloc[k - n_compare : k])

    def test_truncate_at_k_invariance_rsi(self) -> None:
        np.random.seed(42)
        series = pd.Series(np.random.randn(300).cumsum() + 100)
        period = 14
        full = rsi(series, period)
        k = len(series)
        truncated = rsi(series.iloc[:k], period)
        valid_full = full.dropna()
        valid_trunc = truncated.dropna()
        assert len(valid_trunc) > 0
        assert len(valid_full) > 0
