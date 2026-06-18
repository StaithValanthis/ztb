from __future__ import annotations

INTERVAL_TO_MS: dict[str, int] = {
    "1": 60_000,
    "3": 180_000,
    "5": 300_000,
    "15": 900_000,
    "30": 1_800_000,
    "60": 3_600_000,
    "120": 7_200_000,
    "240": 14_400_000,
    "360": 21_600_000,
    "720": 43_200_000,
    "D": 86_400_000,
    "W": 604_800_000,
    "M": 2_592_000_000,
}

MS_TO_INTERVAL: dict[int, str] = {v: k for k, v in INTERVAL_TO_MS.items()}

MAX_KLINE_LIMIT: int = 1000

# Human/alias timeframes -> canonical Bybit interval codes. Strategies and humans
# naturally write "4h"/"1h"/"1d"; Bybit + the engine use "240"/"60"/"D". Normalizing
# at every boundary (interval lookup, cache key, fetch, Sharpe annualization) lets a
# strategy declare any of them and still load/cache/fetch/annualize correctly.
# (recovery_continuation declared timeframe="4h" and crashed validate: Unknown interval.)
_TIMEFRAME_ALIASES: dict[str, str] = {
    "1h": "60",
    "2h": "120",
    "4h": "240",
    "6h": "360",
    "12h": "720",
    "1d": "D",
    "d": "D",
    "1w": "W",
    "w": "W",
    "1mo": "M",
    "1month": "M",
}


def normalize_timeframe(interval: str) -> str:
    """Map a human/alias timeframe ("4h","1h","1d") to its canonical Bybit code
    ("240","60","D"). Canonical codes pass through; unknown values return as-is so
    the caller raises a clear error."""
    if interval in INTERVAL_TO_MS:
        return interval
    return _TIMEFRAME_ALIASES.get(interval.strip().lower(), interval)


def interval_to_ms(interval: str) -> int:
    interval = normalize_timeframe(interval)
    if interval not in INTERVAL_TO_MS:
        raise ValueError(f"Unknown interval: {interval}")
    return INTERVAL_TO_MS[interval]


def ms_to_interval(ms: int) -> str:
    if ms not in MS_TO_INTERVAL:
        raise ValueError(f"Unknown interval in ms: {ms}")
    return MS_TO_INTERVAL[ms]
