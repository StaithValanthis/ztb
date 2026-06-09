from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from ztb.data.bybit_rest import BybitPublicREST
from ztb.data.errors import FetchError
from ztb.data.timeframes import interval_to_ms


def _dedupe_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for bar in bars:
        key = str(bar.get("start", ""))
        if key not in seen:
            seen.add(key)
            result.append(bar)
    return result


def paginate_kline(
    client: BybitPublicREST,
    category: str,
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
) -> Iterator[list[dict[str, Any]]]:
    """Yield pages of kline data walking 1000-bar windows in descending order."""
    interval_ms = interval_to_ms(interval)
    window_size = interval_ms * 1000
    current_end = end_ms

    while current_end > start_ms:
        current_start = max(start_ms, current_end - window_size)
        page = client.get_kline(
            category=category,
            symbol=symbol,
            interval=interval,
            start=current_start,
            end=current_end,
            limit=1000,
        )
        if not page:
            if current_end >= end_ms:
                raise FetchError(
                    f"First page for {symbol} {interval} returned empty at [{start_ms}, {end_ms}]"
                )
            return

        page.sort(key=lambda b: int(b.get("start", "0")))
        yield _dedupe_bars(page)
        current_end = current_start


def paginate_funding(
    client: BybitPublicREST,
    symbol: str,
    category: str = "linear",
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> Iterator[list[dict[str, Any]]]:
    """Yield pages of funding rate history via cursor-based pagination."""
    cursor: str | None = None
    has_more = True
    while has_more:
        page, cursor = client.get_funding_rate_history(
            symbol=symbol,
            category=category,
            start=start_ms,
            end=end_ms,
            limit=200,
            cursor=cursor,
        )
        if page:
            yield page
        has_more = cursor is not None
