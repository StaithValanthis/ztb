from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

import pandas as pd
from pandas import DataFrame

from ztb.data.errors import CacheError, SchemaError
from ztb.data.schema import validate_schema

DEFAULT_CACHE_DIR = Path.home() / ".ztb" / "cache"


def cache_dir(*, base: Path = DEFAULT_CACHE_DIR) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_path(
    category: str,
    symbol: str,
    interval: str,
    *,
    base: Path = DEFAULT_CACHE_DIR,
) -> Path:
    from ztb.data.timeframes import normalize_timeframe

    interval = normalize_timeframe(interval)
    path = base / "kline" / category / symbol / f"{interval}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_cache(
    category: str,
    symbol: str,
    interval: str,
    *,
    base: Path = DEFAULT_CACHE_DIR,
) -> DataFrame | None:
    path = cache_path(category, symbol, interval, base=base)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        raise CacheError(f"Corrupted parquet at {path}: {exc}") from exc
    return df


def write_cache(
    df: DataFrame,
    category: str,
    symbol: str,
    interval: str,
    *,
    base: Path = DEFAULT_CACHE_DIR,
) -> None:
    try:
        validate_schema(df)
    except SchemaError:
        raise

    path = cache_path(category, symbol, interval, base=base)
    try:
        fd, tmp_path_str = tempfile.mkstemp(
            suffix=".parquet", prefix="ztb_cache_", dir=str(path.parent)
        )
        os.close(fd)
        tmp_path = Path(tmp_path_str)
        df.to_parquet(tmp_path)
        os.replace(str(tmp_path), str(path))
    except OSError as exc:
        if "tmp_path" in dir():
            with contextlib.suppress(Exception):
                Path(tmp_path_str).unlink(missing_ok=True)
        raise CacheError(f"Failed to write cache: {exc}") from exc


def merge_incremental(
    cached: DataFrame,
    new: DataFrame,
) -> DataFrame:
    """Merge new data into cached data.

    Latest-wins on duplicate open_time.
    Result is sorted ascending with unique index.
    """
    combined = pd.concat([cached, new])
    combined = combined[~combined.index.duplicated(keep="last")]
    combined = combined.sort_index()
    return combined
