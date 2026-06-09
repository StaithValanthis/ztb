from __future__ import annotations

from typing import NamedTuple

import pandas as pd
from pandas import DataFrame, Timestamp


class IntegrityReport(NamedTuple):
    has_gaps: bool
    gap_count: int
    gap_ranges: list[tuple[Timestamp, Timestamp]]
    has_dupes: bool
    dupe_count: int
    is_monotonic: bool
    is_ascending: bool
    is_unique: bool
    is_fresh: bool | None
    freshness_seconds: float | None
    n_bars: int
    launch_time: pd.Timestamp | None


def check_integrity(
    df: DataFrame,
    interval_ms: int,
    *,
    reference_ts: pd.Timestamp | None = None,
    max_stale_seconds: float = 3600.0,
    launch_time: pd.Timestamp | None = None,
) -> IntegrityReport:
    """Full integrity check on a DataFrame.

    - Gap detection: expected vs actual bar count given interval_ms.
    - Dupe detection: duplicates by index.
    - Monotonicity: strictly ascending index.
    - Freshness: last bar vs reference_ts.
    - launch_time floor: bars before launch_time are NOT flagged as gaps.
    """
    n_bars = len(df)

    if n_bars == 0:
        return IntegrityReport(
            has_gaps=False,
            gap_count=0,
            gap_ranges=[],
            has_dupes=False,
            dupe_count=0,
            is_monotonic=True,
            is_ascending=True,
            is_unique=True,
            is_fresh=None,
            freshness_seconds=None,
            n_bars=0,
            launch_time=launch_time,
        )

    idx = df.index

    is_unique = idx.is_unique
    has_dupes = not is_unique
    dupe_count = idx.duplicated().sum() if has_dupes else 0

    is_ascending = idx.is_monotonic_increasing
    is_monotonic = is_ascending

    gaps: list[tuple[Timestamp, Timestamp]] = []
    gap_count = 0
    if is_ascending and n_bars >= 2:
        interval_td = pd.Timedelta(milliseconds=interval_ms)
        diffs = idx.to_series().diff()
        gap_mask = diffs > interval_td
        if gap_mask.any():
            gap_indices = diffs[gap_mask].index
            for start_idx in gap_indices:
                pos_arr = idx.get_indexer(pd.Index([start_idx]))
                pos = int(pos_arr[0])
                if pos >= 1:
                    gap_start = idx[pos - 1]
                    gap_end = idx[pos]
                    if launch_time is not None and gap_start < launch_time:
                        continue
                    gaps.append((gap_start, gap_end))
                    gap_count += 1

    has_gaps = gap_count > 0

    freshness_seconds: float | None = None
    is_fresh: bool | None = None
    if reference_ts is not None and n_bars > 0:
        last_bar_time = idx[-1]
        freshness_seconds = (reference_ts - last_bar_time).total_seconds()
        is_fresh = freshness_seconds <= max_stale_seconds

    return IntegrityReport(
        has_gaps=has_gaps,
        gap_count=gap_count,
        gap_ranges=gaps,
        has_dupes=has_dupes,
        dupe_count=dupe_count,
        is_monotonic=is_monotonic,
        is_ascending=is_ascending,
        is_unique=is_unique,
        is_fresh=is_fresh,
        freshness_seconds=freshness_seconds,
        n_bars=n_bars,
        launch_time=launch_time,
    )


def has_gaps(report: IntegrityReport) -> bool:
    return report.has_gaps


def has_dupes(report: IntegrityReport) -> bool:
    return report.has_dupes


def is_stale(report: IntegrityReport) -> bool | None:
    if report.is_fresh is None:
        return None
    return not report.is_fresh
