# Data Layer (M1)

The `ztb/data/` module provides canonical data acquisition, caching, integrity checking, and loading for Bybit market data.

## Architecture

```
ztb/data/
  __init__.py          # Public exports
  errors.py            # Typed exception hierarchy
  schema.py            # Canonical OHLCV schema + validation
  timeframes.py        # Bybit interval ↔ ms mapping
  rate_limit.py        # Token-bucket rate limiter + backoff
  bybit_rest.py        # Bybit public REST v5 transport
  pagination.py        # 1000-bar window walk, descending→ascending
  fetch.py             # Orchestrate data fetching
  cache.py             # Parquet cache (atomic writes, incremental merge)
  integrity.py         # Gap/dupe/monotonicity/freshness checks
  loader.py            # Canonical entry point: load()
```

## Key API

### `load(symbol, timeframe, *, category, start, end, client, cache_base) → DataFrame`

The single entry point for OHLCV data:

1. Checks parquet cache first
2. If cache has all requested data within freshness, returns cached
3. Otherwise fetches missing range from Bybit, merges into cache
4. Validates schema, checks integrity
5. Returns DataFrame with canonical OHLCV columns, UTC DatetimeIndex

### `load_with_funding(symbol, timeframe, ...) → DataFrame`

OHLCV + funding rate for perpetual symbols. Raises `ValueError` for spot category.

### CLI

```
ztb data fetch <symbol> --timeframe 60 --category linear --start 2025-01-01 --end 2025-06-01
ztb data show   <symbol> --timeframe 60 --category linear --head 10
ztb data verify <symbol> --timeframe 60 --category linear
ztb data instruments --category linear
```

## Determinism

Cold (empty cache) == warm (populated cache) — identical parameters produce identical DataFrames. Second `load()` call makes zero HTTP requests.

## Dependencies

- `httpx` — HTTP transport
- `pandas` — DataFrame
- `pyarrow` — Parquet I/O
