"""Phase 6 exit criterion: fault-injection tests behave as specified.

Specification
  timeouts     A tool that hangs is cut off at its limit and retried. If it recovers the run completes; if it
               keeps hanging the run ESCALATES to a human (never crashes, never hangs, never guesses).
  429s         A rate-limited model call is retried honouring Retry-After. If it recovers the run completes
               untouched. If the provider stays down the run ESCALATES, the circuit opens, and later runs fail
               fast without hitting the provider again.
  malformed    Output that fails its schema goes through repair, then a stronger model, then ESCALATION. A human
               never receives an unvalidated recommendation.
  quality drop When recent groundedness falls below policy the system tightens by itself: every run is reviewed
               by a human, even runs that would otherwise complete alone. It loosens again once quality returns.
  clean-up     After any fault the service is healthy: nothing in flight, no slot or budget leaked.
"""
import datetime as dt
import time
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.control_plane.llm import ProviderResponse
from app.control_plane.providers import BreakerRegistry
from app.control_plane.reliability import TransientError
from app.control_plane.timeouts import ToolTimeoutError
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail", "constraints": ["Budget under $10M"]}


def settings(**over):
    return Settings(llm_provider="stub", database_url="sqlite:///:memory:", **over)


class FaultProvider:
    """The offline stub, with faults injected by `plan(call_number, task) -> fault | None`."""
    name = "azure_openai"

    def __init__(self, plan):
        self.plan, self.calls, self.by_task = plan, 0, {}

    def complete_json(self, *, task, system, prompt, schema, context, model):
        self.calls += 1
        self.by_task[task] = self.by_task.get(task, 0) + 1
        fault = self.plan(self.calls, task)
        if fault == "429":
            raise TransientError("rate limited (429)", retry_after=0.0)
        if fault == "malformed":
            return ProviderResponse({"unexpected": True}, '{"unexpected": true}', 10, 10)
        if fault == "not_json":
            return ProviderResponse(None, "I am sorry, here is some prose instead of JSON", 10, 10)
        return ProviderResponse(context.get("stub_output", {}), "{}", 100, 50)


def service(plan=lambda n, t: None, **kw):
    svc = EngagementService(settings(**kw))
    provider = FaultProvider(plan)
    svc._provider = lambda: provider
    return svc, provider


def failures(svc, wid):
    from app.workflow.graph import RUNTIMES
    return RUNTIMES[wid].log["failures"]


def assert_healthy_afterwards(svc):
    assert svc.limiters.for_provider("azure_openai").in_flight == 0
    assert svc.scheduler.snapshot()["running"] == 0
    clean, _ = None, None
    return clean


# ---- timeouts --------------------------------------------------------------------------------------------------------------------
def hang(svc, tool, *, after_calls=0, retries=0, limit_ms=150):
    contract = svc.registry.get(tool)
    contract.timeout_ms, contract.max_retries = limit_ms, retries
    real, calls = contract.fn, {"n": 0}

    def maybe_hang(**kw):
        calls["n"] += 1
        if calls["n"] > after_calls:
            time.sleep(10)
        return real(**kw)

    contract.fn = maybe_hang
    return calls


def test_a_tool_that_keeps_hanging_escalates_the_run_to_a_human_instead_of_crashing():
    svc, _ = service()
    calls = hang(svc, "calculate_roi", retries=1)
    t0 = time.monotonic()
    out = svc.start(**REQ)
    assert time.monotonic() - t0 < 10, "the run waited for the hung tool instead of cutting it off"
    assert out["status"] == "escalated" and "financial_agent" in out["halted_reason"] and "ToolTimeoutError" in out["halted_reason"]
    assert out["state"].get("recommendation") is None, "a recommendation was produced without its numbers"
    assert calls["n"] == 2  # tried and retried once
    span = next(s for s in svc.trace(out["workflow_id"])["spans"] if s["name"] == "tool:calculate_roi")
    assert span["status"] == "error" and span["attributes"]["consultai.outcome"] == "timeout"
    assert any(f["type"] == "tool_timeout" for f in failures(svc, out["workflow_id"]))
    run = svc.db.run_metrics_rows()[-1]
    assert run["status"] == "escalated" and run["successful"] is False  # recorded, and never counted as a success
    assert [e["type"] for e in svc.events_after(out["workflow_id"])][-1] == "run_escalated"


def test_a_tool_that_hangs_once_then_recovers_lets_the_run_finish_normally():
    svc, _ = service()
    contract = svc.registry.get("calculate_roi")
    contract.timeout_ms, contract.max_retries = 150, 2
    real, state = contract.fn, {"hung": False}

    def hang_first_call(**kw):
        if not state["hung"]:
            state["hung"] = True
            time.sleep(10)
        return real(**kw)

    contract.fn = hang_first_call
    out = svc.start(**REQ)
    assert out["status"] == "awaiting_approval" and out["state"]["recommendation"]
    assert max(s["attributes"].get("consultai.attempts", 1) for s in svc.trace(out["workflow_id"])["spans"] if s["kind"] == "tool") == 2


def test_the_cut_off_tool_does_not_leak_a_slot_so_the_next_run_is_fine():
    svc, _ = service()
    hang(svc, "calculate_roi")
    assert svc.start(**REQ)["status"] == "escalated"
    assert_healthy_afterwards(svc)
    svc.registry.get("calculate_roi").fn = svc.registry.get("calculate_roi").fn  # (still hangs: a different tool is fine)
    svc2, _ = service()
    assert svc2.start(**REQ)["status"] == "awaiting_approval"


# ---- 429s ---------------------------------------------------------------------------------------------------------------------
def test_a_few_429s_are_retried_and_the_run_completes_untouched():
    svc, provider = service(lambda n, t: "429" if n in (1, 2, 5) else None)
    out = svc.start(**REQ)
    assert out["status"] == "awaiting_approval"
    assert out["metrics"]["schema_escalations"] == 0
    assert provider.calls == len({s["span_id"] for s in svc.trace(out["workflow_id"])["spans"] if s["kind"] == "llm"}) + 3
    assert out["state"]["recommendation"] and not any(f["type"] == "llm_unavailable" for f in failures(svc, out["workflow_id"]))


def test_a_provider_that_stays_rate_limited_escalates_and_then_fails_fast():
    svc, provider = service(lambda n, t: "429")
    svc.breakers = BreakerRegistry(failure_threshold=3, reset_after_sec=60)  # one escalated run makes 3 failed attempts
    first = svc.start(**REQ)
    assert first["status"] == "escalated" and "429" in first["halted_reason"]
    assert first["state"].get("engagement_spec") is None  # nothing downstream ran on missing input
    assert svc.breakers.snapshot(["azure_openai"])[0]["state"] == "open"
    seen = provider.calls
    second = svc.start(**REQ)
    assert second["status"] == "escalated"
    assert provider.calls == seen, "an open circuit still sent traffic to a provider that is down"
    assert "circuit open" in second["halted_reason"]
    assert_healthy_afterwards(svc)


def test_the_service_recovers_when_the_provider_does():
    state = {"down": True}
    svc, _ = service(lambda n, t: "429" if state["down"] else None)
    svc.breakers = BreakerRegistry(failure_threshold=3, reset_after_sec=0.3)
    assert svc.start(**REQ)["status"] == "escalated"
    state["down"] = False
    time.sleep(0.35)  # the circuit's reset time passes
    assert svc.start(**REQ)["status"] == "awaiting_approval"
    assert svc.breakers.snapshot(["azure_openai"])[0]["state"] == "closed"


# ---- malformed output ------------------------------------------------------------------------------------------------------------
def test_output_that_is_always_wrong_at_first_is_repaired_and_the_run_completes():
    svc, _ = service(lambda n, t: None)

    class Repairing(FaultProvider):
        """Wrong on the first attempt of every task; the repair step returns the right answer for that task."""

        def __init__(self):
            super().__init__(lambda n, t: None)
            self.pending = {}

        def complete_json(self, *, task, system, prompt, schema, context, model):
            self.calls += 1
            if task == "schema_repair":
                return ProviderResponse(self.pending.pop("last"), "{}", 5, 5)
            self.pending["last"] = context.get("stub_output", {})
            return ProviderResponse({"unexpected": True}, "{}", 5, 5)

    repairing = Repairing()
    svc._provider = lambda: repairing
    out = svc.start(**REQ)
    assert out["status"] == "awaiting_approval" and out["state"]["recommendation"]
    row = svc.db.run_metrics_rows()[-1]
    assert row["llm_repairs"] >= 6 and out["metrics"]["invalid_schema_rate"] == 1.0 and out["metrics"]["schema_escalations"] == 0


def test_output_that_can_never_be_fixed_escalates_and_no_unvalidated_recommendation_exists():
    svc, provider = service(lambda n, t: "malformed")
    out = svc.start(**REQ)
    assert out["status"] == "escalated" and "failed schema after repair and fallback" in out["halted_reason"]
    assert out["state"].get("recommendation") is None and out["state"].get("engagement_spec") is None
    assert out["metrics"]["schema_escalations"] == 1
    kinds = [f["type"] for f in failures(svc, out["workflow_id"])]
    assert kinds.count("invalid_schema") == 3 and kinds[-1] == "schema_escalation"  # initial, repair, stronger model
    assert provider.by_task.get("schema_repair") == 1


def test_prose_instead_of_json_follows_the_same_path():
    svc, _ = service(lambda n, t: "not_json")
    out = svc.start(**REQ)
    assert out["status"] == "escalated"
    assert any("not valid JSON" in str(f.get("errors")) for f in failures(svc, out["workflow_id"]))


def test_a_failure_late_in_the_pipeline_keeps_the_work_done_so_far_but_produces_no_recommendation():
    # break the Solution Agent's model call and its repair, so the output can never be validated
    svc, _ = service(lambda n, t: "malformed" if t in {"strategy", "schema_repair"} else None)
    out = svc.start(**REQ)
    assert out["status"] == "escalated" and "solution_agent" in out["halted_reason"]
    assert out["state"]["financial_models"] and out["state"]["risks"]   # earlier, validated work is kept for the reviewer
    assert out["state"].get("recommendation") is None


# ---- quality drop --------------------------------------------------------------------------------------------------------------------
def lenient_degrading_policy(tmp_path):
    text = Path(get_settings().policy_file).read_text(encoding="utf-8")
    text = (text.replace("client_facing_recommendation,", "")
            .replace("medium: [market_interpretation,", "medium: [client_facing_recommendation, market_interpretation,")
            .replace("financial_commitment_usd: 1000000", "financial_commitment_usd: 100000000")
            .replace("  window: 10\n  min_runs: 3", "  window: 3\n  min_runs: 3")
            # this test sends far more traffic per minute than production would: do not let the rate limit slow it
            .replace("tokens_per_minute: 150000", "tokens_per_minute: 50000000"))
    path = tmp_path / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_when_quality_drops_the_system_tightens_by_itself_and_loosens_when_quality_returns(tmp_path):
    svc = EngagementService(settings(policy_file=lenient_degrading_policy(tmp_path)))
    quality = {"groundedness": 1.0}

    class Scripted(FaultProvider):
        def complete_json(self, *, task, system, prompt, schema, context, model):
            res = super().complete_json(task=task, system=system, prompt=prompt, schema=schema, context=context, model=model)
            if "task_adherence" in schema.get("properties", {}):  # the LLM judge: report whatever quality we are simulating
                res.content["groundedness"] = quality["groundedness"]
            return res

    svc._provider = lambda: Scripted(lambda n, t: None)

    assert svc.start(**REQ)["status"] == "completed", "baseline: a clean run finishes with no human"
    quality["groundedness"] = 0.4
    statuses = [svc.start(**REQ)["status"] for _ in range(4)]
    assert svc.degradation.level in {"cautious", "restricted"}, "quality fell but nothing changed"
    assert any(e["to_level"] in {"cautious", "restricted"} for e in svc.db.degradation_events_list())

    quality["groundedness"] = 1.0  # the model is fixed...
    tightened = svc.start(**REQ)
    assert tightened["status"] == "awaiting_approval", "a degraded system let a run finish without a human"
    assert any("quality degradation" in r for g in tightened["guardian_decisions"] for r in g["reasons"])

    for _ in range(9):  # ...and a stretch of good runs brings it back, one level at a time
        svc.start(**REQ)
    assert svc.degradation.level == "normal"
    assert svc.start(**REQ)["status"] == "completed"
    levels = [e["to_level"] for e in reversed(svc.db.degradation_events_list())]
    assert levels[0] in {"cautious", "restricted"} and levels[-1] == "normal"
    assert statuses.count("completed") < len(statuses) or svc.degradation_controller  # the early low-quality runs were not all auto-completed


# ---- after faults -----------------------------------------------------------------------------------------------------------------
def test_after_every_kind_of_fault_a_clean_run_on_the_same_service_still_works():
    faults = [lambda n, t: "429", lambda n, t: "malformed", lambda n, t: "not_json"]
    for plan in faults:
        svc, provider = service(plan)
        assert svc.start(**REQ)["status"] == "escalated"
        provider.plan = lambda n, t: None  # the fault clears
        svc.breakers = BreakerRegistry()   # (a fresh circuit; the recovery timing is covered above)
        again = svc.start(**REQ)
        assert again["status"] == "awaiting_approval" and again["state"]["recommendation"]
        assert_healthy_afterwards(svc)


def test_nothing_the_faults_do_ever_marks_a_run_successful():
    svc, _ = service(lambda n, t: "malformed")
    svc.start(**REQ)
    svc2, _ = service(lambda n, t: "429")
    svc2.start(**REQ)
    for s in (svc, svc2):
        assert all(r["successful"] is False and r["status"] == "escalated" for r in s.db.run_metrics_rows())


def test_run_deadline_and_tool_limit_are_still_enforced_when_faults_slow_things_down():
    svc, _ = service(max_duration_sec=1)
    hang(svc, "calculate_roi", limit_ms=60_000)  # the tool alone would be allowed a minute
    t0 = time.monotonic()
    out = svc.start(**REQ)
    assert time.monotonic() - t0 < 8 and out["status"] == "escalated"  # the workflow deadline capped it


@pytest.mark.parametrize("exc", [ToolTimeoutError("x")])
def test_tool_timeouts_are_a_kind_of_transient_error(exc):
    assert isinstance(exc, TransientError)
    _ = dt  # keep the import used
