from fastapi.testclient import TestClient

from app.control_plane.llm import ProviderResponse
from app.main import app
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M"]}


class Garbage:
    """Provider that never produces schema-valid output."""
    name = "azure_openai"

    def complete_json(self, **kw):
        return ProviderResponse({"nonsense": True}, "{}", 10, 10)


def test_unrepairable_output_escalates_instead_of_crashing():
    svc = EngagementService()
    svc._provider = lambda: Garbage()
    out = svc.start(**REQ)
    assert out["status"] == "escalated" and "discovery_agent" in out["halted_reason"]
    assert "recommendation" not in out["state"]
    assert out["metrics"]["schema_escalations"] == 1
    assert out["metrics"]["invalid_schema_rate"] == 1.0
    assert svc.list(status="escalated")["total"] == 1


def test_list_engagements_filters_and_paginates():
    client = TestClient(app)
    a = client.post("/engagements", json=REQ).json()["workflow_id"]
    b = client.post("/engagements", json=REQ).json()["workflow_id"]
    client.post(f"/engagements/{b}/approval", json={"decision": "approve"},
                headers={"X-Dev-Roles": "Partner"})
    waiting = client.get("/engagements", params={"status": "awaiting_approval", "limit": 200}).json()
    done = client.get("/engagements", params={"status": "completed", "limit": 200}).json()
    waiting_ids = [i["workflow_id"] for i in waiting["items"]]
    assert a in waiting_ids and b not in waiting_ids
    assert b in [i["workflow_id"] for i in done["items"]]
    page = client.get("/engagements", params={"limit": 1}).json()
    assert len(page["items"]) == 1 and page["total"] >= 2
    assert page["items"][0]["workflow_id"] == b  # newest first
    assert client.get("/engagements", params={"status": "bogus"}).status_code == 422


def test_cors_preflight_allows_dev_frontend():
    r = TestClient(app).options("/engagements", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    r = TestClient(app).options("/engagements", headers={
        "Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_openapi_contract_is_typed_and_stable():
    spec = TestClient(app).get("/openapi.json").json()
    ops = {op["operationId"] for item in spec["paths"].values() for op in item.values()}
    assert ops == {"createEngagement", "listEngagements", "getEngagement", "submitApproval",
                   "getTrace", "getHealth", "getEvidence", "getTables", "replayRetrieval",
                   "getMe", "listApprovals", "getGuardianLog", "streamEvents", "getMetricsSummary",
                   "getMetricsTimeseries", "getCostBreakdown", "getPolicy", "listPolicyVersions",
                   "getPolicyVersion", "listTools", "getProviders", "getBudgets", "getDegradation"}
    schemas = spec["components"]["schemas"]
    for name in ["EngagementDetail", "EngagementList", "EngagementSummary", "TraceOut", "EngagementState"]:
        assert name in schemas, name
    assert schemas["EngagementDetail"]["properties"]["status"]["enum"] == [
        "queued", "running", "awaiting_approval", "completed", "rejected", "escalated", "failed"]
    for item in spec["paths"].values():  # every operation declares a typed JSON 200 response
        for op in item.values():
            if op["operationId"] == "streamEvents":  # text/event-stream, documented in prose
                continue
            schema = op["responses"]["200"]["content"]["application/json"]["schema"]
            assert "$ref" in schema or "$ref" in schema.get("items", {})  # object or typed array


def test_responses_validate_against_models():
    client = TestClient(app)
    r = client.post("/engagements", json=REQ)
    assert r.status_code == 200 and r.json()["budget"]["cost_usd"] > 0
    assert client.get("/health").json() == {"status": "ok", "llm_provider": "stub"}
