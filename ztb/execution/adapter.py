from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar, cast

from ztb.data.rate_limit import BackoffStrategy
from ztb.execution.errors import AdapterFailedError

_R = TypeVar("_R")

__all__ = [
    "ResilientAdapter",
    "DEFAULT_RETRYABLE",
]

DEFAULT_RETRYABLE: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


class ResilientAdapter:
    """Wraps an adapter operation with retry (exponential backoff + jitter) and optional fallback.

    Retries on retryable exceptions with configurable backoff.
    When all retries are exhausted, invokes the fallback (if provided)
    or raises AdapterFailedError.

    Parameters
    ----------
    backoff:
        BackoffStrategy for delay computation. Defaults to exponential with
        base_delay=1.0, max_delay=60.0, jitter=0.1.
    max_retries:
        Maximum number of attempts (including the first). Default 3.
    retryable_exceptions:
        Tuple of exception types that trigger a retry. Defaults to
        (ConnectionError, TimeoutError, OSError).
    fallback:
        Optional callable invoked when all retries are exhausted.
        Its return value is returned as the result of execute().
    clock:
        Injectable clock for testability (e.g., lambda: 0.0).
    """

    def __init__(
        self,
        backoff: BackoffStrategy | None = None,
        max_retries: int = 3,
        retryable_exceptions: tuple[type[Exception], ...] | None = None,
        retry_predicate: Callable[[Exception], bool] | None = None,
        fallback: Callable[[], Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if max_retries < 1:
            raise ValueError("max_retries must be >= 1")

        self._backoff = backoff or BackoffStrategy()
        self._max_retries = max_retries
        self._retryable_exceptions = retryable_exceptions or DEFAULT_RETRYABLE
        self._retry_predicate = retry_predicate
        self._fallback = fallback
        self._clock = clock or time.time

    @property
    def backoff(self) -> BackoffStrategy:
        return self._backoff

    @property
    def max_retries(self) -> int:
        return self._max_retries

    def _is_retryable(self, exc: Exception) -> bool:
        if self._retry_predicate is not None:
            return self._retry_predicate(exc)
        return isinstance(exc, self._retryable_exceptions)

    def with_fallback(self, fallback: Callable[[], Any]) -> ResilientAdapter:
        """Return a copy with the given fallback attached."""
        return ResilientAdapter(
            backoff=self._backoff,
            max_retries=self._max_retries,
            retryable_exceptions=self._retryable_exceptions,
            retry_predicate=self._retry_predicate,
            fallback=fallback,
            clock=self._clock,
        )

    def execute(self, fn: Callable[..., _R], *args: Any, **kwargs: Any) -> _R:
        """Execute *fn(*args, **kwargs)* with retry/backoff and optional fallback.

        Returns the fallback result when all retries are exhausted and a
        fallback is configured.  Raises ``AdapterFailedError`` when all
        retries are exhausted and no fallback exists.
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                if not self._is_retryable(exc):
                    raise
                last_exc = exc
                if attempt < self._max_retries - 1:
                    delay = self._backoff.delay(attempt)
                    time.sleep(delay)

        if self._fallback is not None:
            return cast(_R, self._fallback())
        raise AdapterFailedError(last_error=last_exc)
