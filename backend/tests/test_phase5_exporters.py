import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.config import Settings
from app.observability.export import build_span_exporter, build_tracer_provider
from app.security.auth import Principal
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M"]}
PARTNER = Principal("p-1", "Pat", ("Partner",))


def settings(**over):
    return Settings(llm_provider="stub", database_url="sqlite:///:memory:", **over)


# ---- OpenTelemetry ----------------------------------------------------------------------------------------
def test_nothing_is_exported_unless_configured():
    s = settings()
    assert build_span_exporter(s) is None and build_tracer_provider(s) is None
    assert EngagementService(s).tracer is None


def test_spans_reach_the_exporter_with_final_token_counts_and_cost():
    mem = InMemorySpanExporter()
    svc = EngagementService(settings(), span_exporter=mem)
    svc.start(**REQ)
    spans = mem.get_finished_spans()
    llm = [s for s in spans if s.attributes.get("consultai.span.kind") == "llm"]
    assert len(spans) > 30 and len(llm) >= 7
    first = llm[0].attributes
    # these only exist once the call has finished: the exported copy is written at the end
    assert first["gen_ai.usage.input_tokens"] > 0 and first["gen_ai.usage.output_tokens"] > 0 and first["consultai.cost_usd"] > 0
    assert first["gen_ai.agent.name"] and first["consultai.prompt"].endswith(("@v1", "@v2", "@v3"))
    kinds = {s.attributes["consultai.span.kind"] for s in spans}
    assert {"agent", "llm", "tool", "retrieval", "evaluator", "guardian"} <= kinds


def test_exported_spans_carry_no_client_payloads_by_default():
    mem = InMemorySpanExporter()
    EngagementService(settings(), span_exporter=mem).start(**REQ)
    keys = {k for s in mem.get_finished_spans() for k in s.attributes}
    for payload in ("consultai.tool_arguments", "consultai.tool_result", "consultai.sql", "consultai.retrieval", "consultai.query"):
        assert payload not in keys
    assert "consultai.guardian" in keys and "gen_ai.tool.name" in keys  # structure is exported


def test_payload_export_can_be_enabled_but_secrets_are_still_scrubbed():
    mem = InMemorySpanExporter()
    svc = EngagementService(settings(otel_export_payloads=True), span_exporter=mem)
    svc.start(**{**REQ, "constraints": ["Budget under $10M, contact ann@corp.com"]})
    values = " ".join(str(v) for s in mem.get_finished_spans() for v in s.attributes.values())
    assert "consultai.tool_arguments" in {k for s in mem.get_finished_spans() for k in s.attributes}
    assert "ann@corp.com" not in values


def test_failed_spans_are_exported_with_an_error_status_and_a_scrubbed_message():
    mem = InMemorySpanExporter()
    svc = EngagementService(settings(), span_exporter=mem)
    with svc._runtime("wf_x").trace.span("boom", "tool") as _:
        pass
    try:
        with svc._runtime("wf_y").trace.span("tool:x", "tool"):
            raise ValueError("lookup failed for ann@corp.com")
    except ValueError:
        pass
    bad = next(s for s in mem.get_finished_spans() if s.name == "tool:x")
    assert bad.status.status_code.name == "ERROR" and "ann@corp.com" not in (bad.status.description or "")
    assert bad.attributes["consultai.status"] == "error" and "[email]" in bad.attributes["consultai.error"]
    # nothing else carries the raw message either: OTel's own exception event is switched off
    assert not bad.events and "ann@corp.com" not in str(bad.attributes)


class _Collector(BaseHTTPRequestHandler):
    received: ClassVar[list[tuple[str, str, int]]] = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _Collector.received.append((self.path, self.headers.get("Content-Type", ""), len(body)))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()

    def log_message(self, *args):
        pass


def test_spans_are_really_posted_to_an_otlp_collector_over_http():
    """Real OTLP/HTTP export to a local receiver, not a mock: proves the wiring end to end."""
    _Collector.received = []
    server = HTTPServer(("127.0.0.1", 0), _Collector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        s = settings(otel_exporter_otlp_endpoint=f"http://127.0.0.1:{server.server_port}")
        svc = EngagementService(s)
        assert svc.tracer_provider is not None
        svc.start(**REQ)
        svc.tracer_provider.force_flush()
    finally:
        server.shutdown()
    assert _Collector.received, "the collector received nothing"
    path, content_type, size = _Collector.received[0]
    assert path == "/v1/traces" and content_type == "application/x-protobuf" and size > 1000


def test_otlp_endpoint_gets_the_traces_path_once():
    for given in ("http://c:4318", "http://c:4318/", "http://c:4318/v1/traces"):
        exporter = build_span_exporter(settings(otel_exporter_otlp_endpoint=given))
        assert exporter._endpoint == "http://c:4318/v1/traces"


def test_azure_monitor_exporter_is_built_from_a_connection_string():
    cs = "InstrumentationKey=00000000-0000-0000-0000-000000000000;IngestionEndpoint=https://example.in.applicationinsights.azure.com/"
    exporter = build_span_exporter(settings(applicationinsights_connection_string=cs))
    assert type(exporter).__name__ == "AzureMonitorTraceExporter"
    assert build_span_exporter(settings(otel_exporter_otlp_endpoint="http://c:1", applicationinsights_connection_string=cs)).__class__.__name__ == "OTLPSpanExporter"


# ---- MLflow (a real file store) -----------------------------------------------------------------------------------
@pytest.fixture
def mlflow_service(tmp_path):
    uri = f"sqlite:///{(tmp_path / 'mlflow.db').as_posix()}"  # MLflow's file store is deprecated: use a database
    svc = EngagementService(settings(mlflow_tracking_uri=uri, mlflow_experiment="test-exp",
                                     mlflow_artifact_location=(tmp_path / "artifacts").as_uri()))
    assert svc.mlflow is not None
    return svc


def runs_of(svc):
    svc.flush_exports()  # exports run on a background worker so they never slow an engagement
    return svc.mlflow.client.search_runs([svc.mlflow.experiment_id])


def test_each_engagement_becomes_one_mlflow_run_with_metrics_params_and_artifacts(mlflow_service):
    svc = mlflow_service
    wid = svc.start(**REQ)["workflow_id"]
    runs = runs_of(svc)
    assert len(runs) == 1
    run = runs[0]
    assert run.data.tags["workflow_id"] == wid and run.data.tags["status"] == "awaiting_approval"
    assert run.data.tags["data_classification"] == "confidential" and run.data.tags["risk_level"] == "high"
    m = run.data.metrics
    assert m["cost_usd"] > 0 and m["llm_calls"] >= 7 and m["score.groundedness"] > 0 and m["successful"] == 0.0
    assert run.data.params["policy_version"] == svc.policy.version and run.data.params["provider"] == "stub"
    assert "discovery@v1" in run.data.params["prompts"]
    arts = {a.path for a in svc.mlflow.client.list_artifacts(run.info.run_id)}
    assert {"trace.json", "guardian_decisions.json"} <= arts


def test_the_artifact_trace_has_structure_but_no_payloads(mlflow_service, tmp_path):
    svc = mlflow_service
    svc.start(**REQ)
    run = runs_of(svc)[0]
    path = svc.mlflow.client.download_artifacts(run.info.run_id, "trace.json", str(tmp_path / "dl"))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    trace = json.loads(text)
    assert trace["span_count"] > 30 and any(s["kind"] == "llm" for s in trace["spans"])
    assert "consultai.tool_result" not in text or "[redacted" in text
    assert "SYNTHETIC DEMO DATA" not in text  # retrieved passages never leave


def test_the_partners_decision_lands_on_the_same_run_beside_the_judges_scores(mlflow_service):
    svc = mlflow_service
    wid = svc.start(**REQ)["workflow_id"]
    svc.approve(wid, "reject", reason="too risky", approver=PARTNER)
    runs = runs_of(svc)
    assert len(runs) == 1  # updated, not duplicated
    run = runs[0]
    assert run.data.tags["human_decision"] == "reject" and run.data.tags["status"] == "rejected"
    assert run.data.metrics["human_decision_value"] == 0.0 and run.data.metrics["decision_seconds"] >= 0
    assert run.data.metrics["score.groundedness"] > 0 and run.info.status == "FINISHED"


def test_an_unreachable_mlflow_never_stops_the_service_or_a_run(tmp_path):
    import time
    t0 = time.monotonic()
    svc = EngagementService(settings(mlflow_tracking_uri="http://127.0.0.1:1"))  # nothing listens here
    assert svc.mlflow is None and time.monotonic() - t0 < 30  # fails fast: MLflow's 7 backoff retries are bounded
    assert svc.start(**REQ)["status"] == "awaiting_approval"


def test_an_mlflow_error_during_export_is_logged_not_raised(mlflow_service, monkeypatch):
    svc = mlflow_service
    monkeypatch.setattr(svc.mlflow, "log_run", lambda **kw: (_ for _ in ()).throw(RuntimeError("mlflow down")))
    assert svc.start(**REQ)["status"] == "awaiting_approval"
    svc.flush_exports()  # the failure happened on the worker and was logged, not raised


def test_a_slow_mlflow_never_delays_the_engagement(mlflow_service, monkeypatch):
    import time
    svc = mlflow_service
    monkeypatch.setattr(svc.mlflow, "log_run", lambda **kw: time.sleep(1.5))
    t0 = time.monotonic()
    svc.start(**REQ)
    assert time.monotonic() - t0 < 1.0  # the response did not wait for the export
    svc.flush_exports()
