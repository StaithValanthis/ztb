from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ztb.data.rate_limit import BackoffStrategy
from ztb.execution.errors import ClientAuthError, ClientError
from ztb.execution.live_guard import LiveGuard
from ztb.execution.models import (
    Mode,
    OrderSide,
    OrderType,
    TopUpResult,
)
from ztb.utils.balance import extract_top_up_credited

logger = logging.getLogger(__name__)

_DEMO_BASE = "https://api-demo.bybit.com"
_LIVE_BASE = "https://api.bybit.com"
_RECV_WINDOW = "5000"
_DEFAULT_TIMEOUT = 30.0


def round_to_step(qty: float, qty_step: float) -> float:
    if qty_step <= 0:
        return qty
    floored = int(qty / qty_step) * qty_step
    return round(floored, 8)


def ceil_to_step(qty: float, qty_step: float) -> float:
    if qty_step <= 0:
        return qty
    ceiled = -(-qty // qty_step) * qty_step
    return round(float(ceiled), 8)


@dataclass
class ClientConfig:
    api_key: str = ""
    api_secret: str = ""
    mode: Mode = Mode.DEMO
    timeout: float = _DEFAULT_TIMEOUT
    max_retries: int = 3
    store_path: str | Path | None = None
    arm_source: str = ""


class BybitClient:
    def __init__(self, config: ClientConfig, live_guard: type[LiveGuard] = LiveGuard) -> None:
        if config.mode == Mode.LIVE:
            live_guard.assert_live_allowed()
        self._config = config
        self._base_url = _LIVE_BASE if config.mode == Mode.LIVE else _DEMO_BASE
        self._client = httpx.Client(timeout=config.timeout)
        self._backoff_strategy = BackoffStrategy()
        self._time_synced = 0
        if config.mode == Mode.LIVE:
            try:
                self._time_synced = self.get_server_time()
            except Exception:
                self._time_synced = 0
        self._instrument_cache: dict[str, dict[str, Any]] = {}
        self._last_demo_post_ts: float = 0.0
        self._demo_faucet_cooldown: float = 60.0

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
        live_guard: type[LiveGuard] | None = None,
    ) -> dict[str, Any]:
        if live_guard is not None and self._config.mode == Mode.LIVE:
            live_guard.assert_live_allowed()
        url = f"{self._base_url}{path}"
        ts = str(int(time.time() * 1000))
        body_str = json.dumps(body) if body else ""
        if method.upper() == "GET" and params:
            sign_payload = "&".join(f"{k}={v}" for k, v in params.items())
        else:
            sign_payload = body_str
        sig = self._sign(ts, method, path, sign_payload)
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
                if resp.status_code == 429:
                    if attempt < self._config.max_retries - 1:
                        delay = self._backoff_strategy.delay(attempt + 1)
                        time.sleep(delay)
                        continue
                    raise ClientError(429, resp.text[:200])
                if resp.status_code >= 500 and attempt < self._config.max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                data: dict[str, Any] = resp.json()
                ret_code = data.get("retCode", -1)
                ret_msg = data.get("retMsg", "")
                result_preview = str(data.get("result", {}))[:200]
                logger.debug(
                    "%s %s \u2192 retCode=%s retMsg=%s result=%s",
                    method,
                    path,
                    ret_code,
                    ret_msg,
                    result_preview,
                )
                if ret_code == 0:
                    result: dict[str, Any] = data.get("result", {})
                    if self._config.mode == Mode.LIVE:
                        self._log_audit("api_call", f"{method} {path}: success")
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
        take_profit: float | None = None,
        stop_loss: float | None = None,
        category: str = "linear",
    ) -> dict[str, Any]:
        validated = self._validate_qty(symbol, qty, category)
        if validated.get("skipped"):
            if self._config.mode == Mode.DEMO:
                logger.info(
                    "place_order SKIPPED: symbol=%s side=%s reason=%s",
                    symbol,
                    side,
                    validated.get("reason", ""),
                )
            return validated
        qty = validated["qty"]
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
        if take_profit is not None:
            body["takeProfit"] = str(take_profit)
        if stop_loss is not None:
            body["stopLoss"] = str(stop_loss)
        result = self._request("POST", "/v5/order/create", body=body)
        if self._config.mode == Mode.DEMO:
            order_id = result.get("orderId", "N/A")
            logger.info(
                "place_order DEMO: symbol=%s side=%s qty=%s order_link_id=%s orderId=%s",
                symbol,
                side,
                qty,
                order_link_id,
                order_id,
            )
        return result

    def set_leverage(
        self,
        symbol: str,
        buy_leverage: float,
        sell_leverage: float,
        category: str = "linear",
    ) -> dict[str, Any]:
        """Set position leverage on the exchange.

        Swallows Bybit "leverage not modified" (retCode 110043) as a success
        no-op so repeated calls with the same value are harmless.
        """

        def _fmt(v: float) -> str:
            return str(int(v)) if float(v).is_integer() else str(v)

        body = {
            "category": category,
            "symbol": symbol,
            "buyLeverage": _fmt(buy_leverage),
            "sellLeverage": _fmt(sell_leverage),
        }
        try:
            return self._request("POST", "/v5/position/set-leverage", body=body)
        except ClientError as exc:
            msg = str(exc).lower()
            if "not modified" in msg or "110043" in msg:
                logger.info("set_leverage no-op (already %s) for %s", buy_leverage, symbol)
                return {}
            raise

    def set_trading_stop(
        self,
        symbol: str,
        side: OrderSide,
        position_size: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        sl_trigger_by: str = "LastPrice",
        tp_trigger_by: str = "LastPrice",
        trailing_stop: float = 0.0,
        active_price: float = 0.0,
        category: str = "linear",
    ) -> dict[str, Any]:
        """Set or clear SL/TP on an open position.

        Delegates HTTP + retry/auth/rate-limit handling to ``_request``,
        which raises ``ClientAuthError`` on auth failures (retCode 10002/10003/10004),
        retries on rate-limit (10028) and 5xx, and raises ``ClientError`` for
        all other API errors.  Callers should catch ``ClientError`` for graceful
        degradation.
        """
        body: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "side": side.value,
            "positionIdx": 0,
        }
        if stop_loss > 0.0:
            body["stopLoss"] = str(stop_loss)
        else:
            body["stopLoss"] = ""
        if take_profit > 0.0:
            body["takeProfit"] = str(take_profit)
        else:
            body["takeProfit"] = ""
        if sl_trigger_by:
            body["slTriggerBy"] = sl_trigger_by
        if tp_trigger_by:
            body["tpTriggerBy"] = tp_trigger_by
        if trailing_stop > 0.0:
            body["trailingStop"] = str(trailing_stop)
        if active_price > 0.0:
            body["activePrice"] = str(active_price)
        return self._request("POST", "/v5/position/trading-stop", body=body)

    def get_active_trading_stops(
        self,
        symbol: str = "",
        category: str = "linear",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        result = self._request("GET", "/v5/position/list", params=params)
        items: list[dict[str, Any]] = result.get("list", [])
        filtered: list[dict[str, Any]] = []
        for pos in items:
            sl = pos.get("stopLoss", "0")
            tp = pos.get("takeProfit", "0")
            try:
                sl_val = float(sl) if sl else 0.0
                tp_val = float(tp) if tp else 0.0
            except (ValueError, TypeError):
                sl_val = 0.0
                tp_val = 0.0
            if abs(sl_val) > 1e-12 or abs(tp_val) > 1e-12:
                filtered.append(pos)
        return filtered

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
        order_id: str = "",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category, "limit": limit}
        if symbol:
            params["symbol"] = symbol
        if order_id:
            params["orderId"] = order_id
        result = self._request("GET", "/v5/execution/list", params=params)
        items: list[dict[str, Any]] = result.get("list", [])
        return items

    def get_server_time(self) -> int:
        result = self._request("GET", "/v5/market/time")
        return int(result.get("timeSecond", 0))

    def get_instrument_info(
        self,
        symbol: str,
        category: str = "linear",
    ) -> dict[str, Any]:
        cache_key = f"{category}:{symbol}"
        if cache_key in self._instrument_cache:
            return self._instrument_cache[cache_key]
        result = self._request(
            "GET",
            "/v5/market/instruments-info",
            params={"category": category, "symbol": symbol},
        )
        items: list[dict[str, Any]] = result.get("list", [])
        info = items[0] if items else {}
        self._instrument_cache[cache_key] = info
        return info

    @staticmethod
    def round_to_step(qty: float, qty_step: float) -> float:
        return round_to_step(qty, qty_step)

    @staticmethod
    def ceil_to_step(qty: float, qty_step: float) -> float:
        return ceil_to_step(qty, qty_step)

    def get_lot_size_filter(self, symbol: str, category: str = "linear") -> dict[str, Any]:
        info = self.get_instrument_info(symbol, category)
        ls: dict[str, Any] = info.get("lotSizeFilter", {})
        return ls

    def get_qty_step(self, symbol: str, category: str = "linear") -> float:
        ls = self.get_lot_size_filter(symbol, category)
        return float(ls.get("qtyStep", "0.001"))

    def get_min_order_qty(self, symbol: str, category: str = "linear") -> float:
        ls = self.get_lot_size_filter(symbol, category)
        return float(ls.get("minOrderQty", "0"))

    def get_price_filter(self, symbol: str, category: str = "linear") -> dict[str, Any]:
        info = self.get_instrument_info(symbol, category)
        pf: dict[str, Any] = info.get("priceFilter", {})
        return pf

    def get_tick_size(self, symbol: str, category: str = "linear") -> float:
        pf = self.get_price_filter(symbol, category)
        return float(pf.get("tickSize", "0.1"))

    def _validate_qty(self, symbol: str, qty: float, category: str = "linear") -> dict[str, Any]:
        info = self.get_instrument_info(symbol, category)
        ls = info.get("lotSizeFilter", {})
        qty_step = float(ls.get("qtyStep", "0.001"))
        min_qty = float(ls.get("minOrderQty", "0"))
        max_qty = float(ls.get("maxOrderQty", "0"))

        orig_qty = qty
        qty = self.round_to_step(qty, qty_step)

        # When round_to_step floors to 0 but orig_qty > 0, try ceil_to_step
        if qty < 1e-12 and orig_qty > 1e-12:
            ceiled = self.ceil_to_step(orig_qty, qty_step)
            if ceiled >= min_qty - 1e-12:
                qty = ceiled
            else:
                return {
                    "skipped": True,
                    "reason": (
                        f"Qty {orig_qty} ceiled to {ceiled} but still below"
                        f" minOrderQty {min_qty} for {symbol}"
                    ),
                }

        if qty < min_qty - 1e-12:
            return {
                "skipped": True,
                "reason": f"Qty {qty} below minOrderQty {min_qty} for {symbol}",
            }
        if max_qty > 0 and qty > max_qty + 1e-12:
            qty = self.round_to_step(max_qty, qty_step)
        return {"skipped": False, "qty": qty}

    def _log_audit(self, event_type: str, detail: str) -> None:
        store_path = self._config.store_path
        if not store_path:
            return
        source = self._config.arm_source or "BybitClient"
        from ztb.store.exec_io import ensure_audit_table, log_audit_event
        from ztb.store.results import connect_live

        try:
            conn = connect_live(str(store_path))
            ensure_audit_table(conn)
            log_audit_event(conn, event_type=event_type, source=source, detail=detail)
            conn.close()
        except Exception:
            pass

    def top_up_demo_account(self, coin: str, amount: str) -> TopUpResult:
        if self._config.mode != Mode.DEMO:
            return TopUpResult(
                success=True,
                credited_amount=0.0,
                coin=coin,
                requested_amount=float(amount),
                message="LIVE mode — no-op",
            )
        now = time.time()
        elapsed = now - self._last_demo_post_ts
        if elapsed < self._demo_faucet_cooldown:
            remaining = self._demo_faucet_cooldown - elapsed
            logger.info(
                "Demo top-up skipped — cooldown active (%.1fs remaining)",
                remaining,
            )
            return TopUpResult(
                success=True,
                credited_amount=0.0,
                coin=coin,
                requested_amount=float(amount),
                message=f"Cooldown active — {remaining:.1f}s remaining",
            )
        requested = float(amount)
        try:
            body = {
                "adjustType": 0,
                "utaDemoApplyMoney": [
                    {
                        "coin": coin,
                        "amountStr": str(
                            int(requested) if requested == int(requested) else requested
                        ),
                    }
                ],
            }
            self._request("POST", "/v5/account/demo-apply-money", body=body)
            self._last_demo_post_ts = time.time()
            wallet = self.get_wallet_balance(coin=coin)
            credited = extract_top_up_credited(wallet, coin)
            logger.info(
                "Demo account credited: %s %s (requested %s)",
                credited,
                coin,
                amount,
            )
            return TopUpResult(
                success=True,
                credited_amount=credited,
                coin=coin,
                requested_amount=requested,
                message=f"Credited {credited} {coin}",
            )
        except Exception as exc:
            return TopUpResult(
                success=False,
                credited_amount=0.0,
                coin=coin,
                requested_amount=requested,
                message=str(exc),
            )

    def close(self) -> None:
        self._client.close()
