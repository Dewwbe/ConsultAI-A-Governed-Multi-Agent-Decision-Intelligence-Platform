"""Per-provider health: circuit breakers and the log of fallbacks.

Every model provider has its own circuit breaker, because one provider being down must not stop calls to
another, and its own recent history of failures. The registry is shared by every engagement (the provider's
health is a fact about the provider, not about one run) and is what the read-only governance API reports.
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

from .reliability import CircuitBreaker


@dataclass(frozen=True)
class FallbackEvent:
    ts: str
    task: str
    agent: str
    from_provider: str
    to_provider: str | None   # None: nothing permitted remained, so the run escalates
    reason: str
    data_classification: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BreakerRegistry:
    def __init__(self, failure_threshold: int = 5, reset_after_sec: float = 30.0):
        self._threshold, self._reset = failure_threshold, reset_after_sec
        self._breakers: dict[str, CircuitBreaker] = {}
        self._last_error: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()

    def get(self, provider: str) -> CircuitBreaker:
        with self._lock:
            if provider not in self._breakers:
                self._breakers[provider] = CircuitBreaker(self._threshold, self._reset)
            return self._breakers[provider]

    def note_error(self, provider: str, message: str) -> None:
        with self._lock:
            self._last_error[provider] = (dt.datetime.now(dt.UTC).isoformat(), message[:300])

    def snapshot(self, providers: list[str] | None = None) -> list[dict[str, Any]]:
        with self._lock:
            names = providers if providers is not None else sorted(self._breakers)
            for n in names:
                self._breakers.setdefault(n, CircuitBreaker(self._threshold, self._reset))
            out = []
            for n in names:
                b = self._breakers[n]
                err = self._last_error.get(n)
                out.append({
                    "provider": n, "state": b.state, "consecutive_failures": b.failures,
                    "failure_threshold": b.threshold, "trips": b.trips,
                    "retry_in_sec": round(max(0.0, b.reset_after - (time.monotonic() - b.opened_at)), 1)
                    if b.opened_at is not None else None,
                    "last_error": err[1] if err else None, "last_error_at": err[0] if err else None})
            return out


class FallbackLog:
    """The most recent fallbacks, newest last. Bounded so a long outage cannot grow memory."""

    def __init__(self, maxlen: int = 200):
        self._events: deque[FallbackEvent] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, event: FallbackEvent) -> None:
        with self._lock:
            self._events.append(event)

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in list(self._events)[-limit:]]

    def __len__(self) -> int:
        return len(self._events)
