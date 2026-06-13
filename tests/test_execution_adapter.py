from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ztb.execution.adapter import DEFAULT_RETRYABLE, ResilientAdapter
from ztb.execution.errors import AdapterFailedError


class TestResilientAdapter:
    def test_successful_execution_returns_result(self) -> None:
        adapter = ResilientAdapter(max_retries=2)
        result = adapter.execute(lambda: 42)
        assert result == 42

    def test_retry_on_retryable_exception_then_succeed(self) -> None:
        call_count = 0

        def flaky() -> int:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("reset")
            return 42

        adapter = ResilientAdapter(max_retries=3)
        result = adapter.execute(flaky)
        assert result == 42
        assert call_count == 3

    def test_non_retryable_exception_raised_immediately(self) -> None:
        adapter = ResilientAdapter(max_retries=3)

        with pytest.raises(ValueError, match="boom"):
            adapter.execute(lambda: (_ for _ in ()).throw(ValueError("boom")))

    def test_adapter_failed_error_when_retries_exhausted(self) -> None:
        adapter = ResilientAdapter(max_retries=3)

        with pytest.raises(AdapterFailedError) as exc_info:
            adapter.execute(lambda: (_ for _ in ()).throw(ConnectionError("still down")))
        assert exc_info.value.last_error is not None
        assert "still down" in str(exc_info.value.last_error)

    def test_adapter_failed_has_last_error(self) -> None:
        adapter = ResilientAdapter(max_retries=2)

        with pytest.raises(AdapterFailedError) as exc_info:
            adapter.execute(lambda: (_ for _ in ()).throw(TimeoutError("timeout")))
        assert isinstance(exc_info.value.last_error, TimeoutError)
        assert "timeout" in str(exc_info.value)

    def test_fallback_returned_when_retries_exhausted(self) -> None:
        adapter = ResilientAdapter(
            max_retries=2,
            fallback=lambda: -1,
        )

        result = adapter.execute(lambda: (_ for _ in ()).throw(ConnectionError("fail")))
        assert result == -1

    def test_fallback_not_invoked_on_success(self) -> None:
        fallback = MagicMock(return_value=-1)
        adapter = ResilientAdapter(max_retries=2, fallback=fallback)

        result = adapter.execute(lambda: 42)
        assert result == 42
        fallback.assert_not_called()

    def test_with_fallback_creates_copy(self) -> None:
        base = ResilientAdapter(max_retries=2)
        assert base._fallback is None

        copied = base.with_fallback(lambda: -1)
        assert copied._fallback is not None
        assert base._fallback is None  # original unchanged

    def test_with_fallback_copy_works(self) -> None:
        base = ResilientAdapter(max_retries=2)

        copied = base.with_fallback(lambda: 99)

        result = copied.execute(lambda: (_ for _ in ()).throw(ConnectionError("fail")))
        assert result == 99

    def test_retry_predicate_customizes_retry_decision(self) -> None:
        def predicate(exc: Exception) -> bool:
            return isinstance(exc, ValueError)

        adapter = ResilientAdapter(max_retries=3, retry_predicate=predicate)

        call_count = 0

        def flaky() -> int:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("retry me")
            return 42

        result = adapter.execute(flaky)
        assert result == 42
        assert call_count == 3

    def test_retry_predicate_rejects_non_matching(self) -> None:
        def predicate(exc: Exception) -> bool:
            return False

        adapter = ResilientAdapter(max_retries=3, retry_predicate=predicate)

        with pytest.raises(ConnectionError):
            adapter.execute(lambda: (_ for _ in ()).throw(ConnectionError("no retry")))

    def test_default_retryable_exceptions(self) -> None:
        assert ConnectionError in DEFAULT_RETRYABLE
        assert TimeoutError in DEFAULT_RETRYABLE
        assert OSError in DEFAULT_RETRYABLE

    def test_invalid_max_retries_raises(self) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            ResilientAdapter(max_retries=0)

    def test_execute_passes_args_and_kwargs(self) -> None:
        adapter = ResilientAdapter(max_retries=1)
        fn = MagicMock(return_value="ok")

        result = adapter.execute(fn, 1, 2, key="val")
        assert result == "ok"
        fn.assert_called_once_with(1, 2, key="val")

    def test_custom_retryable_exceptions(self) -> None:
        adapter = ResilientAdapter(
            max_retries=3,
            retryable_exceptions=(ValueError,),
        )

        call_count = 0

        def flaky() -> int:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("retry")
            return 42

        result = adapter.execute(flaky)
        assert result == 42
        assert call_count == 3

        # ConnectionError is NOT retryable with this config
        with pytest.raises(ConnectionError):
            adapter.execute(lambda: (_ for _ in ()).throw(ConnectionError("no retry")))

    def test_backoff_property(self) -> None:
        from ztb.data.rate_limit import BackoffStrategy

        bs = BackoffStrategy(base_delay=2.0, max_delay=30.0)
        adapter = ResilientAdapter(backoff=bs)
        assert adapter.backoff is bs
        assert adapter.backoff.base_delay == 2.0

    def test_max_retries_property(self) -> None:
        adapter = ResilientAdapter(max_retries=5)
        assert adapter.max_retries == 5

    def test_adapter_failed_error_message(self) -> None:
        error = AdapterFailedError("custom message")
        assert "custom message" in str(error)

    def test_adapter_failed_error_with_last_error(self) -> None:
        cause = ValueError("inner")
        error = AdapterFailedError(last_error=cause)
        assert error.last_error is cause
        assert "inner" in str(error)

    def test_adapter_failed_error_default_message(self) -> None:
        error = AdapterFailedError()
        assert "Adapter operation failed after all retries" in str(error)

    def test_adapter_failed_error_message_with_last_error(self) -> None:
        cause = RuntimeError("oops")
        error = AdapterFailedError("from test", last_error=cause)
        assert error.last_error is cause
        assert "from test" in str(error)
        assert "oops" in str(error)


class TestResilientAdapterBackoffTiming:
    def test_delay_increases_with_attempts(self) -> None:
        adapter = ResilientAdapter(
            max_retries=4,
            retryable_exceptions=(ValueError,),
        )
        backoff = adapter.backoff

        delays = [backoff.delay(i) for i in range(4)]
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1]

    def test_attempt_zero_returns_zero(self) -> None:
        adapter = ResilientAdapter()
        assert adapter.backoff.delay(0) == 0.0


class TestResilientAdapterEdgeCases:
    def test_single_retry_immediate_success(self) -> None:
        adapter = ResilientAdapter(max_retries=1)
        assert adapter.execute(lambda: "ok") == "ok"

    def test_single_retry_fails_immediately(self) -> None:
        adapter = ResilientAdapter(max_retries=1)

        with pytest.raises(AdapterFailedError):
            adapter.execute(lambda: (_ for _ in ()).throw(ConnectionError("fail")))

    def test_single_retry_fallsback(self) -> None:
        adapter = ResilientAdapter(max_retries=1, fallback=lambda: "fallback")

        result = adapter.execute(lambda: (_ for _ in ()).throw(ConnectionError("fail")))
        assert result == "fallback"

    def test_non_retryable_exception_not_caught_by_adapter(self) -> None:
        adapter = ResilientAdapter(
            max_retries=3,
            retryable_exceptions=(ConnectionError,),
        )

        with pytest.raises(RuntimeError):
            adapter.execute(lambda: (_ for _ in ()).throw(RuntimeError("no retry")))

    def test_retry_predicate_with_exception_type_check(self) -> None:
        class CustomTransientError(Exception):
            pass

        class CustomFatalError(Exception):
            pass

        def predicate(exc: Exception) -> bool:
            return isinstance(exc, CustomTransientError)

        adapter = ResilientAdapter(max_retries=3, retry_predicate=predicate)

        call_count = 0

        def flaky() -> int:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise CustomTransientError("transient")
            return 42

        assert adapter.execute(flaky) == 42
        assert call_count == 3

        with pytest.raises(CustomFatalError):
            adapter.execute(lambda: (_ for _ in ()).throw(CustomFatalError("fatal")))


class TestBybitClientIntegration:
    @patch("ztb.execution.bybit_client.httpx.Client")
    def test_client_has_resilient_adapter(self, mock_client_cls: MagicMock) -> None:
        from ztb.execution.bybit_client import BybitClient, ClientConfig
        from ztb.execution.models import Mode

        cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
        client = BybitClient(cfg)
        assert hasattr(client, "resilient_adapter")
        assert isinstance(client.resilient_adapter, ResilientAdapter)
        client.close()

    @patch("ztb.execution.bybit_client.httpx.Client")
    def test_adapter_config_matches_client_config(self, mock_client_cls: MagicMock) -> None:
        from ztb.execution.bybit_client import BybitClient, ClientConfig
        from ztb.execution.models import Mode

        cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO, max_retries=5)
        client = BybitClient(cfg)
        assert client.resilient_adapter.max_retries == 5
        client.close()

    @patch("ztb.execution.bybit_client.httpx.Client")
    def test_backoff_used_for_delays(self, mock_client_cls: MagicMock) -> None:
        from ztb.execution.bybit_client import BybitClient, ClientConfig
        from ztb.execution.models import Mode

        cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
        client = BybitClient(cfg)
        backoff = client.resilient_adapter.backoff
        # Verify backoff produces different delays for different attempts
        assert 0 <= backoff.delay(0) < backoff.delay(1) < backoff.delay(2)
        client.close()

    @patch("ztb.execution.bybit_client.httpx.Client")
    def test_request_still_works_with_adapter_present(
        self, mock_client_cls: MagicMock
    ) -> None:
        from ztb.execution.bybit_client import BybitClient, ClientConfig
        from ztb.execution.models import Mode

        mock_instance = MagicMock()
        mock_client_cls.return_value = mock_instance
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"retCode": 0, "result": {"ok": True}}
        mock_instance.request.return_value = mock_resp

        cfg = ClientConfig(api_key="k", api_secret="s", mode=Mode.DEMO)
        client = BybitClient(cfg)
        result = client._request("GET", "/v5/market/time")
        assert result == {"ok": True}
        client.close()
