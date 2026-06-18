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
        assert cls.params == {"fast": 5, "slow": 20, "sl_pct": 0.05, "tp_pct": 0.10}
        assert cls.warmup == 20
