import asyncio
import threading
import time

import pytest

from app.config import Settings, get_settings
from app.control_plane.budget import Budget, BudgetExceeded
from app.control_plane.executor import ToolExecutor
from app.control_plane.guardian import Guardian
from app.control_plane.policy import PolicyEngine
from app.control_plane.reliability import TransientError
from app.control_plane.timeouts import (
    CancelToken,
    ToolTimeoutError,
    ToolTimeouts,
    run_with_timeouts,
)
from app.control_plane.tool_registry import default_registry
from app.observability.tracing import TraceStore
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "constraints": ["Budget under $10M"]}
FAST = ToolTimeouts(connect_ms=50, read_ms=100, total_ms=200)


# ---- the runner ---------------------------------------------------------------------------------------------
def test_a_fast_tool_returns_its_result_and_errors_propagate_unchanged():
    assert run_with_timeouts(lambda x: x * 2, {"x": 21}, FAST) == 42
    with pytest.raises(ZeroDivisionError):
        run_with_timeouts(lambda: 1 / 0, {}, FAST)


def test_a_slow_sync_tool_times_out_and_the_caller_is_not_held_up():
    t0 = time.monotonic()
    with pytest.raises(ToolTimeoutError, match="timed out after 0.2s"):
        run_with_timeouts(lambda: time.sleep(5), {}, FAST)
    assert time.monotonic() - t0 < 1.0


def test_a_timeout_is_transient_so_it_can_be_retried():
    assert issubclass(ToolTimeoutError, TransientError)


def test_sync_tools_that_take_a_cancel_token_are_told_to_stop():
    stopped = threading.Event()

    def cooperative(cancel: CancelToken):
        for _ in range(100):
            if cancel.cancelled:
                stopped.set()
                return "stopped early"
            time.sleep(0.01)
        return "ran to the end"

    with pytest.raises(ToolTimeoutError):
        run_with_timeouts(cooperative, {}, FAST)
    assert stopped.wait(2.0), "the tool never saw the cancel signal"


def test_cancel_token_check_raises():
    t = CancelToken()
    t.check()
    t.cancel()
    with pytest.raises(ToolTimeoutError):
        t.check()


def test_io_tools_receive_their_connect_read_and_total_limits():
    seen = {}

    def io_tool(host, timeouts: ToolTimeouts):
        seen.update(host=host, timeouts=timeouts)
        return "ok"

    assert run_with_timeouts(io_tool, {"host": "db"}, FAST) == "ok"
    assert (seen["timeouts"].connect_ms, seen["timeouts"].read_ms, seen["timeouts"].total_ms) == (50, 100, 200)


def test_an_async_tool_is_really_cancelled_so_its_cleanup_runs():
    events: list[str] = []

    async def slow_query():
        try:
            events.append("started")
            await asyncio.sleep(30)  # a stuck network read
            events.append("finished")  # must never happen
        except asyncio.CancelledError:
            events.append("cancelled")  # the coroutine really was interrupted
            raise
        finally:
            events.append("connection closed")  # cleanup runs, unlike a thread we merely stopped waiting for

    t0 = time.monotonic()
    with pytest.raises(ToolTimeoutError, match="cancelled"):
        run_with_timeouts(slow_query, {}, FAST)
    assert events == ["started", "cancelled", "connection closed"]
    assert time.monotonic() - t0 < 2.0


def test_an_async_tool_that_finishes_in_time_returns_normally_and_gets_its_limits():
    async def quick(n, timeouts: ToolTimeouts):
        await asyncio.sleep(0.01)
        return n + timeouts.connect_ms

    assert run_with_timeouts(quick, {"n": 1}, FAST) == 51


def test_timeouts_are_capped_by_the_workflow_deadline():
    capped = ToolTimeouts(1000, 3000, 5000).capped(0.25)
    assert (capped.connect_ms, capped.read_ms, capped.total_ms) == (250, 250, 250)
    assert ToolTimeouts(1000, 3000, 5000).capped(None).total_ms == 5000
    assert ToolTimeouts(10, 20, 30).capped(60).total_ms == 30  # a generous deadline changes nothing
    assert ToolTimeouts(1000, 1000, 1000).capped(0.0).total_ms == 1  # never zero: that would mean "no limit" to some clients


# ---- through the executor -----------------------------------------------------------------------------------------
def make_executor(budget=None):
    policy = PolicyEngine.from_file(get_settings().policy_file)
    log = {"guardian_decisions": [], "failures": []}
    trace = TraceStore("wf")
    ex = ToolExecutor(default_registry(), Guardian(policy), budget or Budget(), trace, log)
    return ex, trace, log


ARGS = {"investment": 100.0, "annual_benefit": 50.0, "years": 4}


def test_the_executor_times_out_a_hung_tool_retries_it_then_reports_a_timeout():
    ex, trace, log = make_executor()
    contract = ex.registry.get("calculate_roi")
    contract.timeout_ms, contract.max_retries = 100, 1
    calls = {"n": 0}

    def hung(**kw):
        calls["n"] += 1
        time.sleep(5)

    contract.fn = hung
    t0 = time.monotonic()
    with pytest.raises(ToolTimeoutError):
        ex.call("financial_agent", "calculate_roi", ARGS)
    assert time.monotonic() - t0 < 2.0 and calls["n"] == 2  # tried, retried once, then gave up
    span = trace.spans[0]
    assert span.status == "error" and span.attributes["consultai.outcome"] == "timeout"
    assert span.attributes["consultai.attempts"] == 2 and span.attributes["consultai.timeouts_ms"]["total"] == 100
    assert any(f["type"] == "tool_timeout" and f["limit_ms"] == 100 for f in log["failures"])


def test_a_tool_that_recovers_on_retry_succeeds():
    ex, trace, _ = make_executor()
    contract = ex.registry.get("calculate_roi")
    contract.timeout_ms, contract.max_retries = 150, 2
    calls = {"n": 0}

    def sometimes_slow(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            time.sleep(5)
        return {"roi": 1.0}

    contract.fn = sometimes_slow
    assert ex.call("financial_agent", "calculate_roi", ARGS) == {"roi": 1.0}
    assert trace.spans[0].attributes["consultai.attempts"] == 2 and trace.spans[0].attributes["consultai.outcome"] == "ok"


def test_a_tool_cannot_outlive_the_workflow_deadline():
    ex, trace, _ = make_executor(Budget(max_duration_sec=1))
    contract = ex.registry.get("calculate_roi")
    contract.timeout_ms, contract.max_retries = 60_000, 0  # the tool alone would be allowed a minute
    contract.fn = lambda **kw: time.sleep(10)
    t0 = time.monotonic()
    with pytest.raises(ToolTimeoutError):
        ex.call("financial_agent", "calculate_roi", ARGS)
    assert time.monotonic() - t0 < 3.0 and trace.spans[0].attributes["consultai.timeouts_ms"]["total"] <= 1000


def test_no_tool_call_starts_after_the_deadline_has_passed():
    ex, _, _ = make_executor(Budget(max_duration_sec=0))
    with pytest.raises(BudgetExceeded, match="duration"):
        ex.call("financial_agent", "calculate_roi", ARGS)


# ---- the workflow deadline, end to end -----------------------------------------------------------------------------------
def test_a_run_past_its_deadline_stops_cleanly_and_goes_to_a_human():
    svc = EngagementService(Settings(llm_provider="stub", database_url="sqlite:///:memory:", max_duration_sec=0))
    out = svc.start(**REQ)
    assert out["status"] == "escalated" and "duration budget exceeded" in out["halted_reason"]
    assert out["state"].get("recommendation") is None
    assert any(f["type"] == "budget_exceeded" for f in out["state"].get("failures", [])) or out["halted_reason"]


def test_a_normal_run_is_unaffected_by_the_new_limits():
    svc = EngagementService(Settings(llm_provider="stub", database_url="sqlite:///:memory:"))
    assert svc.start(**REQ)["status"] == "awaiting_approval"
