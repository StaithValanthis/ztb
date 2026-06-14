from __future__ import annotations

import pandas as pd
import pytest
from pandas import DataFrame, Series

from ztb.validation.lookahead import LookaheadReport, check_lookahead, _same_bar


def _sample_df(n: int = 100) -> DataFrame:
    return DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(n)],
            "high": [101.0 + i * 0.1 for i in range(n)],
            "low": [99.0 + i * 0.1 for i in range(n)],
            "close": [100.0 + i * 0.1 for i in range(n)],
            "volume": [1000.0] * n,
        },
        index=pd.date_range("2020-01-01", periods=n, freq="h"),
    )


def test_check_lookahead_returns_report() -> None:
    df = _sample_df()
    signals = Series(0.0, index=df.index)
    report = check_lookahead(signals, df)
    assert isinstance(report, LookaheadReport)


def test_flat_signals_always_pass() -> None:
    df = _sample_df()
    signals = Series(0.0, index=df.index)
    report = check_lookahead(signals, df)
    assert report.passed
    assert report.score == 1.0


def test_signal_length_mismatch() -> None:
    df = _sample_df(100)
    signals = Series(0.0, index=df.index[:50])
    report = check_lookahead(signals, df)
    assert not report.passed
    assert report.score == 0.0


def test_warmup_nonzero_is_flagged() -> None:
    df = _sample_df(100)
    signals = Series(0.0, index=df.index)
    signals.iloc[2] = 0.5
    report = check_lookahead(signals, df, warmup=10)
    assert not report.passed
    assert not report.warmup_enforced
    assert any("Warmup" in d for d in report.details)


def test_warmup_zero_is_fine() -> None:
    df = _sample_df(100)
    signals = Series(0.0, index=df.index)
    signals.iloc[10] = 0.5
    report = check_lookahead(signals, df, warmup=0)
    assert report.passed
    assert report.score == 1.0


def test_future_trades_flagged() -> None:
    from datetime import datetime

    df = _sample_df(100)
    signals = Series(0.0, index=df.index)
    trades = [
        {"timestamp": pd.Timestamp("2025-01-01"), "side": "Buy", "price": 105.0, "size": 1.0, "pnl": 0.0},
    ]
    timestamps = list(df.index)
    report = check_lookahead(signals, df, trades=trades, timestamps=timestamps)
    assert report.trades_use_future_close


def test_same_bar() -> None:
    assert _same_bar(100.0, 100.0)
    assert _same_bar(100.0, 100.0000001)
    assert _same_bar(100.0, 100.001) is False
    assert _same_bar(0.0, 0.0)
    assert _same_bar(-1.0, -1.0)
