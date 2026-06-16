from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from ztb.data.bybit_rest import BackoffStrategy, BybitPublicREST, TokenBucket
from ztb.data.errors import FetchError


@pytest.fixture
def client() -> BybitPublicREST:
    limiter = TokenBucket(capacity=100, refill_rate=100, refill_interval=1.0)
    backoff = BackoffStrategy()
    return BybitPublicREST(
        rate_limiter=limiter, backoff=backoff, timeout=5.0, base_url="https://api-demo.bybit.com"
    )


class TestBybitPublicREST:
    def test_get_kline_success(self, client: BybitPublicREST) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "list": [["1700000000000", "50000", "50100", "49900", "50050", "100", "5000000"]]
            },
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp
        result = client.get_kline(category="linear", symbol="BTCUSDT", interval="60", limit=1)
        assert len(result) == 1
        assert result[0]["start"] == "1700000000000"

    def test_get_kline_timeout(self, client: BybitPublicREST) -> None:
        client._client = MagicMock()
        client._client.request.side_effect = httpx.TimeoutException("timed out")
        with pytest.raises(FetchError, match="timed out"):
            client.get_kline(category="linear", symbol="BTCUSDT", interval="60")

    def test_get_kline_http_error(self, client: BybitPublicREST) -> None:
        client._client = MagicMock()
        client._client.request.side_effect = httpx.HTTPError("connection error")
        with pytest.raises(FetchError, match="HTTP error"):
            client.get_kline(category="linear", symbol="BTCUSDT", interval="60")

    def test_get_kline_non_200(self, client: BybitPublicREST) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        client._client = MagicMock()
        client._client.request.return_value = mock_resp
        with pytest.raises(FetchError, match="HTTP 500"):
            client.get_kline(category="linear", symbol="BTCUSDT", interval="60")

    def test_get_kline_api_error_retcode(self, client: BybitPublicREST) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"retCode": 10001, "retMsg": "invalid symbol"}
        client._client = MagicMock()
        client._client.request.return_value = mock_resp
        with pytest.raises(FetchError, match="retCode=10001"):
            client.get_kline(category="linear", symbol="INVALID", interval="60")

    def test_get_kline_429_retry_then_success(self, client: BybitPublicREST) -> None:
        mock_429 = MagicMock(spec=httpx.Response)
        mock_429.status_code = 429
        mock_200 = MagicMock(spec=httpx.Response)
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "retCode": 0,
            "result": {
                "list": [["1700000000000", "50000", "50100", "49900", "50050", "100", "5000000"]]
            },
        }
        client._client = MagicMock()
        client._client.request.side_effect = [mock_429, mock_200]
        result = client.get_kline(category="linear", symbol="BTCUSDT", interval="60", limit=1)
        assert len(result) == 1

    def test_get_funding_rate_history(self, client: BybitPublicREST) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "retCode": 0,
            "result": {
                "list": [{"symbol": "BTCUSDT", "fundingRate": "0.0001"}],
                "nextPageCursor": "abc123",
            },
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp
        items, cursor = client.get_funding_rate_history(symbol="BTCUSDT")
        assert len(items) == 1
        assert cursor == "abc123"

    def test_get_instruments_info(self, client: BybitPublicREST) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "retCode": 0,
            "result": {"list": [{"symbol": "BTCUSDT", "status": "Trading"}]},
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp
        result = client.get_instruments_info(category="linear", limit=10)
        assert len(result) == 1

    def test_get_server_time(self, client: BybitPublicREST) -> None:
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "retCode": 0,
            "result": {"timeSecond": "1700000000", "timeNano": "1700000000000000000"},
        }
        client._client = MagicMock()
        client._client.request.return_value = mock_resp
        result = client.get_server_time()
        assert "timeSecond" in result

    def test_consecutive_429_raises_fetch_error(self) -> None:
        limiter = TokenBucket(capacity=100, refill_rate=100, refill_interval=1.0)
        backoff = BackoffStrategy()
        c = BybitPublicREST(
            rate_limiter=limiter, backoff=backoff, timeout=5.0,
            base_url="https://api-demo.bybit.com", max_retries=3,
        )
        mock_429 = MagicMock(spec=httpx.Response)
        mock_429.status_code = 429
        c._client = MagicMock()
        c._client.request.return_value = mock_429
        with pytest.raises(FetchError, match="rate limit retries exhausted"):
            c.get_kline(category="linear", symbol="BTCUSDT", interval="60", limit=1)

    def test_retryable_retcode_exhaustion_raises_fetch_error(self) -> None:
        limiter = TokenBucket(capacity=100, refill_rate=100, refill_interval=1.0)
        backoff = BackoffStrategy()
        c = BybitPublicREST(
            rate_limiter=limiter, backoff=backoff, timeout=5.0,
            base_url="https://api-demo.bybit.com", max_retries=2,
        )
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"retCode": 10002, "retMsg": "rate limit"}
        c._client = MagicMock()
        c._client.request.return_value = mock_resp
        with pytest.raises(FetchError, match="rate limit retries exhausted"):
            c.get_kline(category="linear", symbol="BTCUSDT", interval="60", limit=1)

    def test_retryable_retcode_retries(self, client: BybitPublicREST) -> None:
        mock_retryable = MagicMock(spec=httpx.Response)
        mock_retryable.status_code = 200
        mock_retryable.json.side_effect = [
            {"retCode": 10002, "retMsg": "rate limit"},
            {
                "retCode": 0,
                "result": {
                    "list": [
                        ["1700000000000", "50000", "50100", "49900", "50050", "100", "5000000"]
                    ]
                },
            },
        ]
        client._client = MagicMock()
        client._client.request.return_value = mock_retryable
        result = client.get_kline(category="linear", symbol="BTCUSDT", interval="60", limit=1)
        assert len(result) == 1

    def test_http_request_logging(
        self, client: BybitPublicREST, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level("DEBUG")
        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"retCode": 0, "result": {"list": []}}
        client._client = MagicMock()
        client._client.request.return_value = mock_resp
        client.get_kline(category="linear", symbol="BTCUSDT", interval="60", limit=1)
        assert any("HTTP request #1:" in rec.message for rec in caplog.records)
        assert any("HTTP response #1:" in rec.message for rec in caplog.records)

    def test_http_transport_retry(self, client: BybitPublicREST) -> None:
        success_resp = MagicMock(spec=httpx.Response)
        success_resp.status_code = 200
        success_resp.json.return_value = {
            "retCode": 0,
            "result": {
                "list": [["1700000000000", "50000", "50100", "49900", "50050", "100", "5000000"]]
            },
        }
        client._client = MagicMock()
        client._client.request.side_effect = [
            httpx.TimeoutException("attempt 1"),
            httpx.TimeoutException("attempt 2"),
            success_resp,
        ]
        result = client.get_kline(category="linear", symbol="BTCUSDT", interval="60", limit=1)
        assert len(result) == 1
        assert client._client.request.call_count == 3

    def test_http_transport_retry_exhausted(self, client: BybitPublicREST) -> None:
        client._client = MagicMock()
        client._client.request.side_effect = httpx.TimeoutException("always fails")
        with pytest.raises(FetchError, match="timed out"):
            client.get_kline(category="linear", symbol="BTCUSDT", interval="60")

    def test_bybit_rest_client_close(self, client: BybitPublicREST) -> None:
        client._client = MagicMock()
        client.close()
        client._client.close.assert_called_once()
