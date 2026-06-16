from __future__ import annotations

import pytest

from ztb.data.rate_limit import BackoffStrategy, TokenBucket


class TestTokenBucket:
    def test_consume_allows_within_capacity(self) -> None:
        clock = iter([0.0, 0.0, 0.0, 0.0])
        bucket = TokenBucket(
            capacity=5, refill_rate=5, refill_interval=1.0, clock=lambda: next(clock)
        )
        assert bucket.consume(5)
        assert not bucket.consume(1)

    def test_refill_over_time(self) -> None:
        times = [0.0, 0.0, 0.5, 0.5, 0.5]
        clock = iter(times)
        bucket = TokenBucket(
            capacity=5, refill_rate=5, refill_interval=1.0, clock=lambda: next(clock)
        )
        bucket.consume(5)
        assert not bucket.consume(1)
        t = bucket.wait_time()
        assert t > 0

    def test_consume_returns_false_when_empty(self) -> None:
        clock = iter([0.0, 0.0, 0.0])
        bucket = TokenBucket(
            capacity=1, refill_rate=1, refill_interval=1.0, clock=lambda: next(clock)
        )
        assert bucket.consume(1)
        assert not bucket.consume(1)

    def test_wait_time_returns_zero_when_tokens_available(self) -> None:
        clock = iter([0.0, 0.0])
        bucket = TokenBucket(
            capacity=5, refill_rate=5, refill_interval=1.0, clock=lambda: next(clock)
        )
        assert bucket.wait_time() == 0.0

    def test_invalid_capacity_raises(self) -> None:
        with pytest.raises(ValueError, match="capacity"):
            TokenBucket(capacity=0, refill_rate=1, refill_interval=1.0)

    def test_invalid_refill_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="refill_rate"):
            TokenBucket(capacity=5, refill_rate=0, refill_interval=1.0)

    def test_invalid_refill_interval_raises(self) -> None:
        with pytest.raises(ValueError, match="refill_interval"):
            TokenBucket(capacity=5, refill_rate=5, refill_interval=0)

    def test_tokenbucket_no_busy_spin(self) -> None:
        import time as _time

        bucket = TokenBucket(capacity=10, refill_rate=10, refill_interval=1.0)
        for _ in range(10):
            bucket.consume(1)
        assert not bucket.consume(1)
        deadline = _time.monotonic() + 1.5
        got_token = False
        while _time.monotonic() < deadline:
            if bucket.consume(1):
                got_token = True
                break
            _time.sleep(0.01)
        assert got_token, "Should have refilled a token within 1.5s"


class TestBackoffStrategy:
    def test_delay_attempt_zero(self) -> None:
        backoff = BackoffStrategy()
        assert backoff.delay(0) == 0.0

    def test_delay_increases_exponentially(self) -> None:
        backoff = BackoffStrategy(base_delay=1.0, max_delay=60.0, jitter=0.0)
        d1 = backoff.delay(1)
        d2 = backoff.delay(2)
        d3 = backoff.delay(3)
        assert d1 == 1.0
        assert d2 == 2.0
        assert d3 == 4.0

    def test_delay_capped_at_max(self) -> None:
        backoff = BackoffStrategy(base_delay=1.0, max_delay=10.0, jitter=0.0)
        d = backoff.delay(10)
        assert d == 10.0

    def test_jitter_adds_variation(self) -> None:
        import random

        random.seed(42)
        backoff = BackoffStrategy(base_delay=1.0, max_delay=60.0, jitter=0.5)
        d1 = backoff.delay(1)
        assert d1 >= 1.0
        assert d1 <= 1.5

    def test_invalid_base_delay_raises(self) -> None:
        with pytest.raises(ValueError, match="base_delay"):
            BackoffStrategy(base_delay=0)

    def test_invalid_max_delay_raises(self) -> None:
        with pytest.raises(ValueError, match="max_delay"):
            BackoffStrategy(base_delay=5.0, max_delay=1.0)

    def test_invalid_jitter_raises(self) -> None:
        with pytest.raises(ValueError, match="jitter"):
            BackoffStrategy(jitter=1.5)

    def test_invalid_attempt_raises(self) -> None:
        backoff = BackoffStrategy()
        with pytest.raises(ValueError, match="attempt"):
            backoff.delay(-1)
