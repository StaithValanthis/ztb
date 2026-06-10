from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ztb.execution.errors import ClientAuthError, ClientError, LiveModeBlockedError
from ztb.execution.models import (
    Mode,
    OrderSide,
    OrderType,
)

_DEMO_BASE = "https://api-demo.bybit.com"
_LIVE_BASE = "https://api.bybit.com"
_RECV_WINDOW = "5000"
_DEFAULT_TIMEOUT = 30.0


@dataclass
class ClientConfig:
    api_key: str = ""
    api_secret: str = ""
    mode: Mode = Mode.DEMO
    timeout: float = _DEFAULT_TIMEOUT
    max_retries: int = 3


class BybitClient:
    def __init__(self, config: ClientConfig) -> None:
        if config.mode == Mode.LIVE:
            raise LiveModeBlockedError()
        self._config = config
        self._base_url = _DEMO_BASE
        self._client = httpx.Client(timeout=config.timeout)

    def _sign(self, timestamp: str, method: str, path: str, body: str) -> str:
        payload = f"{timestamp}{self._config.api_key}{_RECV_WINDOW}{body}"
        sig = hmac.new(
            self._config.api_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        return sig

    def _headers(self, timestamp: str, sig: str) -> dict[str, str]:
        return {
            "X-BAPI-API-KEY": self._config.api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": sig,
            "X-BAPI-RECV-WINDOW": _RECV_WINDOW,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        ts = str(int(time.time() * 1000))
        body_str = json.dumps(body) if body else ""
        sig = self._sign(ts, method, path, body_str)
        headers = self._headers(ts, sig)

        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries):
            try:
                resp = self._client.request(
                    method=method,
                    url=url,
                    params=params,
                    headers=headers,
                    content=body_str if body else None,
                )
                if resp.status_code >= 500 and attempt < self._config.max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                data: dict[str, Any] = resp.json()
                ret_code = data.get("retCode", -1)
                if ret_code == 0:
                    result: dict[str, Any] = data.get("result", {})
                    return result
                if ret_code in (10002, 10003, 10004):
                    raise ClientAuthError(resp.status_code, data.get("retMsg", ""))
                if ret_code in (10028,) and attempt < self._config.max_retries - 1:
                    time.sleep(2.0)
                    continue
                raise ClientError(resp.status_code, data.get("retMsg", ""))
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < self._config.max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise ClientError(0, "timeout") from exc
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code >= 500 and attempt < self._config.max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                raise ClientError(exc.response.status_code) from exc
        msg = f"max retries exceeded: {last_exc}" if last_exc else "max retries exceeded"
        raise ClientError(0, msg)

    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        qty: float,
        order_type: OrderType = OrderType.MARKET,
        price: float | None = None,
        order_link_id: str = "",
        reduce_only: bool = False,
        category: str = "linear",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "side": side.value,
            "orderType": order_type.value,
            "qty": str(qty),
            "timeInForce": "IOC" if order_type == OrderType.MARKET else "GTC",
        }
        if order_link_id:
            body["orderLinkId"] = order_link_id
        if reduce_only:
            body["reduceOnly"] = True
        if price is not None and order_type == OrderType.LIMIT:
            body["price"] = str(price)
        return self._request("POST", "/v5/order/create", body=body)

    def cancel_order(
        self,
        symbol: str,
        order_id: str = "",
        order_link_id: str = "",
        category: str = "linear",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
        }
        if order_id:
            body["orderId"] = order_id
        if order_link_id:
            body["orderLinkId"] = order_link_id
        return self._request("POST", "/v5/order/cancel", body=body)

    def get_open_orders(
        self,
        symbol: str = "",
        category: str = "linear",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category, "limit": limit}
        if symbol:
            params["symbol"] = symbol
        result = self._request("GET", "/v5/order/realtime", params=params)
        items: list[dict[str, Any]] = result.get("list", [])
        return items

    def get_order_history(
        self,
        symbol: str = "",
        category: str = "linear",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category, "limit": limit}
        if symbol:
            params["symbol"] = symbol
        result = self._request("GET", "/v5/order/history", params=params)
        items: list[dict[str, Any]] = result.get("list", [])
        return items

    def get_positions(
        self,
        symbol: str = "",
        category: str = "linear",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        result = self._request("GET", "/v5/position/list", params=params)
        items: list[dict[str, Any]] = result.get("list", [])
        return items

    def get_wallet_balance(
        self,
        account_type: str = "UNIFIED",
        coin: str = "USDT",
    ) -> dict[str, Any]:
        params = {"accountType": account_type, "coin": coin}
        result = self._request("GET", "/v5/account/wallet-balance", params=params)
        return result

    def get_executions(
        self,
        symbol: str = "",
        category: str = "linear",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category, "limit": limit}
        if symbol:
            params["symbol"] = symbol
        result = self._request("GET", "/v5/execution/list", params=params)
        items: list[dict[str, Any]] = result.get("list", [])
        return items

    def get_server_time(self) -> int:
        result = self._request("GET", "/v5/market/time")
        return int(result.get("timeSecond", 0))

    def close(self) -> None:
        self._client.close()
