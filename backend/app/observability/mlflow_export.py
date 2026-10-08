"""MLflow tracking for engagement runs.

Each engagement becomes one MLflow run: scores and cost as metrics, the models and policy as parameters,
and a structure-only trace as an artifact (payloads are never sent: they can hold client data). When a
partner decides, the decision is written onto the same run, which is what lets the LLM judge be
calibrated against human judgement later: score and decision sit side by side.

Uses the explicit-run MlflowClient API, so it is safe to call from any thread without global state.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from app.observability.redaction import redact_trace

log = logging.getLogger(__name__)

DECISION_VALUE = {"approve": 1.0, "modify": 0.5, "reject": 0.0}
_RUN_METRICS = ("cost_usd", "duration_sec", "input_tokens", "output_tokens", "tool_calls", "tool_errors",
                "llm_calls", "llm_repairs", "llm_fallbacks", "retries", "blocked_actions", "escalations")


class MlflowLogger:
    def __init__(self, tracking_uri: str, experiment: str = "consultai", client: Any = None,
                 artifact_location: str | None = None):
        if client is None:
            # MLflow's defaults (7 retries with exponential backoff) can stall for minutes on a dead server.
            # Telemetry must fail fast, so bound it unless the operator chose otherwise.
            for key, value in {"MLFLOW_HTTP_REQUEST_MAX_RETRIES": "1", "MLFLOW_HTTP_REQUEST_TIMEOUT": "5",
                               "MLFLOW_HTTP_REQUEST_BACKOFF_FACTOR": "1", "MLFLOW_DISABLE_AGENT_HINT": "1"}.items():
                os.environ.setdefault(key, value)
            from mlflow.tracking import MlflowClient

            client = MlflowClient(tracking_uri=tracking_uri)
        self.client = client
        found = client.get_experiment_by_name(experiment)
        # MLflow's default artifact folder is the current directory: always give it a deliberate location
        self.experiment_id = found.experiment_id if found else client.create_experiment(
            experiment, **({"artifact_location": artifact_location} if artifact_location else {}))

    def _find_run(self, workflow_id: str) -> str | None:
        runs = self.client.search_runs([self.experiment_id], filter_string=f"tags.workflow_id = '{workflow_id}'", max_results=1)
        return runs[0].info.run_id if runs else None

    def log_run(self, *, metrics_row: dict[str, Any], trace: dict[str, Any], guardian: list[dict[str, Any]],
                policy_version: str, models: dict[str, str], provider: str) -> str:
        """Create or update the engagement's run. Safe to call again when the run pauses and again when it ends."""
        wid = metrics_row["workflow_id"]
        run_id = self._find_run(wid)
        if run_id is None:
            run = self.client.create_run(self.experiment_id, run_name=wid, tags={"workflow_id": wid})
            run_id = run.info.run_id
        c = self.client
        for key, value in {"status": metrics_row["status"], "data_classification": metrics_row["data_classification"],
                           "risk_level": metrics_row.get("risk_level") or "unknown",
                           "successful": str(metrics_row["successful"]).lower()}.items():
            c.set_tag(run_id, key, value)
        prompts = sorted({s["attributes"].get("consultai.prompt") for s in trace["spans"]
                          if s["kind"] == "llm" and s["attributes"].get("consultai.prompt")})
        for key, value in {"policy_version": policy_version, "provider": provider, "prompts": ",".join(prompts),
                           **{f"model_{k.lower()}": v for k, v in models.items()}}.items():
            c.log_param(run_id, key, str(value)[:250]) if run_id and not self._has_param(run_id, key) else None
        from mlflow.entities import Metric

        now = 0
        batch = [Metric(k, float(metrics_row[k]), now, 0) for k in _RUN_METRICS if metrics_row.get(k) is not None]
        batch += [Metric(f"score.{k}", float(v), now, 0) for k, v in metrics_row["scores"].items()]
        batch.append(Metric("successful", 1.0 if metrics_row["successful"] else 0.0, now, 0))
        c.log_batch(run_id, metrics=batch)
        safe, _ = redact_trace(trace, show_payloads=False)  # structure only, PII scrubbed
        c.log_dict(run_id, {k: safe[k] for k in ("trace_id", "workflow_id", "span_count", "spans")}, "trace.json")
        c.log_dict(run_id, guardian, "guardian_decisions.json")
        if metrics_row["status"] in {"completed", "rejected", "escalated", "failed"}:
            c.set_terminated(run_id, "FAILED" if metrics_row["status"] == "failed" else "FINISHED")
        return run_id

    def _has_param(self, run_id: str, key: str) -> bool:
        return key in self.client.get_run(run_id).data.params

    def log_decision(self, workflow_id: str, decision: str, decision_seconds: float | None) -> None:
        """Record the partner's decision on the run, next to the judge's scores."""
        run_id = self._find_run(workflow_id)
        if run_id is None:
            return
        self.client.set_tag(run_id, "human_decision", decision)
        self.client.log_metric(run_id, "human_decision_value", DECISION_VALUE.get(decision, 0.0))
        if decision_seconds is not None:
            self.client.log_metric(run_id, "decision_seconds", float(decision_seconds))
