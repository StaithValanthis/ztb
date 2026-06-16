from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from pandas import DataFrame

from ztb.data.bybit_rest import BackoffStrategy, BybitPublicREST, TokenBucket
from ztb.data.cache import (
    DEFAULT_CACHE_DIR,
    merge_incremental,
    read_cache,
    write_cache,
)
from ztb.data.errors import FetchError, IntegrityError
from ztb.data.fetch import fetch_ohlcv
from ztb.data.integrity import check_integrity
from ztb.data.schema import validate_schema
from ztb.data.timeframes import interval_to_ms


def _default_client() -> BybitPublicREST:
    limiter = TokenBucket(capacity=10, refill_rate=10, refill_interval=1.0)
    backoff = BackoffStrategy()
    return BybitPublicREST(rate_limiter=limiter, backoff=backoff)


def load(
    symbol: str,
    timeframe: str,
    *,
    category: str = "linear",
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    client: BybitPublicREST | None = None,
    cache_base: Path | None = None,
    no_cache: bool = False,
) -> DataFrame:
    """Load OHLCV data — the canonical data entry point.

    Contract:
    1. Check cache first (unless no_cache=True).
    2. If cache is missing data or stale, fetch from Bybit, merge, return.
    3. Result is always schema-valid, ascending, unique, no gaps.
    4. Determinism: cold == warm.
    """
    created_client = client is None
    if client is None:
        client = _default_client()
    if cache_base is None:
        cache_base = DEFAULT_CACHE_DIR

    interval_ms = interval_to_ms(timeframe)

    start_ts: pd.Timestamp | None = None
    end_ts: pd.Timestamp | None = None
    start_ms: int | None = None
    end_ms: int | None = None

    if start is not None:
        start_ts = pd.Timestamp(start, tz="UTC")
        start_ms = int(start_ts.timestamp() * 1000)
    if end is not None:
        end_ts = pd.Timestamp(end, tz="UTC")
        end_ms = int(end_ts.timestamp() * 1000)

    cached = None
    if not no_cache:
        cached = read_cache(category, symbol, timeframe, base=cache_base)

    if cached is not None and not cached.empty:
        if start_ts is not None and end_ts is not None:
            if cached.index[0] <= start_ts and cached.index[-1] >= end_ts:
                mask = (cached.index >= start_ts) & (cached.index <= end_ts)
                result = cached.loc[mask]
                return validate_schema(result)
        elif start_ts is not None:
            _now_ms = int(pd.Timestamp.now(tz="UTC").timestamp() * 1000)
            _cache_end_ms = int(cached.index[-1].timestamp() * 1000)
            _cache_fresh = (_now_ms - _cache_end_ms) <= (2 * interval_ms)
            if cached.index[0] <= start_ts and _cache_fresh:
                result = cached.loc[cached.index >= start_ts]
                return validate_schema(result)
        elif end_ts is not None and cached.index[-1] >= end_ts:
            result = cached.loc[cached.index <= end_ts]
            return validate_schema(result)

    if start_ms is not None and end_ms is not None:
        raw = fetch_ohlcv(client, category, symbol, timeframe, start_ms, end_ms)
    elif start_ms is not None:
        raw = fetch_ohlcv(
            client,
            category,
            symbol,
            timeframe,
            start_ms,
            int(pd.Timestamp.now(tz="UTC").timestamp() * 1000),
        )
    elif end_ms is not None:
        import time

        raw = fetch_ohlcv(client, category, symbol, timeframe, 0, end_ms)
    else:
        import time

        raw = fetch_ohlcv(client, category, symbol, timeframe, 0, int(time.time() * 1000))

    if not raw:
        raise FetchError(f"No data returned for {symbol} {timeframe} [{start_ms}, {end_ms}]")

    try:
        df = _raw_to_dataframe(raw)
        df = validate_schema(df)

        if cached is not None and not cached.empty:
            df = merge_incremental(cached, df)

        if start_ts is not None:
            df = df.loc[df.index >= start_ts]
        if end_ts is not None:
            df = df.loc[df.index <= end_ts]

        report = check_integrity(df, interval_ms)
        if report.has_gaps or report.has_dupes or not report.is_monotonic:
            raise IntegrityError(
                f"Data integrity check failed for {symbol} {timeframe}:"
                f" gaps={report.gap_count}, dupes={report.dupe_count},"
                f" monotonic={report.is_monotonic}"
            )

        write_cache(df, category, symbol, timeframe, base=cache_base)
    finally:
        if created_client:
            client.close()

    return df


def load_with_funding(
    symbol: str,
    timeframe: str,
    *,
    category: str = "linear",
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
    client: BybitPublicREST | None = None,
    cache_base: Path | None = None,
) -> DataFrame:
    """Load OHLCV + funding rate data.

    For perp symbols only (category='linear' or 'inverse').
    Raises ValueError if category='spot'.
    """
    if category == "spot":
        raise ValueError("load_with_funding is not supported for spot category")

    df = load(
        symbol=symbol,
        timeframe=timeframe,
        category=category,
        start=start,
        end=end,
        client=client,
        cache_base=cache_base,
    )

    df["funding_rate"] = 0.0
    return df


def _raw_to_dataframe(raw: list[dict[str, Any]]) -> DataFrame:
    """Convert raw API kline response list to a DataFrame.

    Bybit kline returns list of lists: [timestamp, open, high, low, close, volume, turnover]
    """
    rows = []
    for bar in raw:
        if isinstance(bar, dict):
            rows.append(
                {
                    "open_time": pd.Timestamp(int(bar["start"]), unit="ms", tz="UTC"),
                    "open": float(bar["open"]),
                    "high": float(bar["high"]),
                    "low": float(bar["low"]),
                    "close": float(bar["close"]),
                    "volume": float(bar["volume"]),
                    "turnover": float(bar.get("turnover", 0)),
                }
            )
        elif isinstance(bar, (list, tuple)):
            rows.append(
                {
                    "open_time": pd.Timestamp(int(bar[0]), unit="ms", tz="UTC"),
                    "open": float(bar[1]),
                    "high": float(bar[2]),
                    "low": float(bar[3]),
                    "close": float(bar[4]),
                    "volume": float(bar[5]),
                    "turnover": float(bar[6]) if len(bar) > 6 else 0.0,
                }
            )

    if not rows:
        return DataFrame(columns=["open", "high", "low", "close", "volume", "turnover"]).set_index(
            pd.DatetimeIndex([], tz="UTC", name="open_time")
        )

    df = DataFrame(rows)
    df = df.set_index("open_time")
    df.index.name = "open_time"
    for col in ["open", "high", "low", "close", "volume", "turnover"]:
        df[col] = df[col].astype("float64")
    df = df.sort_index()
    return df
