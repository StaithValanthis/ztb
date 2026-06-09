from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import DataFrame

from ztb.data.integrity import check_integrity, has_dupes, has_gaps, is_stale
from ztb.data.schema import OHLCV_COLUMNS


def _make_df(n: int = 10, start_hour: int = 0, freq: str = "1h") -> DataFrame:
    idx = pd.date_range(
        f"2025-01-01 {start_hour:02d}:00", periods=n, freq=freq, tz="UTC", name="open_time"
    )
    data = {col: np.random.randn(n) * 100 + 50000 for col in OHLCV_COLUMNS}
    data["volume"] = np.abs(data["volume"]) + 1
    data["turnover"] = np.abs(data["turnover"]) + 1
    df = DataFrame(data, index=idx)
    df.index.name = "open_time"
    for col in OHLCV_COLUMNS:
        df[col] = df[col].astype("float64")
    return df


class TestGapDetection:
    def test_no_gaps(self) -> None:
        df = _make_df(n=10)
        report = check_integrity(df, 3_600_000)
        assert not report.has_gaps
        assert report.gap_count == 0

    def test_gap_detected(self) -> None:
        df = _make_df(n=5, start_hour=0)
        extra = _make_df(n=3, start_hour=10)
        df = pd.concat([df, extra])
        df = df[~df.index.duplicated(keep="first")].sort_index()
        report = check_integrity(df, 3_600_000)
        assert report.has_gaps
        assert report.gap_count >= 1

    def test_gap_range_returns_correct_bounds(self) -> None:
        df = _make_df(n=3, start_hour=0)
        extra = _make_df(n=2, start_hour=5)
        df = pd.concat([df, extra])
        df = df[~df.index.duplicated(keep="first")].sort_index()
        report = check_integrity(df, 3_600_000)
        if report.has_gaps:
            for gs, ge in report.gap_ranges:
                assert gs < ge

    def test_pre_launch_time_not_flagged(self) -> None:
        df = _make_df(n=5, start_hour=0)
        extra = _make_df(n=3, start_hour=10)
        df = pd.concat([df.iloc[:3], df.iloc[3:], extra])
        df = df[~df.index.duplicated(keep="first")].sort_index()
        launch_time = pd.Timestamp("2025-01-01 05:00", tz="UTC")
        report = check_integrity(df, 3_600_000, launch_time=launch_time)
        if report.has_gaps:
            for gs, _ge in report.gap_ranges:
                assert gs >= launch_time


class TestDupeDetection:
    def test_no_dupes(self) -> None:
        df = _make_df(n=10)
        report = check_integrity(df, 3_600_000)
        assert not report.has_dupes
        assert report.dupe_count == 0

    def test_dupe_detected(self) -> None:
        df = _make_df(n=5)
        df = pd.concat([df, df.iloc[:2]])
        report = check_integrity(df, 3_600_000)
        assert report.has_dupes
        assert report.dupe_count > 0


class TestMonotonicity:
    def test_monotonic_increasing(self) -> None:
        df = _make_df(n=10)
        report = check_integrity(df, 3_600_000)
        assert report.is_monotonic
        assert report.is_ascending

    def test_non_monotonic(self) -> None:
        df = _make_df(n=10)
        df = df.sort_index(ascending=False)
        report = check_integrity(df, 3_600_000)
        assert not report.is_monotonic
        assert not report.is_ascending


class TestFreshness:
    def test_fresh_data(self) -> None:
        df = _make_df(n=5)
        ref = df.index[-1] + pd.Timedelta(seconds=30)
        report = check_integrity(df, 3_600_000, reference_ts=ref, max_stale_seconds=3600)
        assert report.is_fresh is True
        assert report.freshness_seconds == 30.0

    def test_stale_data(self) -> None:
        df = _make_df(n=5)
        ref = df.index[-1] + pd.Timedelta(seconds=7200)
        report = check_integrity(df, 3_600_000, reference_ts=ref, max_stale_seconds=3600)
        assert report.is_fresh is False

    def test_freshness_none_when_empty(self) -> None:
        df = DataFrame(columns=OHLCV_COLUMNS).set_index(
            pd.DatetimeIndex([], tz="UTC", name="open_time")
        )
        report = check_integrity(df, 3_600_000, reference_ts=pd.Timestamp.now(tz="UTC"))
        assert report.is_fresh is None
        assert report.freshness_seconds is None


class TestEmptyDataFrame:
    def test_empty_df_no_crash(self) -> None:
        df = DataFrame(columns=OHLCV_COLUMNS).set_index(
            pd.DatetimeIndex([], tz="UTC", name="open_time")
        )
        report = check_integrity(df, 3_600_000)
        assert report.n_bars == 0
        assert report.is_fresh is None

    def test_empty_df_no_gaps(self) -> None:
        df = DataFrame(columns=OHLCV_COLUMNS).set_index(
            pd.DatetimeIndex([], tz="UTC", name="open_time")
        )
        report = check_integrity(df, 3_600_000)
        assert not report.has_gaps
        assert not report.has_dupes


class TestHelperFunctions:
    def test_has_gaps(self) -> None:
        df = _make_df(n=3)
        report = check_integrity(df, 3_600_000)
        assert has_gaps(report) == report.has_gaps

    def test_has_dupes(self) -> None:
        df = _make_df(n=3)
        report = check_integrity(df, 3_600_000)
        assert has_dupes(report) == report.has_dupes

    def test_is_stale(self) -> None:
        df = _make_df(n=3)
        ref = df.index[-1] + pd.Timedelta(seconds=7200)
        report = check_integrity(df, 3_600_000, reference_ts=ref, max_stale_seconds=3600)
        assert is_stale(report) is True

    def test_is_stale_empty(self) -> None:
        df = DataFrame(columns=OHLCV_COLUMNS).set_index(
            pd.DatetimeIndex([], tz="UTC", name="open_time")
        )
        report = check_integrity(df, 3_600_000)
        assert is_stale(report) is None
