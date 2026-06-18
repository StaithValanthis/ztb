from __future__ import annotations

from typing import Any

from ztb.data.bybit_rest import BybitPublicREST
from ztb.data.pagination import paginate_kline


def fetch_ohlcv(
    client: BybitPublicREST,
    category: str,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
) -> list[dict[str, Any]]:
    """Fetch OHLCV data with pagination.

    Returns deduplicated, ascending list of raw API dicts.
    Raises FetchError on failure.
    """
    from ztb.data.timeframes import normalize_timeframe

    interval = normalize_timeframe(interval)
    all_bars: list[dict[str, Any]] = []
    seen: set[str] = set()

    for page in paginate_kline(client, category, symbol, interval, start_ms, end_ms):
        for bar in page:
            key = bar.get("start", "") if isinstance(bar, dict) else ""
            if key not in seen:
                seen.add(key)
                all_bars.append(bar)

    return all_bars


def fetch_instruments(
    client: BybitPublicREST,
    category: str,
) -> list[dict[str, Any]]:
    """Fetch instruments for a category.

    Returns list of instrument dicts from a single page (max 500).
    """
    return client.get_instruments_info(category=category, limit=500)
