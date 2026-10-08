import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.control_plane.budget import Budget
from app.control_plane.executor import ToolArgsInvalid, ToolBlocked, ToolExecutor
from app.control_plane.guardian import Guardian
from app.control_plane.policy import PolicyEngine
from app.control_plane.tool_registry import default_registry
from app.main import app
from app.observability.aggregate import quality_flags, summarize, timeseries
from app.observability.redaction import REDACTED, can_see_payloads, redact_trace
from app.observability.run_metrics import breakdown, is_successful
from app.observability.tracing import TraceStore
from app.security.auth import Principal
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M"]}
OWNER = Principal("owner-1", "Olive Owner", ())
PARTNER = Principal("p-1", "Pat", ("Partner",))
ANALYST = Principal("a-1", "Ann", ("Analyst",))
H = {"X-Dev-User": "owner-1"}


def spans_of(svc, wid, kind=None):
    return [s for s in svc.trace(wid)["spans"] if kind is None or s["kind"] == kind]


# ---- enriched spans -----------------------------------------------------------------------------------
def make_executor():
    policy = PolicyEngine.from_file(get_settings().policy_file)
    log = {"guardian_decisions": [], "failures": []}
    trace = TraceStore("wf")
    return ToolExecutor(default_registry(), Guardian(policy), Budget(), trace, log), trace, log


def test_a_successful_tool_call_records_arguments_result_attempts_and_the_guardian_decision():
    ex, trace, _ = make_executor()
    ex.call("financial_agent", "calculate_roi", {"investment": 100.0, "annual_benefit": 50.0, "years": 4})
    a = trace.spans[0].attributes
    assert a["consultai.tool_arguments"] == {"investment": 100.0, "annual_benefit": 50.0, "years": 4}
    assert a["consultai.tool_result"]["roi"] == pytest.approx(1.0)
    assert a["consultai.attempts"] == 1 and a["consultai.outcome"] == "ok"
    assert a["consultai.guardian"]["action"] == "ALLOW" and a["consultai.timeout_ms"] > 0


def test_a_blocked_call_still_leaves_a_span_with_the_decision_that_stopped_it():
    ex, trace, log = make_executor()
    with pytest.raises(ToolBlocked):
        ex.call("research_agent", "calculate_roi", {"investment": 1.0, "annual_benefit": 1.0, "years": 1})
    span = trace.spans[0]
    assert span.status == "error" and span.attributes["consultai.outcome"] == "blocked"
    assert span.attributes["consultai.guardian"]["action"] == "BLOCK"
    assert "calculate_roi" in span.attributes["consultai.guardian"]["subject"] and log["guardian_decisions"]


def test_invalid_arguments_leave_a_span_with_the_schema_errors():
    ex, trace, _ = make_executor()
    with pytest.raises(ToolArgsInvalid):
        ex.call("financial_agent", "calculate_roi", {"investment": -5, "annual_benefit": 1, "years": 1})
    a = trace.spans[0].attributes
    assert a["consultai.outcome"] == "invalid_arguments" and a["consultai.schema_errors"]
    assert trace.summary()["tool_errors"] == 1  # a refused call now counts as a failed tool call


def test_retries_are_counted():
    ex, trace, _ = make_executor()
    contract = ex.registry.get("calculate_roi")
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            from app.control_plane.reliability import TransientError
            raise TransientError("blip")
        return {"roi": 1.0}
    contract.fn = flaky
    ex.call("financial_agent", "calculate_roi", {"investment": 1.0, "annual_benefit": 1.0, "years": 1})
    assert trace.spans[0].attributes["consultai.attempts"] == 2


def test_a_real_run_records_the_retrieval_documents_and_sql_results():
    svc = EngagementService()
    wid = svc.start(**REQ)["workflow_id"]
    ret = spans_of(svc, wid, "retrieval")[0]["attributes"]["consultai.retrieval"]
    assert ret["embedding_model"].startswith("hashing") and ret["filters"]["max_classification"] == "confidential"
    assert ret["documents"] and {"doc_id", "chunk_id", "source", "score", "text"} <= set(ret["documents"][0])
    sql = [s for s in spans_of(svc, wid, "tool") if s["attributes"].get("gen_ai.tool.name") == "run_sql_readonly"]
    assert len(sql) == 3 and sql[0]["attributes"]["consultai.tool_result"]["row_count"] == 4
    assert all(s["attributes"]["gen_ai.agent.name"] == "data_agent" for s in sql)


# ---- redaction ----------------------------------------------------------------------------------------------
def sample_trace():
    return {"trace_id": "t", "spans": [
        {"span_id": "1", "kind": "tool", "name": "tool:x", "status": "ok", "error": "failed for ann@corp.com",
         "attributes": {"gen_ai.tool.name": "x", "consultai.tool_arguments": {"owner": "ann@corp.com", "n": 3},
                        "consultai.tool_result": {"rows": [1]}, "consultai.sql": "SELECT 1",
                        "consultai.guardian": {"action": "ALLOW"}}},
        {"span_id": "2", "kind": "retrieval", "name": "retrieval", "status": "ok", "error": None,
         "attributes": {"consultai.query": "secret strategy question", "consultai.retrieval": {
             "retrieval_id": "r", "index": "local", "embedding_model": "m", "k": 2, "filters": {"groups": ["all"]},
             "documents": [{"doc_id": "d", "chunk_id": "d#0", "source": "s", "score": 0.9, "text": "CONFIDENTIAL TEXT"}]}}},
    ]}


def test_who_may_see_payloads():
    roles = ["Partner", "Admin"]
    kw = {"owner_id": "owner-1", "privileged_roles": roles}
    assert can_see_payloads(ANALYST, classification="public", **kw)
    assert can_see_payloads(ANALYST, classification="internal", **kw)
    assert not can_see_payloads(ANALYST, classification="confidential", **kw)
    assert can_see_payloads(PARTNER, classification="confidential", **kw)
    assert can_see_payloads(OWNER, classification="confidential", **kw)
    assert can_see_payloads(Principal("x", "x", ("Admin",)), classification="confidential", **kw)


def test_unprivileged_users_get_structure_without_payloads():
    out, info = redact_trace(sample_trace(), show_payloads=False, reason="confidential")
    a = out["spans"][0]["attributes"]
    assert a["consultai.tool_arguments"] == REDACTED and a["consultai.tool_result"] == REDACTED
    assert a["consultai.sql"] == REDACTED
    assert a["consultai.guardian"] == {"action": "ALLOW"} and a["gen_ai.tool.name"] == "x"  # structure stays
    r = out["spans"][1]["attributes"]
    assert r["consultai.query"] == REDACTED
    assert r["consultai.retrieval"]["documents"] == [{"doc_id": "d", "chunk_id": "d#0", "source": "s", "score": 0.9}]
    assert "filters" not in r["consultai.retrieval"] and r["consultai.retrieval"]["redacted"] is True
    assert "CONFIDENTIAL TEXT" not in str(out)
    assert info.payloads_redacted and info.reason == "confidential"


def test_privileged_users_see_payloads_but_secrets_and_pii_are_still_scrubbed_for_everyone():
    out, info = redact_trace(sample_trace(), show_payloads=True)
    a = out["spans"][0]["attributes"]
    assert a["consultai.tool_arguments"] == {"owner": "[email]", "n": 3}
    assert out["spans"][0]["error"] == "failed for [email]"
    assert out["spans"][1]["attributes"]["consultai.retrieval"]["documents"][0]["text"] == "CONFIDENTIAL TEXT"
    assert not info.payloads_redacted and info.pii_scrubbed == 2


def test_redaction_does_not_modify_the_stored_trace():
    t = sample_trace()
    redact_trace(t, show_payloads=False)
    assert t["spans"][0]["attributes"]["consultai.tool_arguments"]["owner"] == "ann@corp.com"


def test_trace_endpoint_applies_the_rule_by_role_and_ownership():
    c = TestClient(app)
    wid = c.post("/engagements", json=REQ, headers=H).json()["workflow_id"]   # confidential, owned by owner-1
    def tool_args(headers):
        r = c.get(f"/control-center/{wid}/trace", headers=headers).json()
        span = next(s for s in r["spans"] if s["attributes"].get("gen_ai.tool.name") == "calculate_roi")
        return span["attributes"]["consultai.tool_arguments"], r["redaction"]
    args, red = tool_args(H)                                                   # the owner
    assert isinstance(args, dict) and red["payloads_redacted"] is False
    args, red = tool_args({"X-Dev-User": "p", "X-Dev-Roles": "Partner"})
    assert isinstance(args, dict)
    args, red = tool_args({"X-Dev-User": "ann", "X-Dev-Roles": "Analyst"})      # someone else
    assert args == REDACTED and red["payloads_redacted"] is True and "confidential" in red["reason"]
    pub = c.post("/engagements", json={**REQ, "data_classification": "public"}, headers=H).json()["workflow_id"]
    r = c.get(f"/control-center/{pub}/trace", headers={"X-Dev-User": "ann"}).json()
    assert r["redaction"]["payloads_redacted"] is False                        # public: open to any signed-in user


# ---- per-run metrics ----------------------------------------------------------------------------------------
def test_success_means_outcome_evidence_and_safety_not_just_completion():
    good = {"constraint_satisfaction": 1.0, "groundedness": 0.9, "contradiction_free": 1.0, "judge_coverage": 1.0}
    th = {"min_constraint_satisfaction": 0.9, "min_groundedness": 0.75, "min_contradiction_free": 0.75}
    ok_state = {"approval_status": "approved"}
    assert is_successful("completed", ok_state, good, th, blocked=0)
    assert not is_successful("rejected", {"approval_status": "rejected"}, good, th, 0)       # human said no
    assert not is_successful("completed", ok_state, {**good, "groundedness": 0.5}, th, 0)    # finished but ungrounded
    assert not is_successful("completed", ok_state, {**good, "constraint_satisfaction": 0.5}, th, 0)
    assert not is_successful("completed", ok_state, {**good, "contradiction_free": 0.2}, th, 0)
    assert not is_successful("completed", ok_state, {**good, "judge_coverage": 0.0}, th, 0)  # nobody checked it
    assert not is_successful("completed", ok_state, good, th, blocked=1)                     # a blocked action
    assert not is_successful("awaiting_approval", {"approval_status": "pending"}, good, th, 0)


def test_a_run_records_its_metrics_when_it_pauses_and_completes():
    svc = EngagementService()
    wid = svc.start(**REQ)["workflow_id"]
    row = svc.db.run_metrics_rows()[-1]
    assert row["workflow_id"] == wid and row["status"] == "awaiting_approval" and row["successful"] is False
    assert row["duration_sec"] > 0 and row["llm_calls"] >= 7 and row["tool_calls"] > 0
    assert {a["agent"] for a in row["cost_by_agent"]} >= {"discovery_agent", "financial_agent", "evaluator", "guardian"}
    svc.approve(wid, "approve", reason="ok", approver=PARTNER)
    row = next(r for r in svc.db.run_metrics_rows() if r["workflow_id"] == wid)
    assert row["status"] == "completed" and row["successful"] is True
    assert row["approval_decision"] == "approve" and row["decision_seconds"] >= 0


def test_failed_and_escalated_runs_are_recorded_too():
    svc = EngagementService()
    svc.graph.invoke = lambda *a, **k: (_ for _ in ()).throw(ValueError("graph exploded"))
    wid = svc.start(**REQ)["workflow_id"]
    row = svc.db.run_metrics_rows()[-1]
    assert row["workflow_id"] == wid and row["status"] == "failed" and row["successful"] is False


def test_breakdown_sums_llm_spans_by_agent_and_model():
    spans = [
        {"kind": "llm", "attributes": {"gen_ai.agent.name": "a", "gen_ai.request.model": "MODEL_SMALL", "consultai.tier": "small",
                                       "gen_ai.usage.input_tokens": 10, "gen_ai.usage.output_tokens": 5, "consultai.cost_usd": 0.01}},
        {"kind": "llm", "attributes": {"gen_ai.agent.name": "a", "gen_ai.request.model": "MODEL_SMALL", "consultai.tier": "small",
                                       "gen_ai.usage.input_tokens": 20, "gen_ai.usage.output_tokens": 5, "consultai.cost_usd": 0.02}},
        {"kind": "llm", "attributes": {"gen_ai.agent.name": "b", "gen_ai.request.model": "MODEL_REASONING", "consultai.tier": "reasoning",
                                       "gen_ai.usage.input_tokens": 1, "gen_ai.usage.output_tokens": 1, "consultai.cost_usd": 0.5}},
        {"kind": "tool", "attributes": {"consultai.cost_usd": 99}},
    ]
    bd = breakdown(spans)
    assert bd["by_agent"] == [{"agent": "a", "calls": 2, "input_tokens": 30, "output_tokens": 10, "cost_usd": 0.03},
                              {"agent": "b", "calls": 1, "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.5}]
    assert [m["model"] for m in bd["by_model"]] == ["MODEL_REASONING", "MODEL_SMALL"]


# ---- aggregation ------------------------------------------------------------------------------------------------
def row(day, *, status="completed", ok=True, cost=1.0, ground=0.9, decision="approve", escalated=False, **over):
    base = {
        "workflow_id": f"wf_{day}_{cost}", "created_at": f"2026-10-0{day}T10:00:00+00:00", "status": status,
        "duration_sec": 10.0, "cost_usd": cost, "input_tokens": 100, "output_tokens": 50, "tool_calls": 10, "tool_errors": 0,
        "llm_calls": 6, "llm_repairs": 0, "llm_fallbacks": 0, "schema_escalations": 0, "invalid_schema_rate": 0.0,
        "guardian_decisions": 20, "blocked_actions": 0, "escalations": 1, "escalated": escalated, "successful": ok,
        "approval_decision": decision, "decision_seconds": 60.0,
        "scores": {"groundedness": ground, "task_adherence": 1.0, "constraint_satisfaction": 1.0, "tool_call_accuracy": 1.0,
                   "contradiction_free": 1.0, "completeness": 1.0, "quality": 0.9},
        "cost_by_agent": [{"agent": "x", "calls": 6, "input_tokens": 100, "output_tokens": 50, "cost_usd": cost}],
        "cost_by_model": [{"model": "MODEL_SMALL", "tier": "small", "calls": 6, "input_tokens": 100, "output_tokens": 50, "cost_usd": cost}],
    }
    return {**base, **over}


TH = {"min_groundedness": 0.75, "min_tool_call_accuracy": 0.9, "min_contradiction_free": 0.75,
      "min_constraint_satisfaction": 0.9, "min_task_adherence": 0.7}


def test_cost_per_successful_task_charges_failures_to_the_successes():
    rows = [row(1, cost=1.0), row(1, cost=1.0), row(1, status="rejected", ok=False, cost=2.0, decision="reject")]
    e = summarize(rows, TH)["economics"]
    assert e["total_cost_usd"] == 4.0 and e["successful_runs"] == 2 and e["success_rate"] == pytest.approx(0.6667, abs=1e-3)
    assert e["cost_per_successful_task"] == 2.0          # $4 spent / 2 good outcomes, not $1.33 per run
    assert e["cost_by_agent"][0]["cost_usd"] == 4.0 and e["cost_by_model"][0]["calls"] == 18


def test_summary_groups_and_business_split():
    rows = [row(1, decision="approve"), row(1, decision="modify"), row(2, status="rejected", ok=False, decision="reject"),
            row(2, status="awaiting_approval", ok=False, decision=None, decision_seconds=None),
            row(2, status="escalated", ok=False, decision=None, decision_seconds=None, escalated=True)]
    s = summarize(rows, TH)
    assert s["runs"] == 5 and s["by_status"] == {"completed": 2, "rejected": 1, "awaiting_approval": 1, "escalated": 1}
    b = s["business"]
    assert b["decided"] == 3 and b["approval_rate"] == pytest.approx(0.3333, abs=1e-3)
    assert b["modification_rate"] == pytest.approx(0.3333, abs=1e-3) and b["rejection_rate"] == pytest.approx(0.3333, abs=1e-3)
    assert b["awaiting_approval"] == 1 and b["median_decision_seconds"] == 60.0
    assert s["safety"]["runs_halted"] == 1 and s["tool"]["tool_call_success_rate"] == 1.0
    assert s["intent"]["task_adherence"] == 1.0


def test_empty_window_is_all_none_not_a_crash():
    s = summarize([], TH)
    assert s["runs"] == 0 and s["economics"]["cost_per_successful_task"] is None and s["flags"] == []
    assert s["safety"]["groundedness"] is None and s["business"]["approval_rate"] is None


def test_quality_flags_fire_below_policy_thresholds_only():
    healthy = summarize([row(1)], TH)
    assert healthy["flags"] == []
    weak = summarize([row(1, ground=0.5), row(1, ground=0.6)], TH)
    assert [f["metric"] for f in weak["flags"]] == ["groundedness"]
    assert weak["flags"][0]["value"] == pytest.approx(0.55) and "below the policy minimum" in weak["flags"][0]["message"]
    bad_tools = summarize([row(1, scores={"tool_call_accuracy": 0.5, "groundedness": 0.9})], TH)
    assert "tool_call_accuracy" in [f["metric"] for f in quality_flags(bad_tools, TH)]


def test_percentiles_and_tool_rates():
    rows = [row(1, duration_sec=float(d)) for d in (10, 20, 30, 40, 100)]
    assert summarize(rows, TH)["economics"]["p50_duration_sec"] == 30.0
    assert summarize(rows, TH)["economics"]["p95_duration_sec"] == pytest.approx(88.0)
    t = summarize([row(1, tool_calls=10, tool_errors=1, llm_calls=10, llm_repairs=2, llm_fallbacks=1)], TH)["tool"]
    assert (t["tool_call_success_rate"], t["llm_repair_rate"], t["llm_fallback_rate"]) == (0.9, 0.2, 0.1)


def test_timeseries_buckets_by_day_and_aggregates_by_kind_of_metric():
    rows = [row(1, cost=1.0, ground=0.8), row(1, cost=2.0, ground=1.0), row(2, cost=5.0, ok=False, ground=0.5)]
    cost = timeseries(rows, "cost_usd")
    assert [(p["t"][:10], p["value"], p["n"]) for p in cost] == [("2026-10-01", 3.0, 2), ("2026-10-02", 5.0, 1)]
    assert [p["value"] for p in timeseries(rows, "runs")] == [2.0, 1.0]
    assert [p["value"] for p in timeseries(rows, "groundedness")] == [0.9, 0.5]
    assert [p["value"] for p in timeseries(rows, "success_rate")] == [1.0, 0.0]
    assert [p["value"] for p in timeseries(rows, "tokens")] == [300.0, 150.0]
    hourly = timeseries([row(1), {**row(1), "created_at": "2026-10-01T11:30:00+00:00"}], "runs", "hour")
    assert [p["t"][11:13] for p in hourly] == ["10", "11"]


def test_timeseries_rejects_unknown_metrics_and_buckets():
    with pytest.raises(ValueError):
        timeseries([], "nope")
    with pytest.raises(ValueError):
        timeseries([], "runs", "week")


# ---- the endpoints ------------------------------------------------------------------------------------------------
def test_metrics_endpoints_after_real_runs():
    client = TestClient(app)
    since = dt.datetime.now(dt.UTC).isoformat()
    ids = [client.post("/engagements", json=REQ, headers=H).json()["workflow_id"] for _ in range(2)]
    client.post(f"/engagements/{ids[0]}/approval", json={"decision": "approve", "reason": "ok"},
                headers={"X-Dev-User": "p", "X-Dev-Roles": "Partner"})
    client.post(f"/engagements/{ids[1]}/approval", json={"decision": "reject", "reason": "no"},
                headers={"X-Dev-User": "p", "X-Dev-Roles": "Partner"})
    s = client.get("/metrics/summary", params={"since": since}, headers=H).json()
    assert s["runs"] == 2 and s["by_status"] == {"completed": 1, "rejected": 1}
    assert s["business"]["approval_rate"] == 0.5 and s["business"]["rejection_rate"] == 0.5
    assert s["economics"]["successful_runs"] == 1 and s["economics"]["cost_per_successful_task"] == pytest.approx(s["economics"]["total_cost_usd"] / 1)
    assert set(s) >= {"intent", "tool", "safety", "business", "economics", "flags"}
    assert client.get("/metrics/summary", params={"since": since, "status": "rejected"}, headers=H).json()["runs"] == 1
    ts = client.get("/metrics/timeseries", params={"metric": "cost_usd", "since": since}, headers=H).json()
    assert ts["metric"] == "cost_usd" and ts["points"][0]["n"] == 2 and ts["points"][0]["value"] > 0
    assert client.get("/metrics/timeseries", params={"metric": "nope"}, headers=H).status_code == 422
    assert client.get("/metrics/timeseries", params={"metric": "runs", "bucket": "week"}, headers=H).status_code == 422


def test_cost_endpoint_breaks_down_by_agent_and_model_and_shows_budget_use():
    client = TestClient(app)
    wid = client.post("/engagements", json=REQ, headers=H).json()["workflow_id"]
    r = client.get(f"/engagements/{wid}/cost", headers=H).json()
    assert r["total_cost_usd"] > 0 and r["successful"] is False and r["cost_per_successful_task"] is None
    assert sum(a["cost_usd"] for a in r["by_agent"]) == pytest.approx(r["total_cost_usd"], abs=1e-5)
    assert {m["tier"] for m in r["by_model"]} >= {"small", "medium", "reasoning"}
    assert r["budget"]["cost_usd"]["limit"] == 2.0 and r["budget"]["tokens"]["used"] == r["input_tokens"] + r["output_tokens"]
    client.post(f"/engagements/{wid}/approval", json={"decision": "approve"}, headers={"X-Dev-User": "p", "X-Dev-Roles": "Partner"})
    done = client.get(f"/engagements/{wid}/cost", headers=H).json()
    assert done["successful"] is True and done["cost_per_successful_task"] == done["total_cost_usd"]
    assert client.get("/engagements/nope/cost", headers=H).status_code == 404


def test_every_guardian_decision_records_the_policy_version_that_governed_it():
    svc = EngagementService()
    out = svc.start(**REQ)
    assert out["guardian_decisions"] and all(d["policy_version"] == svc.policy.version for d in out["guardian_decisions"])
    # including tool-call decisions and the final workflow decision
    assert {d["subject"] == "workflow" for d in out["guardian_decisions"]} == {True, False}


def test_the_metrics_summary_tells_the_ui_the_policy_it_is_judged_against():
    client = TestClient(app)
    s = client.get("/metrics/summary", headers=H).json()
    assert s["policy_version"] and s["thresholds"]["min_groundedness"] == 0.75
    assert s["thresholds"]["min_tool_call_accuracy"] == 0.9
