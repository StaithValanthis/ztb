from __future__ import annotations

import pytest

from ztb.execution.bybit_client import BybitClient, ClientConfig
from ztb.execution.errors import ClientError
from ztb.execution.models import Mode


def _client() -> BybitClient:
    return BybitClient(ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO))


class _FakeReq:
    def __init__(self) -> None:
        self.calls: list = []

    def __call__(self, method, path, body=None, **kw):
        self.calls.append((method, path, body))
        return {"ok": True}


def test_set_leverage_posts_correct_endpoint_and_body(monkeypatch) -> None:
    c = _client()
    fake = _FakeReq()
    monkeypatch.setattr(c, "_request", fake)
    c.set_leverage("BTCUSDT", 2.0, 2.0)
    method, path, body = fake.calls[0]
    assert method == "POST"
    assert path == "/v5/position/set-leverage"
    assert body["category"] == "linear"
    assert body["symbol"] == "BTCUSDT"
    assert body["buyLeverage"] == "2"
    assert body["sellLeverage"] == "2"


def test_set_leverage_fractional_formatting(monkeypatch) -> None:
    c = _client()
    fake = _FakeReq()
    monkeypatch.setattr(c, "_request", fake)
    c.set_leverage("BTCUSDT", 2.5, 2.5)
    assert fake.calls[0][2]["buyLeverage"] == "2.5"


def test_set_leverage_swallows_not_modified(monkeypatch) -> None:
    c = _client()

    def raise_nm(method, path, body=None, **kw):
        raise ClientError(200, "Set leverage not modified")

    monkeypatch.setattr(c, "_request", raise_nm)
    assert c.set_leverage("BTCUSDT", 2.0, 2.0) == {}


def test_set_leverage_reraises_other_errors(monkeypatch) -> None:
    c = _client()

    def raise_other(method, path, body=None, **kw):
        raise ClientError(400, "insufficient permissions")

    monkeypatch.setattr(c, "_request", raise_other)
    with pytest.raises(ClientError):
        c.set_leverage("BTCUSDT", 2.0, 2.0)
