from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from ztb.execution.bybit_client import BybitClient, ClientConfig
from ztb.execution.errors import ClientAuthError, ClientError
from ztb.execution.live_guard import LiveDisarmedError
from ztb.execution.models import Mode, OrderSide, OrderType, TopUpResult


def test_live_mode_blocked_when_disarmed() -> None:
    from ztb.execution.live_guard import LiveGuard

    LiveGuard.disarm()
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.LIVE)
    with pytest.raises(LiveDisarmedError):
        BybitClient(cfg)


def test_live_mode_allowed_when_armed(tmp_path: Path) -> None:
    from ztb.execution.arm_auth import compute_arm_hash
    from ztb.execution.live_guard import LiveGuard

    os.environ[LiveGuard.BOARD_TOKEN_VAR] = "test-token"
    hp = tmp_path / "board-arm-hash"
    hp.write_text(compute_arm_hash("test-token"))
    LiveGuard.arm("1", hash_path=hp)
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.LIVE)
    client = BybitClient(cfg)
    assert client._base_url == "https://api.bybit.com"
    client.close()
    LiveGuard.disarm()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)


def test_demo_mode_ok() -> None:
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    assert client._base_url == "https://api-demo.bybit.com"
    client.close()


def test_signing_golden_vector() -> None:
    cfg = ClientConfig(api_key="test_key", api_secret="test_secret", mode=Mode.DEMO)
    client = BybitClient(cfg)
    ts = "1620000000000"
    method = "POST"
    path = "/v5/order/create"
    body = json.dumps({"symbol": "BTCUSDT", "side": "Buy", "qty": "0.01"})
    sig = client._sign(ts, method, path, body)
    expected_payload = f"{ts}test_key5000{body}"
    expected_sig = hmac.new(b"test_secret", expected_payload.encode(), hashlib.sha256).hexdigest()
    assert sig == expected_sig


def test_sign_different_bodies_different_sigs() -> None:
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    ts = str(int(time.time() * 1000))
    sig1 = client._sign(ts, "POST", "/v5/order/create", '{"qty":"0.01"}')
    sig2 = client._sign(ts, "POST", "/v5/order/create", '{"qty":"0.02"}')
    assert sig1 != sig2


def test_demo_url_pinned() -> None:
    cfg = ClientConfig(mode=Mode.DEMO)
    client = BybitClient(cfg)
    assert "api-demo" in client._base_url
    assert "api.bybit.com" not in client._base_url
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_request_success(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"orderId": "oid1"}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    result = client._request("GET", "/v5/market/time")
    assert result == {"orderId": "oid1"}
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_request_auth_error(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 10003, "retMsg": "invalid api key"}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    with pytest.raises(ClientAuthError):
        client._request("GET", "/v5/market/time")
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_place_order_parameters(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"orderId": "oid1"}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    result = client.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        qty=0.01,
        order_type=OrderType.MARKET,
        order_link_id="test_link_id",
    )
    assert result["orderId"] == "oid1"
    call_kwargs = mock_instance.request.call_args[1]
    body = json.loads(call_kwargs["content"])
    assert body["symbol"] == "BTCUSDT"
    assert body["side"] == "Buy"
    assert body["orderType"] == "Market"
    assert body["orderLinkId"] == "test_link_id"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_retry_on_500(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    fail_resp = MagicMock()
    fail_resp.status_code = 500
    fail_resp.json.return_value = {"retCode": 500, "retMsg": "server error"}
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"retCode": 0, "result": {"ok": True}}
    mock_instance.request.side_effect = [fail_resp, ok_resp]

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=2)
    client = BybitClient(cfg)
    result = client._request("GET", "/v5/market/time")
    assert result == {"ok": True}
    assert mock_instance.request.call_count == 2
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_retry_on_10028_and_recover(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    rate_resp = MagicMock()
    rate_resp.status_code = 200
    rate_resp.json.return_value = {"retCode": 10028, "retMsg": "rate limit"}
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"retCode": 0, "result": {"ok": True}}
    mock_instance.request.side_effect = [rate_resp, ok_resp]

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=2)
    client = BybitClient(cfg)
    result = client._request("GET", "/v5/market/time")
    assert result == {"ok": True}
    assert mock_instance.request.call_count == 2
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_timeout_exception_then_retry(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_instance.request.side_effect = [
        httpx.TimeoutException("timeout"),
        httpx.TimeoutException("timeout"),
        MagicMock(
            status_code=200,
            json=lambda: {"retCode": 0, "result": {"ok": True}},
        ),
    ]

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=3)
    client = BybitClient(cfg)
    result = client._request("GET", "/v5/market/time")
    assert result == {"ok": True}
    assert mock_instance.request.call_count == 3
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_timeout_exception_exhausts_retries(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_instance.request.side_effect = httpx.TimeoutException("always timeout")

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=2)
    client = BybitClient(cfg)
    with pytest.raises(ClientError, match="timeout"):
        client._request("GET", "/v5/market/time")
    assert mock_instance.request.call_count == 2
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_http_status_error_500_retry_then_succeed(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    err_resp = MagicMock(status_code=500)
    fail_exc = httpx.HTTPStatusError("500", request=MagicMock(), response=err_resp)
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"retCode": 0, "result": {"ok": True}}
    mock_instance.request.side_effect = [fail_exc, ok_resp]

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=2)
    client = BybitClient(cfg)
    result = client._request("GET", "/v5/market/time")
    assert result == {"ok": True}
    assert mock_instance.request.call_count == 2
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_http_status_error_400_raises_immediately(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    err_resp = MagicMock(status_code=400)
    exc = httpx.HTTPStatusError("400", request=MagicMock(), response=err_resp)
    mock_instance.request.side_effect = exc

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    with pytest.raises(ClientError):
        client._request("GET", "/v5/market/time")
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_max_retries_on_500_exhausted(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    fail_resp = MagicMock()
    fail_resp.status_code = 500
    fail_resp.json.return_value = {"retCode": 500, "retMsg": "server error"}
    mock_instance.request.return_value = fail_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=2)
    client = BybitClient(cfg)
    with pytest.raises(ClientError, match="server error"):
        client._request("GET", "/v5/market/time")
    assert mock_instance.request.call_count == 2
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_http_429_retries_then_succeeds(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    fail_resp = MagicMock()
    fail_resp.status_code = 429
    fail_resp.json.return_value = {"retCode": 10004, "retMsg": "rate limited"}
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"retCode": 0, "result": {"ok": True}}
    mock_instance.request.side_effect = [fail_resp, ok_resp]

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=2)
    client = BybitClient(cfg)
    result = client._request("GET", "/v5/market/time")
    assert result == {"ok": True}
    assert mock_instance.request.call_count == 2
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_http_429_on_last_attempt_raises_client_error(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    fail_resp = MagicMock()
    fail_resp.status_code = 429
    mock_instance.request.return_value = fail_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=2)
    client = BybitClient(cfg)
    with pytest.raises(ClientError, match="rate limited"):
        client._request("GET", "/v5/market/time")
    assert mock_instance.request.call_count == 2
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_http_429_with_10028_retries_then_succeeds(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    resp_429 = MagicMock()
    resp_429.status_code = 429
    resp_429.json.return_value = {"retCode": 10028, "retMsg": "rate limit"}
    resp_10028 = MagicMock()
    resp_10028.status_code = 200
    resp_10028.json.return_value = {"retCode": 10028, "retMsg": "rate limit"}
    ok_resp = MagicMock()
    ok_resp.status_code = 200
    ok_resp.json.return_value = {"retCode": 0, "result": {"ok": True}}
    mock_instance.request.side_effect = [resp_429, resp_10028, ok_resp]

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=3)
    client = BybitClient(cfg)
    result = client._request("GET", "/v5/market/time")
    assert result == {"ok": True}
    assert mock_instance.request.call_count == 3
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_generic_ret_code_raises(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 11007, "retMsg": "unknown error"}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    with pytest.raises(ClientError, match="unknown error"):
        client._request("GET", "/v5/market/time")
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_place_order_reduce_only(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"orderId": "oid_r"}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    result = client.place_order(
        symbol="BTCUSDT",
        side=OrderSide.SELL,
        qty=0.01,
        order_type=OrderType.MARKET,
        reduce_only=True,
    )
    assert result["orderId"] == "oid_r"
    call_kwargs = mock_instance.request.call_args[1]
    body = json.loads(call_kwargs["content"])
    assert body["reduceOnly"] is True
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_place_order_limit_with_price(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"orderId": "oid_l"}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    result = client.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        qty=0.01,
        order_type=OrderType.LIMIT,
        price=49000.0,
    )
    assert result["orderId"] == "oid_l"
    call_kwargs = mock_instance.request.call_args[1]
    body = json.loads(call_kwargs["content"])
    assert body["price"] == "49000.0"
    assert body["timeInForce"] == "GTC"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_cancel_order_with_order_id(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    client.cancel_order(symbol="BTCUSDT", order_id="ord123")
    call_kwargs = mock_instance.request.call_args[1]
    body = json.loads(call_kwargs["content"])
    assert body["orderId"] == "ord123"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_cancel_order_with_link_id(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    client.cancel_order(symbol="BTCUSDT", order_link_id="link456")
    call_kwargs = mock_instance.request.call_args[1]
    body = json.loads(call_kwargs["content"])
    assert body["orderLinkId"] == "link456"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_open_orders_with_symbol(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"list": [{"orderId": "o1"}]}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    items = client.get_open_orders(symbol="BTCUSDT")
    assert items == [{"orderId": "o1"}]
    call_kwargs = mock_instance.request.call_args[1]
    assert call_kwargs["params"]["symbol"] == "BTCUSDT"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_open_orders_no_symbol(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"list": []}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    items = client.get_open_orders()
    assert items == []
    call_kwargs = mock_instance.request.call_args[1]
    assert "symbol" not in call_kwargs["params"]
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_order_history_with_symbol(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"list": [{"orderId": "h1"}]}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    items = client.get_order_history(symbol="BTCUSDT")
    assert items == [{"orderId": "h1"}]
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_positions_with_symbol(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "retCode": 0,
        "result": {"list": [{"symbol": "BTCUSDT", "size": "0.1"}]},
    }
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    items = client.get_positions(symbol="BTCUSDT")
    assert items == [{"symbol": "BTCUSDT", "size": "0.1"}]
    call_kwargs = mock_instance.request.call_args[1]
    assert call_kwargs["params"]["symbol"] == "BTCUSDT"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_wallet_balance(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"wallet": "info"}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    result = client.get_wallet_balance()
    assert result == {"wallet": "info"}
    call_kwargs = mock_instance.request.call_args[1]
    assert call_kwargs["params"]["accountType"] == "UNIFIED"
    assert call_kwargs["params"]["coin"] == "USDT"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_executions_with_symbol(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"list": [{"execId": "e1"}]}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    items = client.get_executions(symbol="BTCUSDT")
    assert items == [{"execId": "e1"}]
    call_kwargs = mock_instance.request.call_args[1]
    assert call_kwargs["params"]["symbol"] == "BTCUSDT"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_server_time(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"timeSecond": "1234567890"}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    ts = client.get_server_time()
    assert ts == 1234567890
    client.close()


def test_round_to_step() -> None:
    assert BybitClient.round_to_step(0.0026, 0.001) == pytest.approx(0.002)
    assert BybitClient.round_to_step(0.0024, 0.001) == pytest.approx(0.002)
    assert BybitClient.round_to_step(1.29, 0.1) == pytest.approx(1.2)
    assert BybitClient.round_to_step(1.0, 0.5) == pytest.approx(1.0)
    assert BybitClient.round_to_step(0.0, 0.001) == pytest.approx(0.0)
    assert BybitClient.round_to_step(0.0015, 0.001) == pytest.approx(0.001)


def test_round_to_step_zero_step() -> None:
    assert BybitClient.round_to_step(0.5, 0.0) == 0.5


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_instrument_info(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "retCode": 0,
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "lotSizeFilter": {
                        "qtyStep": "0.001",
                        "minOrderQty": "0.001",
                        "maxOrderQty": "1000",
                    },
                }
            ]
        },
    }
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    info = client.get_instrument_info("BTCUSDT")
    assert info["symbol"] == "BTCUSDT"
    assert info["lotSizeFilter"]["qtyStep"] == "0.001"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_instrument_info_cached(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "retCode": 0,
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "lotSizeFilter": {
                        "qtyStep": "0.001",
                        "minOrderQty": "0.001",
                        "maxOrderQty": "1000",
                    },
                },
            ],
        },
    }
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    info1 = client.get_instrument_info("BTCUSDT")
    info2 = client.get_instrument_info("BTCUSDT")
    assert info1 is info2
    assert mock_instance.request.call_count == 1
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_place_order_validates_qty(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance

    info_resp = MagicMock()
    info_resp.status_code = 200
    info_resp.json.return_value = {
        "retCode": 0,
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "lotSizeFilter": {
                        "qtyStep": "0.001",
                        "minOrderQty": "0.001",
                        "maxOrderQty": "1000",
                    },
                },
            ],
        },
    }

    order_resp = MagicMock()
    order_resp.status_code = 200
    order_resp.json.return_value = {"retCode": 0, "result": {"orderId": "oid1"}}

    mock_instance.request.side_effect = [info_resp, order_resp]

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    result = client.place_order(symbol="BTCUSDT", side=OrderSide.BUY, qty=0.002)
    assert result["orderId"] == "oid1"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_validate_qty_below_min_skips(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "retCode": 0,
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "lotSizeFilter": {
                        "qtyStep": "0.001",
                        "minOrderQty": "0.01",
                        "maxOrderQty": "1000",
                    },
                },
            ],
        },
    }
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    result = client.place_order(symbol="BTCUSDT", side=OrderSide.BUY, qty=0.001)
    assert result.get("skipped") is True
    assert "below minOrderQty" in result.get("reason", "")
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_validate_qty_exceeds_max_caps(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance

    info_resp = MagicMock()
    info_resp.status_code = 200
    info_resp.json.return_value = {
        "retCode": 0,
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "lotSizeFilter": {
                        "qtyStep": "1",
                        "minOrderQty": "1",
                        "maxOrderQty": "10",
                    },
                },
            ],
        },
    }

    order_resp = MagicMock()
    order_resp.status_code = 200
    order_resp.json.return_value = {"retCode": 0, "result": {"orderId": "oid_capped"}}

    mock_instance.request.side_effect = [info_resp, order_resp]

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    result = client.place_order(symbol="BTCUSDT", side=OrderSide.BUY, qty=100)
    assert result["orderId"] == "oid_capped"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_http_status_error_503_retry_then_raise(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    err_resp = MagicMock(status_code=503)
    exc = httpx.HTTPStatusError("503", request=MagicMock(), response=err_resp)
    mock_instance.request.side_effect = exc

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=2)
    client = BybitClient(cfg)
    with pytest.raises(ClientError, match="Client error 503"):
        client._request("GET", "/v5/market/time")
    assert mock_instance.request.call_count == 2
    client.close()


def test_live_mode_logs_audit_on_success(tmp_path: Path) -> None:
    from ztb.execution.arm_auth import compute_arm_hash
    from ztb.execution.live_guard import LiveGuard

    os.environ[LiveGuard.BOARD_TOKEN_VAR] = "audit-tkn"
    hp = tmp_path / "board-arm-hash"
    hp.write_text(compute_arm_hash("audit-tkn"))
    LiveGuard.arm("1", hash_path=hp)
    db_path = tmp_path / "test_audit_bybit.db"
    cfg = ClientConfig(
        api_key="test_key",
        api_secret="test_secret",
        mode=Mode.LIVE,
        store_path=db_path,
        arm_source="test_audit",
    )
    with patch("ztb.execution.bybit_client.httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"retCode": 0, "result": {"orderId": "oid_a"}}
        mock_instance.request.return_value = mock_resp
        client = BybitClient(cfg)
        client.place_order(
            symbol="BTCUSDT", side=OrderSide.BUY, qty=0.01, order_type=OrderType.MARKET
        )
        client.close()
    from ztb.store.exec_io import ensure_audit_table, get_audit_log
    from ztb.store.results import connect

    conn = connect(str(db_path))
    ensure_audit_table(conn)
    events = get_audit_log(conn)
    conn.close()
    assert len(events) >= 1
    api_events = [e for e in events if e["event_type"] == "api_call"]
    assert len(api_events) >= 1, "No api_call audit events found"
    assert "POST /v5/order/create: success" in api_events[0]["detail"]
    LiveGuard.disarm()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)


def test_demo_mode_does_not_log_audit(tmp_path: Path) -> None:
    db_path = tmp_path / "test_no_audit_demo.db"
    cfg = ClientConfig(
        api_key="k",
        api_secret="s",
        mode=Mode.DEMO,
        store_path=db_path,
        arm_source="test_demo",
    )
    with patch("ztb.execution.bybit_client.httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"retCode": 0, "result": {"orderId": "oid_d"}}
        mock_instance.request.return_value = mock_resp
        client = BybitClient(cfg)
        client.place_order(
            symbol="BTCUSDT", side=OrderSide.BUY, qty=0.01, order_type=OrderType.MARKET
        )
        client.close()
    from ztb.store.exec_io import ensure_audit_table, get_audit_log
    from ztb.store.results import connect

    conn = connect(str(db_path))
    ensure_audit_table(conn)
    events = get_audit_log(conn)
    conn.close()
    api_events = [e for e in events if e["event_type"] == "api_call"]
    assert len(api_events) == 0, "DEMO mode should not log API audit events"


def test_audit_logged_for_get_wallet_balance_live(tmp_path: Path) -> None:
    from ztb.execution.arm_auth import compute_arm_hash
    from ztb.execution.live_guard import LiveGuard

    os.environ[LiveGuard.BOARD_TOKEN_VAR] = "wallet-tkn"
    hp = tmp_path / "board-arm-hash"
    hp.write_text(compute_arm_hash("wallet-tkn"))
    LiveGuard.arm("1", hash_path=hp)
    db_path = tmp_path / "test_audit_wallet.db"
    cfg = ClientConfig(
        api_key="test_key",
        api_secret="test_secret",
        mode=Mode.LIVE,
        store_path=db_path,
        arm_source="test_wallet",
    )
    with patch("ztb.execution.bybit_client.httpx.Client") as mock_client_cls:
        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "retCode": 0,
            "result": {"wallet": {"totalEquity": "100000"}},
        }
        mock_instance.request.return_value = mock_resp
        client = BybitClient(cfg)
        client.get_wallet_balance()
        client.close()
    from ztb.store.exec_io import ensure_audit_table, get_audit_log
    from ztb.store.results import connect

    conn = connect(str(db_path))
    ensure_audit_table(conn)
    events = get_audit_log(conn)
    conn.close()
    api_events = [e for e in events if e["event_type"] == "api_call"]
    assert len(api_events) >= 1
    assert "GET /v5/account/wallet-balance: success" in api_events[0]["detail"]
    LiveGuard.disarm()
    os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)


# ---------------------------------------------------------------------------
# top_up_demo_account
# ---------------------------------------------------------------------------


def test_top_up_demo_account_calls_api() -> None:
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    with patch.object(client, "_request") as mock_request:
        faucet_resp = {"result": "ok"}
        wallet_resp = {
            "list": [
                {
                    "coin": [
                        {
                            "coin": "USDT",
                            "equity": "50000.0",
                            "walletBalance": "50000.0",
                            "availableBalance": "25000.0",
                        }
                    ]
                }
            ]
        }
        mock_request.side_effect = [faucet_resp, wallet_resp]
        result = client.top_up_demo_account("USDT", "100000")
        assert mock_request.call_count == 2
        assert mock_request.call_args_list[0][0] == ("POST", "/v5/account/demo-apply-money")
        assert mock_request.call_args_list[0][1] == {
            "body": {
                "adjustType": 0,
                "utaDemoApplyMoney": [{"coin": "USDT", "amountStr": "100000"}],
            }
        }
        assert mock_request.call_args_list[1][0] == ("GET", "/v5/account/wallet-balance")
        assert isinstance(result, TopUpResult)
        assert result.success is True
        assert result.credited_amount == 50000.0
        assert result.coin == "USDT"
        assert result.requested_amount == 100000.0
    client.close()


def test_top_up_demo_account_live_mode_skips() -> None:
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.LIVE)
    from ztb.execution.arm_auth import compute_arm_hash
    from ztb.execution.live_guard import LiveGuard

    os.environ[LiveGuard.BOARD_TOKEN_VAR] = "test-token"
    hp = Path("/tmp/test-arm-hash-top-up-live")
    hp.write_text(compute_arm_hash("test-token"))
    LiveGuard.arm("1", hash_path=hp)
    try:
        client = BybitClient(cfg)
        with patch.object(client, "_request") as mock_request:
            result = client.top_up_demo_account("USDT", "100000")
            mock_request.assert_not_called()
            assert isinstance(result, TopUpResult)
            assert result.success is True
            assert result.credited_amount == 0.0
            assert result.coin == "USDT"
        client.close()
    finally:
        LiveGuard.disarm()
        os.environ.pop(LiveGuard.BOARD_TOKEN_VAR, None)
        hp.unlink(missing_ok=True)


def test_top_up_demo_account_exception_returns_empty() -> None:
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    with patch.object(client, "_request") as mock_request:
        mock_request.side_effect = Exception("API error")
        result = client.top_up_demo_account("USDT", "100000")
        assert isinstance(result, TopUpResult)
        assert result.success is False
        assert result.credited_amount == 0.0
        assert "API error" in result.message
    client.close()


def test_top_up_demo_account_verifies_balance() -> None:
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    with patch.object(client, "_request") as mock_request:
        faucet_resp = {"result": "ok"}
        wallet_resp = {
            "list": [
                {
                    "coin": [
                        {
                            "coin": "USDT",
                            "equity": "75000.0",
                            "walletBalance": "75000.0",
                            "availableBalance": "40000.0",
                        }
                    ]
                }
            ]
        }
        mock_request.side_effect = [faucet_resp, wallet_resp]
        result = client.top_up_demo_account("USDT", "100000")
        assert isinstance(result, TopUpResult)
        assert result.success is True
        assert result.credited_amount == 75000.0
        assert result.coin == "USDT"
        assert result.requested_amount == 100000.0
    client.close()


def test_top_up_demo_account_faucet_cap() -> None:
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    with patch.object(client, "_request") as mock_request:
        faucet_resp = {"result": "ok"}
        wallet_resp = {
            "list": [
                {
                    "coin": [
                        {
                            "coin": "USDT",
                            "equity": "100.0",
                            "walletBalance": "100.0",
                            "availableBalance": "50.0",
                        }
                    ]
                }
            ]
        }
        mock_request.side_effect = [faucet_resp, wallet_resp]
        result = client.top_up_demo_account("USDT", "100000")
        assert isinstance(result, TopUpResult)
        assert result.success is True
        assert result.credited_amount == 100.0
        assert result.requested_amount == 100000.0
    client.close()


def test_top_up_demo_account_fails_gracefully() -> None:
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    with patch.object(client, "_request") as mock_request:
        mock_request.side_effect = ClientError(400, "faucet unavailable")
        result = client.top_up_demo_account("USDT", "100000")
        assert isinstance(result, TopUpResult)
        assert result.success is False
        assert result.credited_amount == 0.0
        assert result.requested_amount == 100000.0
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_executions_signs_query_in_sent_order(mock_client_cls: MagicMock) -> None:
    """Regression lock for the get_executions signature bug.

    The GET query string must be signed in the order it is SENT (params-dict
    insertion order), NOT sorted(). A sorted-vs-sent mismatch made Bybit reject
    every execution query with "Error sign" -> 0 real fills (the root cause the
    firm masked with the DEMO synthetic short-circuit, d797575).
    """
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"list": []}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)

    captured: dict[str, str] = {}
    real_sign = client._sign

    def _capture(ts: str, method: str, path: str, body: str) -> str:
        captured["payload"] = body
        return real_sign(ts, method, path, body)

    with patch.object(client, "_sign", side_effect=_capture):
        client.get_executions(symbol="BTCUSDT", order_id="abc-123", category="linear")

    payload = captured["payload"]
    # signed string must match what is SENT (insertion order: symbol before orderId)
    assert "symbol=BTCUSDT&orderId=abc-123" in payload, payload
    # must NOT be alphabetically sorted (orderId before symbol) — that was the bug
    assert "orderId=abc-123&symbol=BTCUSDT" not in payload, payload
