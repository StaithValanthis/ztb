from __future__ import annotations

import functools
import random
import sqlite3
import time
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def retry_on_lock(
    max_retries: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: sqlite3.OperationalError | None = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    msg = str(e)
                    if "database is locked" not in msg:
                        raise
                    if attempt == max_retries - 1:
                        raise
                    last_exc = e
                    delay = min(base_delay * (2**attempt), max_delay)
                    jitter = delay * random.uniform(-0.25, 0.25)
                    time.sleep(delay + jitter)
            assert last_exc is not None
            raise last_exc

        return wrapper  # type: ignore[return-value]

    return decorator
