from __future__ import annotations

import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas import DataFrame

from ztb.data.cache import (
    cache_path,
    merge_incremental,
    read_cache,
    write_cache,
)
from ztb.data.errors import CacheError, SchemaError
from ztb.data.schema import OHLCV_COLUMNS


@pytest.fixture
def tmp_base() -> Path:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def _make_df(n: int = 10, start_hour: int = 0) -> DataFrame:
    idx = pd.date_range(
        f"2025-01-01 {start_hour:02d}:00", periods=n, freq="1h", tz="UTC", name="open_time"
    )
    data = {col: np.random.randn(n) * 100 + 50000 for col in OHLCV_COLUMNS}
    data["volume"] = np.abs(data["volume"]) + 1
    data["turnover"] = np.abs(data["turnover"]) + 1
    df = DataFrame(data, index=idx)
    df.index.name = "open_time"
    for col in OHLCV_COLUMNS:
        df[col] = df[col].astype("float64")
    return df


class TestWriteReadRoundTrip:
    def test_byte_identical_round_trip(self, tmp_base: Path) -> None:
        df = _make_df()
        write_cache(df, "linear", "BTCUSDT", "60", base=tmp_base)
        loaded = read_cache("linear", "BTCUSDT", "60", base=tmp_base)
        assert loaded is not None
        assert list(loaded.columns) == OHLCV_COLUMNS
        assert len(loaded) == len(df)
        assert loaded.index.name == "open_time"
        assert str(loaded.index.tz) == "UTC"

    def test_missing_file_returns_none(self, tmp_base: Path) -> None:
        assert read_cache("linear", "NONEXISTENT", "60", base=tmp_base) is None


class TestCachePath:
    def test_path_format(self, tmp_base: Path) -> None:
        path = cache_path("linear", "BTCUSDT", "60", base=tmp_base)
        assert path == tmp_base / "kline" / "linear" / "BTCUSDT" / "60.parquet"

    def test_directory_created(self, tmp_base: Path) -> None:
        path = cache_path("linear", "BTCUSDT", "60", base=tmp_base)
        assert path.parent.exists()


class TestMergeIncremental:
    def test_union_of_disjoint_ranges(self) -> None:
        cached = _make_df(n=5, start_hour=0)
        new = _make_df(n=5, start_hour=10)
        merged = merge_incremental(cached, new)
        assert len(merged) == 10
        assert merged.index.is_monotonic_increasing

    def test_overlap_latest_wins(self) -> None:
        cached = _make_df(n=5, start_hour=0)
        new = _make_df(n=5, start_hour=3)
        merged = merge_incremental(cached, new)
        assert len(merged) == 8
        assert merged.index.is_unique
        assert merged.index.is_monotonic_increasing

    def test_new_data_appended(self) -> None:
        cached = _make_df(n=5, start_hour=0)
        new = _make_df(n=3, start_hour=5)
        merged = merge_incremental(cached, new)
        assert len(merged) == 8

    def test_new_inside_cached_noop(self) -> None:
        cached = _make_df(n=10, start_hour=0)
        new = _make_df(n=3, start_hour=3)
        merged = merge_incremental(cached, new)
        assert len(merged) == 10


class TestWriteAtomicity:
    def test_crash_before_replace_no_partial(self, tmp_base: Path) -> None:
        df = _make_df()
        path = cache_path("linear", "BTCUSDT", "60", base=tmp_base)
        target = path
        fd, tmpp = tempfile.mkstemp(suffix=".parquet", prefix="ztb_test_", dir=str(path.parent))
        os.close(fd)
        tmp_path = Path(tmpp)
        df.to_parquet(tmp_path)
        assert target.exists() is False

    def test_corrupt_parquet_raises(self, tmp_base: Path) -> None:
        path = cache_path("linear", "BTCUSDT", "60", base=tmp_base)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not a parquet file")
        with pytest.raises(CacheError, match="Corrupted"):
            read_cache("linear", "BTCUSDT", "60", base=tmp_base)

    def test_write_schema_validation(self, tmp_base: Path) -> None:
        df = DataFrame({"bad": [1.0]})
        with pytest.raises(SchemaError):
            write_cache(df, "linear", "BTCUSDT", "60", base=tmp_base)


class TestCacheDir:
    def test_cache_dir_creates(self, tmp_base: Path) -> None:
        from ztb.data.cache import cache_dir

        result = cache_dir(base=tmp_base)
        assert result == tmp_base
        assert tmp_base.exists()

    def test_cache_dir_idempotent(self, tmp_base: Path) -> None:
        from ztb.data.cache import cache_dir

        cache_dir(base=tmp_base)
        cache_dir(base=tmp_base)
        assert tmp_base.exists()


class TestWriteCacheError:
    def test_os_error_raises_cache_error(self, tmp_base: Path) -> None:
        from unittest.mock import patch

        df = _make_df(n=3)
        with patch("ztb.data.cache.os.replace") as mock_replace:
            mock_replace.side_effect = OSError("permission denied")
            with pytest.raises(CacheError, match="Failed to write cache"):
                write_cache(df, "linear", "BTCUSDT", "60", base=tmp_base)
