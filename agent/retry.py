"""Exponential backoff for transient model errors."""

from __future__ import annotations

from collections.abc import Callable

from agent.model_client import TransientModelError


def backoff_delays(max_attempts: int, base_s: float = 0.5, cap_s: float = 8.0) -> list[float]:
    """Delays slept *between* attempts: 0.5, 1.0, 2.0, ... (capped)."""
    return [min(cap_s, base_s * 2**i) for i in range(max_attempts - 1)]


def call_with_retries[T](fn: Callable[[], T], *, max_attempts: int,
                      sleep: Callable[[float], None],
                      on_retry: Callable[[int, Exception, float], None] | None = None) -> T:
    """Call fn, retrying only TransientModelError. Re-raises after the last attempt."""
    delays = backoff_delays(max_attempts)
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except TransientModelError as exc:
            if attempt == max_attempts:
                raise
            delay = delays[attempt - 1]
            if on_retry:
                on_retry(attempt, exc, delay)
            sleep(delay)
    raise AssertionError("unreachable")
