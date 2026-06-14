from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame, Series

from ztb.strategies.base import Strategy
from ztb.validation.lookahead import LookaheadResult, run_lookahead_tripwire


class SmaCross(Strategy):
    name = "sma_cross"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 20

    def generate_signals(self, df: DataFrame) -> Series:
        close = df["close"]
        fast = close.rolling(5).mean()
        slow = close.rolling(20).mean()
        signal = Series(0.0, index=df.index)
        signal[fast > slow] = 1.0
        signal[fast < slow] = -1.0
        return signal.shift(1).fillna(0.0)


class BrokenStrat(Strategy):
    name = "broken"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        close = df["close"]
        return close.shift(-1).fillna(0.0)


class LookaheadByOHLCStrat(Strategy):
    name = "lookahead_ohlc"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        high = df["high"]
        return high.shift(-1).fillna(0.0)


class CloseOnlyStrat(Strategy):
    name = "close_only"
    symbols = []
    timeframe = "60"
    params = {}
    warmup = 0

    def generate_signals(self, df: DataFrame) -> Series:
        close = df["close"]
        fast = close.rolling(5).mean()
        slow = close.rolling(20).mean()
        signal = Series(0.0, index=df.index)
        signal[fast > slow] = 1.0
        signal[fast < slow] = -1.0
        return signal.shift(1).fillna(0.0)


def _make_clean_data(n: int = 200) -> DataFrame:
    np.random.seed(42)
    idx = pd.date_range("2020-01-01", periods=n, freq="h")
    close = 100.0 + np.cumsum(np.random.randn(n) * 0.5)
    data = DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.002,
            "low": close * 0.998,
            "close": close,
            "volume": np.random.uniform(800, 1200, n),
        },
        index=idx,
    )
    return data


def _data_factory(data: DataFrame):
    def _factory() -> DataFrame:
        return data[["open", "high", "low", "close", "volume"]].copy()

    return _factory


def test_sma_cross_passes() -> None:
    data = _make_clean_data(300)
    strat = SmaCross()
    result = run_lookahead_tripwire(strat, _data_factory(data))
    assert result.passed
    assert result.mode == "frame"
    assert result.bars_checked > 0


def test_broken_strategy_fails() -> None:
    data = _make_clean_data(200)
    strat = BrokenStrat()
    result = run_lookahead_tripwire(strat, _data_factory(data))
    assert not result.passed
    assert len(result.details) > 0


def test_lookahead_ohlc_strategy_fails() -> None:
    data = _make_clean_data(200)
    strat = LookaheadByOHLCStrat()
    result = run_lookahead_tripwire(strat, _data_factory(data))
    assert not result.passed
    assert len(result.details) > 0


def test_close_only_passes_with_all_columns_corrupted() -> None:
    data = _make_clean_data(200)
    strat = CloseOnlyStrat()
    result = run_lookahead_tripwire(strat, _data_factory(data))
    assert result.passed


def test_empty_data_returns_pass() -> None:
    empty = DataFrame(columns=["open", "high", "low", "close", "volume"])
    strat = SmaCross()
    result = run_lookahead_tripwire(strat, lambda: empty)
    assert result.passed
    assert result.bars_checked == 0


def test_result_type() -> None:
    data = _make_clean_data(200)
    strat = SmaCross()
    result = run_lookahead_tripwire(strat, _data_factory(data))
    assert isinstance(result, LookaheadResult)
    assert isinstance(result.passed, bool)
    assert isinstance(result.details, list)
    assert isinstance(result.bars_checked, int)
    assert isinstance(result.mode, str)


def test_missing_columns_detected() -> None:
    bad_data = DataFrame({"close": [100.0] * 50})
    strat = SmaCross()
    result = run_lookahead_tripwire(strat, lambda: bad_data)
    assert not result.passed
    assert any("Missing" in d for d in result.details)
