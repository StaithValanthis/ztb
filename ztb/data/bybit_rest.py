from __future__ import annotations

from typing import Any

import httpx

from ztb.data.errors import FetchError
from ztb.data.rate_limit import BackoffStrategy, TokenBucket

__all__ = [
    "BybitPublicREST",
    "BackoffStrategy",
    "TokenBucket",
]


class BybitPublicREST:
    """Transport-layer client for Bybit public REST v5 endpoints.

    No auth — public endpoints only.
    """

    BASE_URL_DEMO = "https://api-demo.bybit.com"
    BASE_URL_LIVE = "https://api.bybit.com"

    def __init__(
        self,
        rate_limiter: TokenBucket,
        backoff: BackoffStrategy,
        timeout: float = 10.0,
        base_url: str = BASE_URL_DEMO,
        max_retries: int = 5,
    ) -> None:
        self._rate_limiter = rate_limiter
        self._backoff = backoff
        self._timeout = timeout
        self._base_url = base_url
        self._max_retries = max_retries
        self._client = httpx.Client(timeout=httpx.Timeout(timeout))

    def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        for attempt in range(self._max_retries):
            while not self._rate_limiter.consume():
                wait = self._rate_limiter.wait_time()
                import time as _time

                _time.sleep(wait)

            try:
                resp = self._client.request(method, url, params=params)
            except httpx.TimeoutException as exc:
                raise FetchError(f"Request timed out: {path}") from exc
            except httpx.HTTPError as exc:
                raise FetchError(f"HTTP error: {exc}") from exc

            if resp.status_code == 429:
                if attempt < self._max_retries - 1:
                    delay = self._backoff.delay(attempt)
                    import time as _time

                    _time.sleep(delay)
                    continue
                raise FetchError(f"rate limit retries exhausted for {path}")

            if resp.status_code != 200:
                raise FetchError(f"HTTP {resp.status_code} for {path}: {resp.text[:200]}")

            data: dict[str, Any] = resp.json()
            ret_code = data.get("retCode", -1)
            if ret_code != 0:
                if ret_code in (10002, 10006, 10028):
                    if attempt < self._max_retries - 1:
                        delay = self._backoff.delay(attempt)
                        import time as _time

                        _time.sleep(delay)
                        continue
                    raise FetchError(f"rate limit retries exhausted for {path}")
                raise FetchError(
                    f"Bybit API error (retCode={ret_code}) for {path}: {data.get('retMsg', '')}"
                )

            return data
        raise FetchError(f"rate limit retries exhausted for {path}")

    def get_kline(
        self,
        category: str,
        symbol: str,
        interval: str,
        start: int | None = None,
        end: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        data = self._request("GET", "/v5/market/kline", params=params)
        result = data.get("result", {})
        raw = result.get("list", [])
        return [self._kline_to_dict(item) for item in raw]

    @staticmethod
    def _kline_to_dict(item: list[Any] | dict[str, Any]) -> dict[str, str]:
        if isinstance(item, dict):
            return {
                "start": str(item.get("start", "0")),
                "open": str(item.get("open", "0")),
                "high": str(item.get("high", "0")),
                "low": str(item.get("low", "0")),
                "close": str(item.get("close", "0")),
                "volume": str(item.get("volume", "0")),
                "turnover": str(item.get("turnover", "0")),
            }
        if isinstance(item, (list, tuple)) and len(item) >= 7:
            return {
                "start": str(item[0]),
                "open": str(item[1]),
                "high": str(item[2]),
                "low": str(item[3]),
                "close": str(item[4]),
                "volume": str(item[5]),
                "turnover": str(item[6]),
            }
        if isinstance(item, (list, tuple)):
            return {
                "start": str(item[0]) if len(item) > 0 else "0",
                "open": str(item[1]) if len(item) > 1 else "0",
                "high": str(item[2]) if len(item) > 2 else "0",
                "low": str(item[3]) if len(item) > 3 else "0",
                "close": str(item[4]) if len(item) > 4 else "0",
                "volume": str(item[5]) if len(item) > 5 else "0",
                "turnover": str(item[6]) if len(item) > 6 else "0",
            }
        return {}

    def get_funding_rate_history(
        self,
        symbol: str,
        category: str = "linear",
        start: int | None = None,
        end: int | None = None,
        limit: int = 200,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "limit": limit,
        }
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        if cursor is not None:
            params["cursor"] = cursor
        data = self._request("GET", "/v5/market/funding/history", params=params)
        result: dict[str, Any] = data.get("result", {})
        items: list[dict[str, Any]] = result.get("list", [])
        next_cursor: str | None = result.get("nextPageCursor")
        return items, next_cursor

    def get_instruments_info(
        self,
        category: str,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "category": category,
            "limit": limit,
        }
        if symbol is not None:
            params["symbol"] = symbol
        if status is not None:
            params["status"] = status
        data = self._request("GET", "/v5/market/instruments-info", params=params)
        result: dict[str, Any] = data.get("result", {})
        items: list[dict[str, Any]] = result.get("list", [])
        return items

    def get_server_time(self) -> dict[str, Any]:
        data = self._request("GET", "/v5/market/time")
        result: dict[str, Any] = data.get("result", {})
        return result
