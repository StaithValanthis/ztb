from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from ztb.execution.bybit_client import BybitClient, ClientConfig
from ztb.execution.errors import ClientAuthError, LiveModeBlockedError
from ztb.execution.models import Mode, OrderSide, OrderType


def test_live_mode_blocked() -> None:
    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.LIVE)
    with pytest.raises(LiveModeBlockedError):
        BybitClient(cfg)


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
def test_cancel_order(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    client.cancel_order(symbol="BTCUSDT", order_id="oid1")
    call_kwargs = mock_instance.request.call_args[1]
    body = json.loads(call_kwargs["content"])
    assert body["orderId"] == "oid1"
    assert body["symbol"] == "BTCUSDT"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_open_orders(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"list": [{"orderId": "oid1"}]}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    orders = client.get_open_orders(symbol="BTCUSDT")
    assert len(orders) == 1
    assert orders[0]["orderId"] == "oid1"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_positions(mock_client_cls: MagicMock) -> None:
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
    positions = client.get_positions(symbol="BTCUSDT")
    assert len(positions) == 1
    assert positions[0]["symbol"] == "BTCUSDT"
    client.close()


@patch("ztb.execution.bybit_client.httpx.Client")
def test_get_wallet_balance(mock_client_cls: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_client_cls.return_value = mock_instance
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"retCode": 0, "result": {"totalEquity": "1000.0"}}
    mock_instance.request.return_value = mock_resp

    cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
    client = BybitClient(cfg)
    result = client.get_wallet_balance()
    assert result["totalEquity"] == "1000.0"
    client.close()
