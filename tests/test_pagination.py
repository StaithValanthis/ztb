from __future__ import annotations

from typing import Any

import pytest

from ztb.data.errors import FetchError
from ztb.data.pagination import paginate_funding, paginate_kline


class _MockClient:
    def __init__(self, pages: list[list[dict[str, Any]]] | None = None) -> None:
        self._pages = pages or []
        self._call_count = 0

    def get_kline(
        self,
        category: str,
        symbol: str,
        interval: str,
        start: int | None = None,
        end: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        if self._call_count >= len(self._pages):
            return []
        page = self._pages[self._call_count]
        self._call_count += 1
        return page

    def get_funding_rate_history(
        self,
        symbol: str,
        category: str = "linear",
        start: int | None = None,
        end: int | None = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        if self._call_count >= len(self._pages):
            return ([], None)
        page = self._pages[self._call_count]
        self._call_count += 1
        next_cursor = None if self._call_count >= len(self._pages) else f"cursor_{self._call_count}"
        return (page, next_cursor)


def _bar(ts: int) -> dict[str, str]:
    return {
        "start": str(ts),
        "open": "50000",
        "high": "50100",
        "low": "49900",
        "close": "50050",
        "volume": "100",
        "turnover": "5000000",
    }


class TestPaginateKline:
    WINDOW_60 = 3600000 * 1000  # 1000 hours for interval 60

    def test_single_page(self) -> None:
        pages = [[_bar(1000), _bar(2000)]]
        client: Any = _MockClient(pages)
        result = list(paginate_kline(client, "linear", "BTCUSDT", "1", 0, 5000))
        assert len(result) == 1
        assert len(result[0]) == 2

    def test_two_pages_without_gaps(self) -> None:
        end_ts = self.WINDOW_60 + 3600000
        page1 = [_bar(self.WINDOW_60), _bar(self.WINDOW_60 + 3600000)]
        page2 = [_bar(0), _bar(3600000)]
        client: Any = _MockClient([page1, page2])
        result = list(paginate_kline(client, "linear", "BTCUSDT", "60", 0, end_ts))
        assert len(result) == 2

    def test_empty_page_raises_on_first(self) -> None:
        client: Any = _MockClient([[]])
        with pytest.raises(FetchError):
            list(paginate_kline(client, "linear", "BTCUSDT", "1", 0, 5000))

    def test_empty_page_after_first_returns(self) -> None:
        page1 = [_bar(1000), _bar(2000)]
        client: Any = _MockClient([page1, []])
        pages = list(paginate_kline(client, "linear", "BTCUSDT", "1", 0, 5000))
        assert len(pages) == 1

    def test_dedupe_overlapping_boundaries(self) -> None:
        bar = _bar(2000)
        client: Any = _MockClient([[bar], [_bar(3000)]])
        result = list(paginate_kline(client, "linear", "BTCUSDT", "1", 0, 5000))
        all_bars = [b for page in result for b in page]
        timestamps = [b["start"] for b in all_bars]
        assert len(timestamps) == len(set(timestamps))


class TestPaginateFunding:
    def test_terminates(self) -> None:
        pages = [[{"symbol": "BTCUSDT", "fundingRate": "0.0001"}]] * 3
        client: Any = _MockClient(pages)
        result = list(paginate_funding(client, "BTCUSDT"))
        assert len(result) == 3

    def test_single_page(self) -> None:
        pages = [[{"symbol": "BTCUSDT", "fundingRate": "0.0001"}]]
        client: Any = _MockClient(pages)
        result = list(paginate_funding(client, "BTCUSDT"))
        assert len(result) == 1

    def test_empty_result(self) -> None:
        client: Any = _MockClient([[]])
        result = list(paginate_funding(client, "BTCUSDT"))
        assert len(result) == 0
