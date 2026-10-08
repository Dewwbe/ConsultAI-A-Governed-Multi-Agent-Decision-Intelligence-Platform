"""Rate limiting, concurrency limits and queueing.

* `TokenBucket`: a smooth rate limit with bursts (used for requests/minute and tokens/minute per provider).
* `ProviderLimiter`: requests/minute + tokens/minute + a cap on calls in flight. A caller that cannot get
  in waits in line for up to `queue_timeout_sec`, then is refused (so a stampede degrades into short waits,
  not a flood of 429s from the provider, and never into an unbounded pile-up).
* `RunScheduler`: bounds how many engagements run at once and how many may wait; beyond that it refuses
  immediately so the API can answer 429 with a Retry-After instead of accepting work it cannot do.

The clock and sleep are injectable so the tests are exact and instantaneous.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


class RateLimitTimeout(RuntimeError):
    """Could not get through the limiter within the queue timeout."""


class QueueFull(RuntimeError):
    """The engagement queue is full: try again later."""

    def __init__(self, retry_after_sec: int = 5):
        super().__init__(f"too many engagements in progress; retry in about {retry_after_sec}s")
        self.retry_after_sec = retry_after_sec


class TokenBucket:
    """Refills at `rate_per_sec` up to `capacity`. A request larger than the capacity is clamped to it,
    so an oversized single request can still pass (after a full refill) instead of waiting forever."""

    def __init__(self, rate_per_sec: float, capacity: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        if rate_per_sec <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self.rate, self.capacity = rate_per_sec, capacity
        self._clock, self._sleep = clock, sleep
        self._tokens = capacity
        self._stamp = clock()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._stamp) * self.rate)
        self._stamp = now

    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens

    def try_acquire(self, n: float = 1.0) -> bool:
        n = min(n, self.capacity)
        with self._lock:
            self._refill()
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

    def wait_time(self, n: float = 1.0) -> float:
        n = min(n, self.capacity)
        with self._lock:
            self._refill()
            return max(0.0, (n - self._tokens) / self.rate)

    def acquire(self, n: float = 1.0, timeout: float | None = None) -> float:
        """Block until `n` tokens are available. Returns seconds waited; raises RateLimitTimeout past `timeout`."""
        waited = 0.0
        while not self.try_acquire(n):
            pause = min(self.wait_time(n) or 0.001, 0.5)
            if timeout is not None and waited + pause > timeout:
                raise RateLimitTimeout(f"rate limit: would wait more than {timeout:g}s")
            self._sleep(pause)
            waited += pause
        return waited


@dataclass(frozen=True)
class ProviderLimits:
    requests_per_minute: int = 600
    tokens_per_minute: int = 150_000
    max_concurrent: int = 8
    queue_timeout_sec: float = 20.0


class ProviderLimiter:
    def __init__(self, name: str, limits: ProviderLimits, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.name, self.limits = name, limits
        rpm, tpm = limits.requests_per_minute, limits.tokens_per_minute
        self.requests = TokenBucket(rpm / 60, rpm, clock, sleep)
        self.tokens = TokenBucket(tpm / 60, tpm, clock, sleep)
        self._slots = threading.BoundedSemaphore(limits.max_concurrent)
        self._in_flight = 0
        self._lock = threading.Lock()
        self.waits = 0          # calls that had to queue
        self.rejections = 0     # calls refused after the queue timeout

    @property
    def in_flight(self) -> int:
        return self._in_flight

    @contextmanager
    def slot(self, est_tokens: int = 0):
        """Hold a concurrency slot and spend rate-limit tokens for one provider call."""
        deadline = self.limits.queue_timeout_sec
        started = time.monotonic()
        if not self._slots.acquire(timeout=deadline):
            self.rejections += 1
            raise RateLimitTimeout(f"{self.name}: {self.limits.max_concurrent} calls already in flight")
        try:
            remaining = max(0.0, deadline - (time.monotonic() - started))
            try:
                waited = self.requests.acquire(1, remaining)
                waited += self.tokens.acquire(max(1, est_tokens), max(0.0, remaining - waited))
            except RateLimitTimeout:
                self.rejections += 1
                raise
            if waited > 0:
                self.waits += 1
            with self._lock:
                self._in_flight += 1
            try:
                yield
            finally:
                with self._lock:
                    self._in_flight -= 1
        finally:
            self._slots.release()

    def snapshot(self) -> dict[str, Any]:
        return {"requests_available": round(self.requests.available, 1), "requests_capacity": self.requests.capacity,
                "tokens_available": round(self.tokens.available), "tokens_capacity": self.tokens.capacity,
                "in_flight": self._in_flight, "max_concurrent": self.limits.max_concurrent,
                "queued_calls": self.waits, "rejected_calls": self.rejections}


class LimiterRegistry:
    """One limiter per provider, shared by every engagement, because the provider's limits are global."""

    def __init__(self, config: dict[str, dict[str, Any]] | None = None, default: ProviderLimits | None = None):
        self._config = config or {}
        self._default = default or ProviderLimits()
        self._limiters: dict[str, ProviderLimiter] = {}
        self._lock = threading.Lock()

    def for_provider(self, name: str) -> ProviderLimiter:
        with self._lock:
            if name not in self._limiters:
                cfg = {**self._default.__dict__, **self._config.get(name, {})}
                self._limiters[name] = ProviderLimiter(name, ProviderLimits(**cfg))
            return self._limiters[name]

    def snapshots(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {n: lim.snapshot() for n, lim in self._limiters.items()}


class RunScheduler:
    """At most `max_concurrent` engagements run; up to `max_queued` more wait in order; beyond that we refuse."""

    def __init__(self, max_concurrent: int = 4, max_queued: int = 20):
        self.max_concurrent, self.max_queued = max_concurrent, max_queued
        self._lock = threading.Lock()
        self._running = 0
        self._waiting: deque[tuple[Callable[..., Any], tuple[Any, ...], Future[Any]]] = deque()

    @property
    def running(self) -> int:
        return self._running

    @property
    def queued(self) -> int:
        return len(self._waiting)

    def would_queue(self) -> bool:
        with self._lock:
            return self._running >= self.max_concurrent

    def submit(self, fn: Callable[..., Any], *args: Any) -> tuple[Future[Any], int]:
        """Start `fn` now or queue it. Returns (future, queue position; 0 = started immediately). Raises QueueFull."""
        fut: Future[Any] = Future()
        with self._lock:
            if self._running < self.max_concurrent:
                self._running += 1
                position = 0
            elif len(self._waiting) < self.max_queued:
                self._waiting.append((fn, args, fut))
                return fut, len(self._waiting)
            else:
                raise QueueFull()
        self._start(fn, args, fut)
        return fut, position

    def _start(self, fn: Callable[..., Any], args: tuple[Any, ...], fut: Future[Any]) -> None:
        def work() -> None:
            try:
                fut.set_result(fn(*args))
            except BaseException as exc:  # noqa: BLE001  delivered to whoever waits on the future
                fut.set_exception(exc)
            finally:
                self._next()

        threading.Thread(target=work, daemon=True, name="engagement-run").start()

    def _next(self) -> None:
        with self._lock:
            if self._waiting:
                fn, args, fut = self._waiting.popleft()  # the slot passes straight to the next in line
            else:
                self._running -= 1
                return
        self._start(fn, args, fut)

    def snapshot(self) -> dict[str, int]:
        return {"running": self._running, "queued": len(self._waiting),
                "max_concurrent": self.max_concurrent, "max_queued": self.max_queued}
