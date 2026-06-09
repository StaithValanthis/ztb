from __future__ import annotations

import pytest

from ztb.data.bybit_rest import BackoffStrategy, BybitPublicREST, TokenBucket

pytestmark = pytest.mark.network


@pytest.fixture
def client() -> BybitPublicREST:
    limiter = TokenBucket(capacity=10, refill_rate=10, refill_interval=1.0)
    backoff = BackoffStrategy()
    return BybitPublicREST(rate_limiter=limiter, backoff=backoff)


def test_server_time_returns_valid_timestamp(client: BybitPublicREST) -> None:
    result = client.get_server_time()
    assert "timeSecond" in result
    assert isinstance(result["timeSecond"], (int, str))
    ts = int(result["timeSecond"])
    assert ts > 1000000000


def test_btcusdt_kline_returns_bars(client: BybitPublicREST) -> None:
    bars = client.get_kline(category="linear", symbol="BTCUSDT", interval="60", limit=1)
    assert len(bars) >= 1


def test_instruments_info_non_empty(client: BybitPublicREST) -> None:
    instruments = client.get_instruments_info(category="linear", limit=10)
    assert len(instruments) >= 1
