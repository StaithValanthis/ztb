from __future__ import annotations

import random
import time
from collections.abc import Callable


class TokenBucket:
    """Token-bucket rate limiter with injected clock for testability."""

    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        refill_interval: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be > 0")
        if refill_interval <= 0:
            raise ValueError("refill_interval must be > 0")

        self.capacity = capacity
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval
        self._clock = clock or time.time

        self._tokens = float(capacity)
        self._last_refill = self._clock()

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last_refill
        if elapsed >= self.refill_interval:
            n_intervals = elapsed / self.refill_interval
            self._tokens = min(self.capacity, self._tokens + n_intervals * self.refill_rate)
            self._last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def wait_time(self) -> float:
        self._refill()
        if self._tokens >= 1:
            return 0.0
        deficit = 1.0 - self._tokens
        rate = self.refill_rate / self.refill_interval
        return deficit / rate


class BackoffStrategy:
    """Exponential backoff with jitter for HTTP 429 / Bybit retCode handling."""

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        jitter: float = 0.1,
    ) -> None:
        if base_delay <= 0:
            raise ValueError("base_delay must be > 0")
        if max_delay < base_delay:
            raise ValueError("max_delay must be >= base_delay")
        if jitter < 0 or jitter > 1:
            raise ValueError("jitter must be in [0, 1]")

        self.base_delay = base_delay
        self.max_delay = max_delay
        self.jitter = jitter

    def delay(self, attempt: int) -> float:
        if attempt < 0:
            raise ValueError("attempt must be >= 0")
        if attempt == 0:
            return 0.0
        delay = min(self.max_delay, self.base_delay * (2 ** (attempt - 1)))
        jitter_amount = delay * self.jitter * random.random()
        return delay + jitter_amount  # type: ignore[no-any-return]
