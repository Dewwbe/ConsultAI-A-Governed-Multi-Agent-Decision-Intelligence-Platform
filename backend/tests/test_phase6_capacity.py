import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.config import Settings, get_settings
from app.control_plane.budget import Budget
from app.control_plane.limits import ProviderLimiter, ProviderLimits
from app.control_plane.llm import LLMGateway, LLMUnavailable, ProviderResponse
from app.control_plane.policy import PolicyEngine
from app.control_plane.router import ModelRouter
from app.observability.tracing import TraceStore
from app.security.auth import DevAuthenticator
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail", "constraints": ["Budget under $10M"]}
H = {"X-Dev-User": "u"}


def settings(**over):
    return Settings(llm_provider="stub", database_url="sqlite:///:memory:", **over)


# ---- provider limits in the gateway ------------------------------------------------------------------------------
class Echo:
    name = "azure_openai"

    def __init__(self):
        self.calls = 0

    def complete_json(self, **kw):
        self.calls += 1
        return ProviderResponse({"a": "x"}, "", 10, 10)


SCHEMA = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}, "additionalProperties": False}


def gateway(limiter):
    policy = PolicyEngine.from_file(get_settings().policy_file)
    log = {"failures": []}
    provider = Echo()
    return LLMGateway(ModelRouter(policy), provider, Budget(), TraceStore("wf"), log, limiter=limiter), provider, log


def call(gw):
    return gw.structured(agent="a", task="extraction", prompt="hello", schema=SCHEMA, context={})


def test_model_calls_pass_through_the_providers_limiter():
    lim = ProviderLimiter("azure_openai", ProviderLimits(requests_per_minute=60, tokens_per_minute=60_000, max_concurrent=2))
    gw, provider, _ = gateway(lim)
    for _ in range(3):
        call(gw)
    assert provider.calls == 3 and lim.in_flight == 0 and lim.requests.available < 60


def test_a_call_that_cannot_get_through_the_limit_in_time_becomes_an_escalation_not_a_provider_429():
    lim = ProviderLimiter("azure_openai", ProviderLimits(requests_per_minute=1, tokens_per_minute=60_000, queue_timeout_sec=0.3))
    gw, provider, log = gateway(lim)
    call(gw)  # uses the only request this minute
    with pytest.raises(LLMUnavailable, match="rate limit"):
        call(gw)
    assert provider.calls == 1  # the provider was never hit with the excess call
    types = [f["type"] for f in log["failures"]]
    assert types[-2:] == ["llm_unavailable", "no_provider"] and lim.rejections == 1  # why it failed, then why it could not fail over
    assert log["failures"][-2]["provider"] == "azure_openai"


def test_a_slow_burst_waits_in_line_and_all_calls_complete():
    lim = ProviderLimiter("azure_openai", ProviderLimits(requests_per_minute=600, tokens_per_minute=600_000, max_concurrent=1))
    gw, provider, _ = gateway(lim)
    results, lock = [], threading.Lock()

    def worker():
        out = call(gw)
        with lock:
            results.append(out.stage)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert results == ["initial"] * 6 and provider.calls == 6 and lim.in_flight == 0


# ---- queueing engagements ---------------------------------------------------------------------------------------------
class Gate:
    """Makes the pipeline block until released, so the tests control exactly when runs finish."""

    def __init__(self, svc):
        self.release = threading.Event()
        self.started: list[str] = []
        real = svc.graph.invoke

        def blocking(payload, cfg):
            self.started.append(cfg["configurable"]["thread_id"])
            self.release.wait(10)
            return real(payload, cfg)

        svc.graph.invoke = blocking


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_runs_beyond_the_concurrency_limit_are_queued_then_started_in_order():
    svc = EngagementService(settings(max_concurrent_runs=1, max_queued_runs=5))
    gate = Gate(svc)
    ids = [svc.start(**REQ, wait=False)["workflow_id"] for _ in range(3)]
    assert wait_for(lambda: len(gate.started) == 1)
    status = lambda wid: svc.get(wid)["status"]
    assert [status(i) for i in ids] == ["running", "queued", "queued"]
    positions = [e["data"]["position"] for i in ids for e in svc.events_after(i) if e["type"] == "run_queued"]
    assert positions == [1, 2]
    assert svc.scheduler.snapshot()["queued"] == 2

    gate.release.set()
    for i in ids:
        svc.wait(i, 10)
    assert [status(i) for i in ids] == ["awaiting_approval"] * 3
    assert gate.started == ids  # first in, first out
    for i in ids:  # a queued run still announces its start, after the queue event
        types = [e["type"] for e in svc.events_after(i)]
        assert types.index("run_started") >= 0 and types[-1] == "approval_requested"


def test_a_full_queue_is_refused_with_429_and_leaves_nothing_behind():
    svc = EngagementService(settings(max_concurrent_runs=1, max_queued_runs=1))
    gate = Gate(svc)
    app = FastAPI()
    app.include_router(router)
    app.state.service, app.state.authenticator = svc, DevAuthenticator()
    client = TestClient(app)
    assert client.post("/engagements", params={"wait": "false"}, json=REQ, headers=H).status_code == 200  # running
    assert wait_for(lambda: len(gate.started) == 1)
    assert client.post("/engagements", params={"wait": "false"}, json=REQ, headers=H).json()["status"] == "queued"
    before = client.get("/engagements", headers=H).json()["total"]
    r = client.post("/engagements", params={"wait": "false"}, json=REQ, headers=H)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0 and "too many" in r.json()["detail"]
    assert client.get("/engagements", headers=H).json()["total"] == before  # the refused request created no engagement
    gate.release.set()
    for wid in list(svc._futures):
        svc.wait(wid, 10)
    # once there is room again, new work is accepted
    assert client.post("/engagements", json=REQ, headers=H).status_code == 200


def test_the_deadline_clock_starts_when_the_run_starts_not_while_it_waits():
    svc = EngagementService(settings(max_concurrent_runs=1, max_queued_runs=2))
    gate = Gate(svc)
    first = svc.start(**REQ, wait=False)["workflow_id"]
    second = svc.start(**REQ, wait=False)["workflow_id"]
    from app.workflow.graph import RUNTIMES
    created = RUNTIMES[second].budget.started
    time.sleep(0.4)  # the second run waits in the queue
    gate.release.set()
    svc.wait(first, 10)
    svc.wait(second, 10)
    assert RUNTIMES[second].budget.started >= created + 0.35  # reset when it actually began


def test_queued_runs_do_not_survive_a_restart_and_are_marked_failed():
    from app.persistence.db import Database
    db = Database("sqlite:///:memory:")
    db.add_engagement("wf_q", user_id="u", business_problem="p", industry="", data_classification="public", status="queued")
    assert db.mark_interrupted() == 1 and db.get_engagement("wf_q")["status"] == "failed"


def test_default_limits_come_from_the_policy_file_and_can_be_overridden():
    svc = EngagementService(settings())
    assert (svc.scheduler.max_concurrent, svc.scheduler.max_queued) == (4, 20)
    lim = svc.limiters.for_provider("azure_openai").limits
    assert (lim.requests_per_minute, lim.max_concurrent) == (600, 8)
    assert EngagementService(settings(max_concurrent_runs=2, max_queued_runs=0)).scheduler.max_queued == 0
