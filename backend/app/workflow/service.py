"""EngagementService: wires the control plane, runs the graph, persists everything, and handles
the human-approval resume.

Durability: engagements, approvals, the audit trail, live events and a runtime snapshot (budget,
trace, retrievals, logs) are stored through `Database`; LangGraph's checkpoint is stored by the
matching saver. A paused run therefore survives an API restart: the runtime is rebuilt from the
snapshot on demand and the graph resumes from its checkpoint.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any

from langgraph.types import Command

from app.adapters import build_backends
from app.agents.base import RuntimeContext
from app.config import Settings, get_settings
from app.control_plane.budget import Budget
from app.control_plane.degradation import DegradationController, DegradationState
from app.control_plane.executor import ToolExecutor
from app.control_plane.guardian import Guardian
from app.control_plane.limits import LimiterRegistry, QueueFull, RunScheduler
from app.control_plane.llm import AzureOpenAIProvider, LLMGateway, StubProvider
from app.control_plane.policy import PolicyEngine
from app.control_plane.providers import BreakerRegistry, FallbackLog
from app.control_plane.router import ModelRouter
from app.control_plane.tool_registry import default_registry
from app.knowledge.cached import CachedRetriever
from app.knowledge.retriever import ReplayMismatch, RetrievalRecord
from app.knowledge.semantic_cache import SemanticCache
from app.observability import aggregate
from app.observability.export import build_tracer_provider
from app.observability.metrics import engagement_metrics
from app.observability.mlflow_export import MlflowLogger
from app.observability.redaction import can_see_payloads, redact_trace
from app.observability.run_metrics import breakdown, compute_run_metrics
from app.observability.tracing import SpanRecord, TraceStore
from app.persistence.checkpointer import make_checkpointer
from app.persistence.db import Database
from app.security.auth import Principal
from app.security.rbac import Rbac
from app.workflow.graph import RUNTIMES, build_graph

# Recommendation fields a reviewer may change. Numbers are never editable: they trace to tool calls.
EDITABLE_CHANGES: dict[str, type] = {"rationale": str, "assumptions": list}
STEP_KINDS = {"agent", "evaluator", "guardian"}  # the approval pause has its own events


class Forbidden(PermissionError):
    """Caller lacks the approver role (HTTP 403)."""


class Conflict(RuntimeError):
    """Engagement is not awaiting approval (HTTP 409)."""


class Invalid(ValueError):
    """Approval request is malformed (HTTP 422)."""


class EngagementService:
    def __init__(self, settings: Settings | None = None, db: Database | None = None,
                 checkpointer: Any = None, span_exporter: Any = None, mlflow_logger: MlflowLogger | None = None):
        self.settings = settings or get_settings()
        self.policy = PolicyEngine.from_file(self.settings.policy_file)
        split = lambda v: [r.strip() for r in v.split(",") if r.strip()] if v else None
        self.rbac = Rbac.from_policy(self.policy.rbac, {
            "engagement:approve": [self.settings.approver_role] if self.settings.approver_role else None,
            "payload:view": split(self.settings.payload_roles)})
        self.db = db or Database(self.settings.database_url)
        if self.policy.sha256:
            self.db.record_policy(self.policy.version, self.policy.sha256, self.policy.source_text)
        self.graph = build_graph(checkpointer or make_checkpointer(self.settings.database_url))
        backends = build_backends(self.settings)
        self.memory, self.index_retriever, self.data_source = backends.memory, backends.retriever, backends.data_source
        self.cache = SemanticCache(backends.embedder)
        self.registry = default_registry()
        # Provider health is a fact about the provider, so breakers and the fallback log are shared by every run.
        self.breakers = BreakerRegistry()
        self.fallbacks = FallbackLog()
        self.extra_providers: dict[str, Any] = {}  # additional providers, tried in registration order
        self._degradation_lock = threading.Lock()
        self.degradation_controller = DegradationController(self.policy.thresholds, **self.policy.degradation)
        self.degradation = self._restore_degradation()
        self._futures: dict[str, Any] = {}
        policy_limits = self.policy.limits
        eng = policy_limits.get("engagements", {})
        self.scheduler = RunScheduler(
            self.settings.max_concurrent_runs or eng.get("max_concurrent", 4),
            self.settings.max_queued_runs if self.settings.max_queued_runs is not None else eng.get("max_queued", 20))
        self.limiters = LimiterRegistry(policy_limits.get("providers", {}))
        self._approval_lock = threading.Lock()
        # Optional telemetry. Each is off unless configured, and a failure to export never fails a run.
        self.tracer_provider = build_tracer_provider(self.settings, span_exporter)
        self.tracer = self.tracer_provider.get_tracer("consultai") if self.tracer_provider else None
        self.mlflow = mlflow_logger or self._build_mlflow()
        # one worker: exports stay in order and never delay an engagement, even if the destination is slow
        self._exports = ThreadPoolExecutor(max_workers=1, thread_name_prefix="export")
        self.db.mark_interrupted()  # runs that were mid-flight when a previous process died

    def _build_mlflow(self) -> MlflowLogger | None:
        if not self.settings.mlflow_tracking_uri:
            return None
        try:
            return MlflowLogger(self.settings.mlflow_tracking_uri, self.settings.mlflow_experiment,
                                artifact_location=self.settings.mlflow_artifact_location or None)
        except Exception:
            logging.getLogger(__name__).exception("MLflow is configured but unavailable; continuing without it")
            return None

    # -- runtime ----------------------------------------------------------------------------
    def _span_listener(self, workflow_id: str):
        def listen(phase: str, rec: SpanRecord) -> None:
            if rec.kind not in STEP_KINDS:
                return
            data = {"name": rec.name, "kind": rec.kind}
            if phase == "finished":
                data.update(status=rec.status, latency_ms=round(rec.latency_ms, 1))
            self.db.add_event(workflow_id, f"step_{phase}", data)
        return listen

    def _runtime(self, workflow_id: str) -> RuntimeContext:
        s = self.settings
        trace = TraceStore(workflow_id, listener=self._span_listener(workflow_id), tracer=self.tracer,
                           export_payloads=s.otel_export_payloads)
        budget = Budget(s.max_tokens, s.max_cost_usd, s.max_duration_sec, s.max_tool_calls)
        guardian = Guardian(self.policy)
        log: dict[str, list] = {"guardian_decisions": [], "failures": []}
        primary = self._provider()
        providers = {primary.name: primary, **self.extra_providers}
        degradation = self.degradation  # fixed for the whole run: it must not change its own behaviour mid-flight
        llm = LLMGateway(ModelRouter(self.policy, providers=list(providers), tier_boost=degradation.actions.tier_boost),
                         providers, budget, trace, log,
                         breaker=self.breakers, limiter=self.limiters, fallbacks=self.fallbacks,
                         pii_mode=self.policy.pii_mode)
        tools = ToolExecutor(self.registry, guardian, budget, trace, log)
        return RuntimeContext(workflow_id, self.policy, guardian, budget, trace, llm, tools,
                              CachedRetriever(self.index_retriever, self.cache), self.memory, log, degradation,
                              data_source=self.data_source)

    def _restore_degradation(self) -> DegradationState:
        """After a restart, carry on at the level we were at (it is part of how cautious to be)."""
        last = self.db.degradation_events_list(limit=1)
        if not last:
            return DegradationState()
        e = last[0]
        return DegradationState(e["to_level"], e["since"], tuple(e["reasons"]), e["metrics"], e["runs_considered"])

    def _update_degradation(self) -> None:
        """Re-evaluate quality after every finished run; record and apply any change of level."""
        try:
            with self._degradation_lock:
                new = self.degradation_controller.evaluate(self.db.run_metrics_rows(), self.degradation)
                if new.level != self.degradation.level:
                    self.db.add_degradation_event(self.degradation.level, new.level, new.to_dict())
                    logging.getLogger(__name__).warning("quality degradation: %s -> %s (%s)", self.degradation.level,
                                                        new.level, "; ".join(new.reasons))
                self.degradation = new
        except Exception:
            logging.getLogger(__name__).exception("degradation check failed")

    def register_provider(self, provider: Any) -> None:
        """Add a fallback provider. It is only ever used for data its policy classification permits."""
        self.extra_providers[provider.name] = provider

    def _provider(self):
        s = self.settings
        if s.llm_provider != "azure_openai":
            return StubProvider()
        return AzureOpenAIProvider(
            endpoint=s.azure_openai_endpoint, api_key=s.azure_openai_api_key,
            api_version=s.azure_openai_api_version, timeout_sec=s.llm_timeout_sec,
            deployments={"MODEL_SMALL": s.model_small, "MODEL_MEDIUM": s.model_medium,
                         "MODEL_REASONING": s.model_reasoning})

    def _cfg(self, workflow_id: str) -> dict:
        return {"configurable": {"thread_id": workflow_id}}

    def _snapshot(self, workflow_id: str) -> None:
        ctx = RUNTIMES[workflow_id]
        self.db.save_snapshot(workflow_id, {
            "budget": {"tokens": ctx.budget.tokens, "cost_usd": ctx.budget.cost_usd,
                       "tool_calls": ctx.budget.tool_calls,
                       "elapsed_sec": time.monotonic() - ctx.budget.started},
            "log": ctx.log,
            "retrievals": [asdict(r) for r in self.memory.retrievals.get(workflow_id, [])],
            "trace": {"trace_id": ctx.trace.trace_id, "spans": [s.__dict__ for s in ctx.trace.spans]}})

    def _ensure_runtime(self, workflow_id: str) -> RuntimeContext:
        """The runtime holds non-serialisable objects; after a restart rebuild it from the snapshot."""
        if workflow_id in RUNTIMES:
            return RUNTIMES[workflow_id]
        ctx = self._runtime(workflow_id)
        snap = self.db.load_snapshot(workflow_id)
        if snap:
            b = snap["budget"]
            ctx.budget.tokens, ctx.budget.cost_usd, ctx.budget.tool_calls = (
                b["tokens"], b["cost_usd"], b["tool_calls"])
            ctx.budget.started = time.monotonic() - b["elapsed_sec"]  # time spent paused is not billed
            ctx.log["guardian_decisions"].extend(snap["log"].get("guardian_decisions", []))
            ctx.log["failures"].extend(snap["log"].get("failures", []))
            ctx.trace.restore(snap["trace"]["trace_id"], snap["trace"]["spans"])
            self.memory.retrievals[workflow_id] = [RetrievalRecord(**r) for r in snap["retrievals"]]
        RUNTIMES[workflow_id] = ctx
        return ctx

    # -- running ----------------------------------------------------------------------------
    def start(self, *, business_problem: str, industry: str = "", objectives: list[str] | None = None,
              constraints: list[str] | None = None, user_id: str = "anonymous",
              data_classification: str = "confidential", wait: bool = True) -> dict[str, Any]:
        """Start an engagement. With wait=False it returns at once (status `running`) and the
        pipeline continues in the background; follow it through the events stream."""
        if self.scheduler.queued >= self.scheduler.max_queued and self.scheduler.would_queue():
            raise QueueFull()  # refuse before creating anything: the caller should retry later
        wid = f"wf_{uuid.uuid4().hex[:10]}"
        self.db.add_engagement(wid, user_id=user_id, business_problem=business_problem, industry=industry,
                               data_classification=data_classification, status="queued",
                               policy_version=self.policy.version)
        self.db.add_audit(actor_id=user_id, action="create_engagement", outcome="allowed", workflow_id=wid)
        RUNTIMES[wid] = self._runtime(wid)
        for text in [*(objectives or []), *(constraints or [])]:  # only durable, safe text is kept
            self.memory.observe(conversation_id=f"conv_{wid[3:]}", user_id=user_id, text=text,
                                engagement_id=wid)
        payload = {
            "workflow_id": wid, "engagement_id": wid, "conversation_id": f"conv_{wid[3:]}",
            "user_id": user_id, "preferences": {}, "data_classification": data_classification,
            "business_problem": business_problem, "industry": industry,
            "objectives": objectives or [], "constraints": constraints or [],
        }
        try:
            future, position = self.scheduler.submit(self._run_scheduled, wid, payload)
        except QueueFull:  # lost a race for the last queue place
            self.db.delete_engagement(wid)
            RUNTIMES.pop(wid, None)
            raise
        self._futures[wid] = future
        if position > 0:
            self.db.add_event(wid, "run_queued", {"position": position})
        if wait:
            future.result()
        return self.get(wid)

    def wait(self, workflow_id: str, timeout: float | None = None) -> None:
        future = self._futures.get(workflow_id)
        if future is not None:
            future.result(timeout)

    def _run_scheduled(self, workflow_id: str, payload: Any) -> None:
        """Runs when a slot is free. The deadline clock starts now, not while the run waited in the queue."""
        self.db.set_status(workflow_id, "running")
        RUNTIMES[workflow_id].budget.started = time.monotonic()
        self.db.add_event(workflow_id, "run_started", {})
        self._run(workflow_id, payload)

    def _run(self, workflow_id: str, payload: Any) -> None:
        try:
            self.graph.invoke(payload, self._cfg(workflow_id))
        except Exception as exc:  # noqa: BLE001  any crash becomes a visible `failed` run
            self._fail(workflow_id, exc)
        else:
            self._finish(workflow_id)

    def _fail(self, workflow_id: str, exc: BaseException) -> None:
        self.db.set_status(workflow_id, "failed", error=f"{type(exc).__name__}: {exc}"[:500])
        self.db.add_event(workflow_id, "run_failed", {"error": f"{type(exc).__name__}: {exc}"[:500]})
        self._snapshot(workflow_id)
        self._record_metrics(workflow_id, "failed")

    def _finish(self, workflow_id: str) -> str:
        snap = self.graph.get_state(self._cfg(workflow_id))
        state = dict(snap.values)
        status = ("awaiting_approval" if snap.next else
                  "escalated" if state.get("halted") else
                  "rejected" if state.get("approval_status") == "rejected" else "completed")
        self.db.set_status(workflow_id, status, halted_reason=state.get("halted"))
        rec = state.get("recommendation") or {}
        event = {"awaiting_approval": "approval_requested", "escalated": "run_escalated"}.get(status, "run_completed")
        self.db.add_event(workflow_id, event, {
            "status": status, "risk_level": state.get("risk_level"), "recommendation": rec.get("name"),
            "halted_reason": state.get("halted")})
        self._snapshot(workflow_id)
        self._record_metrics(workflow_id, status)
        return status

    def _record_metrics(self, workflow_id: str, status: str) -> None:
        """Store this run's metrics. Metrics must never break a run, so a failure here is logged and dropped."""
        try:
            ctx = RUNTIMES[workflow_id]
            state = dict(self.graph.get_state(self._cfg(workflow_id)).values)
            row = self.db.get_engagement(workflow_id)
            trace = ctx.trace.summary()
            metrics = compute_run_metrics(
                row=row, status=status, state=state, trace=trace,
                engagement_metrics=engagement_metrics(trace, {**state, **ctx.log}),
                guardian_decisions=ctx.log["guardian_decisions"], failures=ctx.log["failures"],
                thresholds=self.policy.thresholds)
            metrics["degradation_level"] = ctx.degradation.level
            self.db.save_run_metrics(metrics)
            self._update_degradation()
            self._export_to_mlflow(metrics, trace, ctx.log["guardian_decisions"])
        except Exception:
            logging.getLogger(__name__).exception("could not record run metrics for %s", workflow_id)

    def flush_exports(self, timeout: float = 30.0) -> None:
        """Wait for queued telemetry exports to finish (used by tests and on shutdown)."""
        self._exports.submit(lambda: None).result(timeout)
        if self.tracer_provider is not None:
            self.tracer_provider.force_flush()

    def _export_to_mlflow(self, metrics: dict[str, Any], trace: dict[str, Any], guardian: list[dict[str, Any]]) -> None:
        if self.mlflow is None:
            return
        self._exports.submit(self._do_export_to_mlflow, metrics, trace, guardian)

    def _do_export_to_mlflow(self, metrics: dict[str, Any], trace: dict[str, Any], guardian: list[dict[str, Any]]) -> None:
        try:
            s = self.settings
            self.mlflow.log_run(metrics_row=metrics, trace=trace, guardian=guardian, policy_version=self.policy.version,
                                models={"small": s.model_small, "medium": s.model_medium, "reasoning": s.model_reasoning},
                                provider=s.llm_provider)
        except Exception:
            logging.getLogger(__name__).exception("MLflow export failed for %s", metrics["workflow_id"])

    def _do_log_decision(self, workflow_id: str, decision: str, waited: float | None) -> None:
        try:
            if self.mlflow is not None:
                self.mlflow.log_decision(workflow_id, decision, waited)
        except Exception:
            logging.getLogger(__name__).exception("MLflow decision export failed for %s", workflow_id)

    # -- approval ---------------------------------------------------------------------------
    def approve(self, workflow_id: str, decision: str, changes: dict | None = None, reason: str = "",
                *, approver: Principal) -> dict[str, Any]:
        """Apply a human decision. Authorisation is enforced here, so every caller path is covered;
        every attempt (allowed or not) lands in the audit log with the caller's identity."""
        row = self.db.get_engagement(workflow_id)
        if row is None:
            raise KeyError(workflow_id)
        changes = changes or {}

        def audit(outcome: str, **detail: Any) -> None:
            self.db.add_audit(actor_id=approver.user_id, action="approval", outcome=outcome,
                              workflow_id=workflow_id, detail={"decision": decision, **detail})

        if not self.rbac.allows(approver, "engagement:approve"):
            needed = self.rbac.roles_for("engagement:approve")
            audit("denied", roles=list(approver.roles), required=needed)
            raise Forbidden(f"approving requires the '{' or '.join(needed)}' role")
        problem = self._validate_decision(decision, changes, reason)
        if problem:
            audit("invalid", error=problem)
            raise Invalid(problem)
        with self._approval_lock:  # a second approver racing this one gets a clean 409
            status = self.db.get_engagement(workflow_id)["status"]
            if status != "awaiting_approval":
                audit("conflict", status=status)
                raise Conflict(f"engagement is {status}, not awaiting approval")
            self.db.set_status(workflow_id, "running")
        self._ensure_runtime(workflow_id)
        before = dict(self.graph.get_state(self._cfg(workflow_id)).values)
        self.db.add_event(workflow_id, "approval_decided", {"decision": decision, "approver": approver.name})
        try:
            self.graph.invoke(Command(resume={"decision": decision, "changes": changes, "reason": reason}),
                              self._cfg(workflow_id))
        except Exception as exc:  # noqa: BLE001
            self._fail(workflow_id, exc)
        else:
            self._finish(workflow_id)
        resulting = self.db.get_engagement(workflow_id)["status"]
        asked = self.db.last_event(workflow_id, "approval_requested")
        waited = ((dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(asked["ts"])).total_seconds()
                  if asked else None)
        self.db.update_run_metrics(workflow_id, {"approval_decision": decision,
                                                 "decision_seconds": round(waited, 2) if waited is not None else None})
        if self.mlflow is not None:  # on the export worker, queued behind this run's own export, so it finds the run
            self._exports.submit(self._do_log_decision, workflow_id, decision, waited)
        self.db.add_approval(workflow_id, approver_id=approver.user_id, approver_name=approver.name,
                             roles=list(approver.roles), decision=decision, reason=reason, changes=changes,
                             resulting_status=resulting)
        self.db.add_decision_record(workflow_id, {
            "decision": decision, "reason": reason, "changes": changes, "approver_id": approver.user_id,
            "risk_level": before.get("risk_level"), "recommendation": before.get("recommendation"),
            "evaluation_scores": before.get("evaluation_scores"),
            "guardian": (before.get("guardian_decisions") or [None])[-1]})
        audit("allowed", resulting_status=resulting)
        return self.get(workflow_id)

    @staticmethod
    def _validate_decision(decision: str, changes: dict, reason: str) -> str | None:
        if decision not in {"approve", "modify", "reject"}:
            return "decision must be approve | modify | reject"
        if decision in {"modify", "reject"} and not reason.strip():
            return f"a reason is required to {decision}"
        if decision != "modify" and changes:
            return "changes are only allowed with decision=modify"
        if decision == "modify":
            if not changes:
                return "modify requires at least one change"
            bad = sorted(set(changes) - set(EDITABLE_CHANGES))
            if bad:
                return f"fields not editable: {bad}; editable: {sorted(EDITABLE_CHANGES)}"
            for k, v in changes.items():
                if not isinstance(v, EDITABLE_CHANGES[k]) or (
                        k == "assumptions" and not all(isinstance(x, str) for x in v)):
                    return f"'{k}' must be a {EDITABLE_CHANGES[k].__name__}"
        return None

    # -- reads ------------------------------------------------------------------------------
    def get(self, workflow_id: str) -> dict[str, Any]:
        row = self.db.get_engagement(workflow_id)
        if row is None:
            raise KeyError(workflow_id)
        ctx = self._ensure_runtime(workflow_id)
        snap = self.graph.get_state(self._cfg(workflow_id))
        state = dict(snap.values)
        status = row["status"]
        return {"workflow_id": workflow_id, "status": status,
                "pending_node": list(snap.next) if status == "awaiting_approval" else [],
                "halted_reason": row["halted_reason"] or state.get("halted"), "error": row["error"],
                "policy_version": row["policy_version"],
                "state": state, "guardian_decisions": ctx.log["guardian_decisions"],
                "metrics": engagement_metrics(ctx.trace.summary(), {**state, **ctx.log}),
                "budget": {"tokens": ctx.budget.tokens, "cost_usd": round(ctx.budget.cost_usd, 6),
                           "tool_calls": ctx.budget.tool_calls}}

    def list(self, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Newest first."""
        rows, total = self.db.list_engagements(status, limit, offset)
        items = []
        for r in rows:
            ctx = self._ensure_runtime(r["workflow_id"])
            state = dict(self.graph.get_state(self._cfg(r["workflow_id"])).values)
            items.append({"workflow_id": r["workflow_id"], "status": r["status"],
                          "business_problem": r["business_problem"], "industry": r["industry"],
                          "created_at": r["created_at"], "risk_level": state.get("risk_level"),
                          "recommendation": (state.get("recommendation") or {}).get("name"),
                          "cost_usd": round(ctx.budget.cost_usd, 6)})
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def evidence(self, workflow_id: str) -> dict[str, Any]:
        state = self.get(workflow_id)["state"]
        ctx = RUNTIMES[workflow_id]
        claims = state.get("research_results", [])
        by_source: dict[str, dict[str, Any]] = {}
        for c in claims:
            src = by_source.setdefault(c["source"], {"source": c["source"], "doc_ids": [], "claims": 0})
            src["claims"] += 1
            if c.get("doc_id") and c["doc_id"] not in src["doc_ids"]:
                src["doc_ids"].append(c["doc_id"])
        rejected = [{"reason": f["type"], "doc_ref": f.get("doc_ref", ""), "chunk_id": f.get("chunk_id")}
                    for f in ctx.log["failures"] if f.get("type") in {"unsupported_claim", "unverified_citation"}]
        return {"workflow_id": workflow_id, "claims": claims, "sources": list(by_source.values()),
                "retrievals": [asdict(r) for r in self.memory.retrievals.get(workflow_id, [])],
                "rejected_claims": rejected}

    def tables(self, workflow_id: str) -> dict[str, Any]:
        state = self.get(workflow_id)["state"]
        return {"workflow_id": workflow_id, "datasets": state.get("datasets", []),
                "table_context": state.get("table_context", {}),
                "queries": [{"query": a["query"], "row_count": len(a["rows"])}
                            for a in state.get("analysis_results", [])]}

    def replay_retrieval(self, workflow_id: str, retrieval_id: str) -> dict[str, Any]:
        """Re-derive what an agent saw from its stored record (not by re-running the search)."""
        self.get(workflow_id)  # 404 semantics for unknown workflows
        record = next((r for r in self.memory.retrievals.get(workflow_id, [])
                       if r.retrieval_id == retrieval_id), None)
        if record is None:
            raise KeyError(retrieval_id)
        try:
            ev = RUNTIMES[workflow_id].retriever.replay(record)
        except ReplayMismatch as exc:
            return {"retrieval_id": retrieval_id, "reproduced": False, "error": str(exc), "evidence": []}
        return {"retrieval_id": retrieval_id, "reproduced": True, "error": None,
                "evidence": [asdict(e) for e in ev]}

    def trace(self, workflow_id: str) -> dict[str, Any]:
        if self.db.get_engagement(workflow_id) is None:
            raise KeyError(workflow_id)
        return self._ensure_runtime(workflow_id).trace.summary()

    # -- metrics ----------------------------------------------------------------------------
    def metrics_summary(self, since: str | None = None, until: str | None = None,
                        status: str | None = None) -> dict[str, Any]:
        rows = self.db.run_metrics_rows(since, until, status)
        return {**aggregate.summarize(rows, self.policy.thresholds), "policy_version": self.policy.version,
                "thresholds": {k: float(v) for k, v in self.policy.thresholds.items()}, "since": since, "until": until}

    def metrics_timeseries(self, metric: str, bucket: str = "day", since: str | None = None,
                           until: str | None = None, status: str | None = None) -> dict[str, Any]:
        rows = self.db.run_metrics_rows(since, until, status)
        return {"metric": metric, "bucket": bucket, "points": aggregate.timeseries(rows, metric, bucket)}

    def cost_breakdown(self, workflow_id: str) -> dict[str, Any]:
        """Tokens and cost by agent and model, and how much of each budget this run used."""
        if self.db.get_engagement(workflow_id) is None:
            raise KeyError(workflow_id)
        ctx = self._ensure_runtime(workflow_id)
        trace = ctx.trace.summary()
        bd = breakdown(trace["spans"])
        b, s = ctx.budget, self.settings
        mine = next((m for m in self.db.run_metrics_rows() if m["workflow_id"] == workflow_id), None)
        ok = bool(mine and mine["successful"])
        return {"workflow_id": workflow_id, "total_cost_usd": round(trace["cost_usd"], 6),
                "input_tokens": trace["input_tokens"], "output_tokens": trace["output_tokens"],
                "successful": ok, "cost_per_successful_task": round(trace["cost_usd"], 6) if ok else None, **bd,
                "budget": {"tokens": {"used": b.tokens, "limit": s.max_tokens},
                           "cost_usd": {"used": round(b.cost_usd, 6), "limit": s.max_cost_usd},
                           "tool_calls": {"used": b.tool_calls, "limit": s.max_tool_calls},
                           "duration_sec": {"used": round(time.monotonic() - b.started, 1), "limit": s.max_duration_sec}}}

    def trace_for(self, workflow_id: str, principal: Principal) -> dict[str, Any]:
        """The trace as `principal` may see it: payloads gated by classification and role, PII always scrubbed."""
        row = self.db.get_engagement(workflow_id)
        if row is None:
            raise KeyError(workflow_id)
        show = can_see_payloads(principal, owner_id=row["user_id"], classification=row["data_classification"],
                                privileged_roles=self.rbac.roles_for("payload:view"))
        trace, redaction = redact_trace(
            self.trace(workflow_id), show_payloads=show,
            reason=f"{row['data_classification']} engagement: payloads need the owner, Partner or Admin role")
        return {**trace, "redaction": {"payloads_redacted": redaction.payloads_redacted,
                                       "pii_scrubbed": redaction.pii_scrubbed, "reason": redaction.reason}}

    def approvals(self, workflow_id: str) -> list[dict[str, Any]]:
        self.get(workflow_id)
        return self.db.approvals_for(workflow_id)

    def guardian(self, workflow_id: str) -> list[dict[str, Any]]:
        return self.get(workflow_id)["guardian_decisions"]

    def events_after(self, workflow_id: str, after: int = 0) -> list[dict[str, Any]]:
        if self.db.get_engagement(workflow_id) is None:
            raise KeyError(workflow_id)
        return self.db.events_after(workflow_id, after)
