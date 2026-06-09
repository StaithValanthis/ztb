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


def interval_to_ms(interval: str) -> int:
    if interval not in INTERVAL_TO_MS:
        raise ValueError(f"Unknown interval: {interval}")
    return INTERVAL_TO_MS[interval]


def ms_to_interval(ms: int) -> str:
    if ms not in MS_TO_INTERVAL:
        raise ValueError(f"Unknown interval in ms: {ms}")
    return MS_TO_INTERVAL[ms]
