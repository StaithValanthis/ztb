from __future__ import annotations

import pandas as pd
import pytest
from pandas import DataFrame

from ztb.strategies.base import Strategy
from ztb.strategies.registry import all, get, list_names


def _sample_df(length: int = 50) -> DataFrame:
    return DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(length)],
            "high": [101.0 + i * 0.1 for i in range(length)],
            "low": [99.0 + i * 0.1 for i in range(length)],
            "close": [100.0 + i * 0.1 for i in range(length)],
            "volume": [1000.0] * length,
        },
        index=pd.date_range("2020-01-01", periods=length, freq="h"),
    )


def test_strategy_is_abstract() -> None:
    with pytest.raises(TypeError):
        Strategy()  # type: ignore[abstract]


def test_get_unknown_raises() -> None:
    with pytest.raises(KeyError, match="Unknown"):
        get("nonexistent_test_strategy")


def test_list_names() -> None:
    names = list_names()
    assert isinstance(names, list)
    assert "sma_cross" in names


def test_all_returns_list() -> None:
    strategies = all()
    assert isinstance(strategies, list)
    assert len(strategies) > 0


def test_get_returns_strategy_class() -> None:
    cls = get("sma_cross")
    assert cls is not None
    assert cls.name == "sma_cross"


class TestSMACross:
    def test_generate_signals(self) -> None:
        cls = get("sma_cross")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    def test_signals_in_range(self) -> None:
        cls = get("sma_cross")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert signals.dropna().between(-1.0, 1.0).all()

    def test_signals_are_float(self) -> None:
        cls = get("sma_cross")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert signals.dtype == float

    def test_warmup_is_flat(self) -> None:
        cls = get("sma_cross")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert (signals.iloc[: strat.warmup] == 0.0).all()

    def test_name_and_params(self) -> None:
        cls = get("sma_cross")
        assert cls.name == "sma_cross"
        assert cls.params == {"fast": 5, "slow": 20}
        assert cls.warmup == 20


class TestRangeFade4h:
    def test_generate_signals(self) -> None:
        cls = get("range_fade_4h")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert len(signals) == len(df)
        assert signals.index.equals(df.index)

    def test_signals_in_range(self) -> None:
        cls = get("range_fade_4h")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert signals.dropna().between(-1.0, 1.0).all()

    def test_signals_are_float(self) -> None:
        cls = get("range_fade_4h")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert signals.dtype == float

    def test_warmup_is_flat(self) -> None:
        cls = get("range_fade_4h")
        strat = cls()
        df = _sample_df(100)
        signals = strat.generate_signals(df)
        assert (signals.iloc[: strat.warmup] == 0.0).all()

    def test_name_and_params(self) -> None:
        cls = get("range_fade_4h")
        assert cls.name == "range_fade_4h"
        assert cls.warmup == 30
        assert cls.params == {
            "lookback": 30,
            "long_entry_bps": 200,
            "short_entry_bps": 100,
            "stop_bps": 80,
            "range_min_bps": 200,
            "range_max_bps": 1500,
        }

    def test_regime_gate_too_narrow(self) -> None:
        cls = get("range_fade_4h")
        strat = cls()
        df = DataFrame(
            {
                "open": [100.0] * 60,
                "high": [100.5] * 60,
                "low": [99.9] * 60,
                "close": [100.0] * 60,
                "volume": [1000.0] * 60,
            },
            index=pd.date_range("2020-01-01", periods=60, freq="4h"),
        )
        signals = strat.generate_signals(df)
        assert (signals == 0.0).all()

    def test_regime_gate_too_wide(self) -> None:
        cls = get("range_fade_4h")
        strat = cls()
        df = DataFrame(
            {
                "open": [100.0] * 60,
                "high": [200.0] * 60,
                "low": [50.0] * 60,
                "close": [100.0] * 60,
                "volume": [1000.0] * 60,
            },
            index=pd.date_range("2020-01-01", periods=60, freq="4h"),
        )
        signals = strat.generate_signals(df)
        assert (signals == 0.0).all()

    def test_entry_near_low(self) -> None:
        cls = get("range_fade_4h")
        strat = cls()
        recent_low = 100.0
        recent_high = 105.0
        lookback = int(strat.params["lookback"])
        long_entry_bps = int(strat.params["long_entry_bps"])
        short_entry_bps = int(strat.params["short_entry_bps"])
        close_price = recent_low * (1 + long_entry_bps / 10000) - 0.01
        assert close_price < recent_high * (1 - short_entry_bps / 10000)
        df = DataFrame(
            {
                "open": [101.0] * 60,
                "high": [recent_high] * 60,
                "low": [recent_low] * 60,
                "close": [close_price] * 60,
                "volume": [1000.0] * 60,
            },
            index=pd.date_range("2020-01-01", periods=60, freq="4h"),
        )
        signals = strat.generate_signals(df)
        after_warmup = signals.iloc[lookback:]
        assert (after_warmup == 1.0).all()

    def test_entry_near_high(self) -> None:
        cls = get("range_fade_4h")
        strat = cls()
        recent_low = 100.0
        recent_high = 103.0
        lookback = int(strat.params["lookback"])
        short_entry_bps = int(strat.params["short_entry_bps"])
        df = DataFrame(
            {
                "open": [101.0] * 60,
                "high": [recent_high] * 60,
                "low": [recent_low] * 60,
                "close": [recent_high * (1 - short_entry_bps / 10000)] * 60,
                "volume": [1000.0] * 60,
            },
            index=pd.date_range("2020-01-01", periods=60, freq="4h"),
        )
        signals = strat.generate_signals(df)
        after_warmup = signals.iloc[lookback:]
        assert (after_warmup == -1.0).all()

    def test_short_takes_priority(self) -> None:
        cls = get("range_fade_4h")
        strat = cls()
        recent_low = 100.0
        recent_high = 103.0
        lookback = int(strat.params["lookback"])
        long_entry_bps = int(strat.params["long_entry_bps"])
        short_entry_bps = int(strat.params["short_entry_bps"])
        close_price = min(
            recent_low * (1 + long_entry_bps / 10000),
            recent_high * (1 - short_entry_bps / 10000),
        )
        df = DataFrame(
            {
                "open": [101.0] * 60,
                "high": [recent_high] * 60,
                "low": [recent_low] * 60,
                "close": [close_price] * 60,
                "volume": [1000.0] * 60,
            },
            index=pd.date_range("2020-01-01", periods=60, freq="4h"),
        )
        signals = strat.generate_signals(df)
        after_warmup = signals.iloc[lookback:]
        assert (after_warmup == -1.0).all()

    def test_registered_in_registry(self) -> None:
        cls = get("range_fade_4h")
        assert cls is not None
        assert cls.name == "range_fade_4h"
        names = list_names()
        assert "range_fade_4h" in names
