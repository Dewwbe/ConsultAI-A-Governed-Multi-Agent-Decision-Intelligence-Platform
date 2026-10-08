import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"],
       "constraints": ["Budget under $10M", "Launch within 18 months"]}


@pytest.fixture
def svc():
    return EngagementService()


def test_full_run_pauses_for_human_approval(svc):
    out = svc.start(**REQ)
    assert out["status"] == "awaiting_approval"
    assert out["pending_node"] == ["approval"]
    rec = out["state"]["recommendation"]
    assert rec["cost_usd"] <= 10_000_000
    assert out["state"]["evaluation_scores"]["constraint_satisfaction"] == 1.0
    assert out["state"]["risk_level"] == "high"


def test_approve_completes_with_report(svc):
    wid = svc.start(**REQ)["workflow_id"]
    out = svc.approve(wid, "approve", reason="looks right")
    assert out["status"] == "completed"
    assert "Engagement Report" in out["state"]["report"]["markdown"]
    assert out["state"]["approval_status"] == "approved"


def test_modify_applies_changes(svc):
    wid = svc.start(**REQ)["workflow_id"]
    out = svc.approve(wid, "modify", changes={"rationale": "conservative assumptions"})
    assert out["state"]["recommendation"]["rationale"] == "conservative assumptions"
    assert out["state"]["approval_status"] == "modified"
    assert len(svc.memory.recall("human_feedback")) == 1


def test_reject_ends_without_report(svc):
    wid = svc.start(**REQ)["workflow_id"]
    out = svc.approve(wid, "reject", reason="assumptions too optimistic")
    assert out["status"] == "rejected"
    assert "report" not in out["state"]


def test_trace_and_metrics(svc):
    out = svc.start(**REQ)
    tr = svc.trace(out["workflow_id"])
    kinds = {s["kind"] for s in tr["spans"]}
    assert {"agent", "llm", "tool", "retrieval", "evaluator", "guardian", "approval"} <= kinds
    assert tr["tool_calls"] > 0
    m = out["metrics"]
    assert m["tool_call_success_rate"] == 1.0
    assert m["invalid_schema_rate"] == 0.0
    assert m["total_engagement_cost"] > 0


def test_financial_numbers_come_from_tools(svc):
    out = svc.start(**REQ)
    fm = {m["id"]: m for m in out["state"]["financial_models"]}
    assert fm["B"]["roi"] == pytest.approx((700_000 * 5 - 2_000_000) / 2_000_000)


def test_least_privilege_views():
    from app.schemas.views import view_for
    state = {"business_problem": "x", "risks": [1], "recommendation": {}, "engagement_spec": {}}
    assert "risks" not in view_for("research_agent", state)
    assert "business_problem" not in view_for("solution_agent", state)


def test_api_roundtrip():
    client = TestClient(app)
    r = client.post("/engagements", json=REQ)
    assert r.status_code == 200
    wid = r.json()["workflow_id"]
    assert client.get(f"/engagements/{wid}").json()["status"] == "awaiting_approval"
    assert client.get(f"/control-center/{wid}/trace").json()["span_count"] > 5
    assert client.post(f"/engagements/{wid}/approval", json={"decision": "approve"}).json()["status"] == "completed"
    # approving twice is a conflict
    assert client.post(f"/engagements/{wid}/approval", json={"decision": "approve"}).status_code == 409
    assert client.get("/engagements/nope").status_code == 404
