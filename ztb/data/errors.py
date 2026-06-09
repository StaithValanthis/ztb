class DataError(Exception):
    """Base exception for data-layer errors."""


class FetchError(DataError):
    """Network / rate-limit / timeout errors."""


class SchemaError(DataError):
    """Off-grid bar, bad dtype, missing column, or other schema violations."""


class IntegrityError(DataError):
    """Gap / dupe / non-monotonic / stale data errors."""


class CacheError(DataError):
    """I/O errors or corrupted parquet cache."""
