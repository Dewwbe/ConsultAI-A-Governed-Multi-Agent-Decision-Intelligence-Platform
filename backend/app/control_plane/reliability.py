"""Reliability manager: error classification, backoff with jitter, circuit breaker."""
from __future__ import annotations

import random
import time
from collections.abc import Callable
from enum import Enum
from typing import TypeVar

T = TypeVar("T")


class ErrorClass(str, Enum):
    TRANSIENT = "transient"   # timeouts, 429, 5xx -> retry
    PERMANENT = "permanent"   # validation, permission -> block / human review
    QUALITY = "quality"       # low groundedness etc. -> fallback model / review


class TransientError(Exception):
    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


class PermanentError(Exception):
    pass


class CircuitOpen(RuntimeError):
    pass


def classify(exc: Exception) -> ErrorClass:
    if isinstance(exc, (TransientError, TimeoutError, ConnectionError)):
        return ErrorClass.TRANSIENT
    return ErrorClass.PERMANENT


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_after_sec: float = 30.0):
        self.threshold = failure_threshold
        self.reset_after = reset_after_sec
        self.failures = 0
        self.opened_at: float | None = None
        self.trips = 0  # how many times it has opened

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half_open" if time.monotonic() - self.opened_at >= self.reset_after else "open"

    def before_call(self) -> None:
        if self.opened_at is None:
            return
        if time.monotonic() - self.opened_at >= self.reset_after:
            self.opened_at = None  # half-open: allow a trial call
            self.failures = self.threshold - 1
            return
        raise CircuitOpen("circuit open")

    def on_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def on_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            if self.opened_at is None:
                self.trips += 1
            self.opened_at = time.monotonic()


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 20.0,
                  retry_after: float | None = None) -> float:
    if retry_after is not None:
        return min(retry_after, cap)
    return random.uniform(0, min(cap, base * 2 ** attempt))  # full jitter


def call_with_retry(fn: Callable[[], T], *, max_attempts: int = 3,
                    breaker: CircuitBreaker | None = None,
                    sleep: Callable[[float], None] = time.sleep) -> T:
    last: Exception | None = None
    for attempt in range(max_attempts):
        if breaker:
            breaker.before_call()
        try:
            result = fn()
            if breaker:
                breaker.on_success()
            return result
        except Exception as exc:
            last = exc
            if breaker:
                breaker.on_failure()
            if classify(exc) is not ErrorClass.TRANSIENT or attempt == max_attempts - 1:
                raise
            sleep(backoff_delay(attempt, retry_after=getattr(exc, "retry_after", None)))
    raise last  # pragma: no cover
