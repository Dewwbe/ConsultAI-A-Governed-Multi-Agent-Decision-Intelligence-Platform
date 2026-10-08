"""Tool execution with real time limits.

Each tool has three limits: *connect* (establishing a connection), *read* (waiting for data) and *total*
(the whole call, which the executor always enforces). The first two are handed to I/O tools that declare
a `timeouts` parameter; the total is enforced here whatever the tool does.

Cancellation, honestly:
* `async def` tools are run on a dedicated event loop and are cancelled for real when the limit passes:
  the coroutine receives `CancelledError` at its next await, so its `finally` blocks run and sockets close.
* plain sync tools run in a daemon thread. Python cannot kill a thread, so we stop *waiting* at the limit
  (the caller moves on, the call is reported as timed out) and flip a `CancelToken` that tools declaring a
  `cancel` parameter can poll to stop early. A sync tool that ignores the token finishes in the background.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .reliability import TransientError


class ToolTimeoutError(TransientError):
    """The tool did not finish within its limit. Transient: the executor may retry it."""


@dataclass(frozen=True)
class ToolTimeouts:
    connect_ms: int
    read_ms: int
    total_ms: int

    @property
    def total_sec(self) -> float:
        return self.total_ms / 1000

    def capped(self, remaining_sec: float | None) -> ToolTimeouts:
        """Never let a tool outlive the workflow deadline."""
        if remaining_sec is None:
            return self
        cap = max(1, int(remaining_sec * 1000))
        return ToolTimeouts(min(self.connect_ms, cap), min(self.read_ms, cap), min(self.total_ms, cap))


class CancelToken:
    """Cooperative cancellation for sync tools: poll `cancelled` (or call `check`) inside long loops."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self._event.is_set():
            raise ToolTimeoutError("cancelled: time limit reached")


class _AsyncRuntime:
    """One background event loop shared by all async tool calls."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="tool-async-loop")
        self._thread.start()

    def run(self, coro: Any, total_sec: float) -> Any:
        unwound = threading.Event()

        async def runner() -> Any:
            try:
                return await coro
            finally:
                unwound.set()  # fires after the tool's own `finally` blocks, whether it finished or was cancelled

        future = asyncio.run_coroutine_threadsafe(runner(), self._loop)
        try:
            return future.result(timeout=total_sec)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()  # delivers CancelledError into the coroutine at its next await
            # wait for the coroutine to actually unwind (sockets closed, locks released) before reporting
            unwound.wait(2.0)
            raise ToolTimeoutError(f"timed out after {total_sec:g}s (cancelled)") from exc


_runtime: _AsyncRuntime | None = None
_runtime_lock = threading.Lock()


def _async_runtime() -> _AsyncRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = _AsyncRuntime()
        return _runtime


def _accepts(fn: Callable[..., Any], name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def run_with_timeouts(fn: Callable[..., Any], args: dict[str, Any], timeouts: ToolTimeouts) -> Any:
    """Run `fn(**args)` under `timeouts`. Raises ToolTimeoutError (transient) when the total limit passes."""
    kwargs = dict(args)
    if _accepts(fn, "timeouts"):
        kwargs["timeouts"] = timeouts
    if inspect.iscoroutinefunction(fn):
        return _async_runtime().run(fn(**kwargs), timeouts.total_sec)

    token = CancelToken()
    if _accepts(fn, "cancel"):
        kwargs["cancel"] = token
    box: dict[str, Any] = {}
    done = threading.Event()

    def target() -> None:
        try:
            box["value"] = fn(**kwargs)
        except BaseException as exc:  # noqa: BLE001  re-raised on the caller's thread
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=target, daemon=True, name="tool-call").start()
    if not done.wait(timeouts.total_sec):
        token.cancel()
        raise ToolTimeoutError(f"timed out after {timeouts.total_sec:g}s")
    if "error" in box:
        raise box["error"]
    return box["value"]
