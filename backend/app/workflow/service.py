"""EngagementService: wires the control plane, runs the graph, persists everything, and handles
the human-approval resume.

Durability: engagements, approvals, the audit trail, live events and a runtime snapshot (budget,
trace, retrievals, logs) are stored through `Database`; LangGraph's checkpoint is stored by the
matching saver. A paused run therefore survives an API restart: the runtime is rebuilt from the
snapshot on demand and the graph resumes from its checkpoint.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict
from typing import Any

from langgraph.types import Command

from app.agents.base import RuntimeContext
from app.config import Settings, get_settings
from app.control_plane.budget import Budget
from app.control_plane.executor import ToolExecutor
from app.control_plane.guardian import Guardian
from app.control_plane.llm import AzureOpenAIProvider, LLMGateway, StubProvider
from app.control_plane.policy import PolicyEngine
from app.control_plane.reliability import CircuitBreaker
from app.control_plane.router import ModelRouter
from app.control_plane.tool_registry import default_registry
from app.knowledge.cached import CachedRetriever
from app.knowledge.demo_corpus import DEMO_CORPUS
from app.knowledge.retriever import LocalRetriever, ReplayMismatch, RetrievalRecord
from app.knowledge.semantic_cache import SemanticCache
from app.memory.store import MemoryStore
from app.observability.metrics import engagement_metrics
from app.observability.tracing import SpanRecord, TraceStore
from app.persistence.checkpointer import make_checkpointer
from app.persistence.db import Database
from app.security.auth import Principal
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
                 checkpointer: Any = None):
        self.settings = settings or get_settings()
        self.policy = PolicyEngine.from_file(self.settings.policy_file)
        self.db = db or Database(self.settings.database_url)
        self.graph = build_graph(checkpointer or make_checkpointer(self.settings.database_url))
        self.memory = MemoryStore()
        self.index_retriever = LocalRetriever(DEMO_CORPUS)  # built once; Azure AI Search later
        self.cache = SemanticCache(self.index_retriever.embedder)
        self.registry = default_registry()
        self.llm_breaker = CircuitBreaker()  # shared across engagements: one provider, one health
        self._threads: dict[str, threading.Thread] = {}
        self._approval_lock = threading.Lock()
        self.db.mark_interrupted()  # runs that were mid-flight when a previous process died

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
        trace = TraceStore(workflow_id, listener=self._span_listener(workflow_id))
        budget = Budget(s.max_tokens, s.max_cost_usd, s.max_duration_sec, s.max_tool_calls)
        guardian = Guardian(self.policy)
        log: dict[str, list] = {"guardian_decisions": [], "failures": []}
        llm = LLMGateway(ModelRouter(self.policy), self._provider(), budget, trace, log,
                         breaker=self.llm_breaker)
        tools = ToolExecutor(self.registry, guardian, budget, trace, log)
        return RuntimeContext(workflow_id, self.policy, guardian, budget, trace, llm, tools,
                              CachedRetriever(self.index_retriever, self.cache), self.memory, log)

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
        wid = f"wf_{uuid.uuid4().hex[:10]}"
        self.db.add_engagement(wid, user_id=user_id, business_problem=business_problem, industry=industry,
                               data_classification=data_classification)
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
        self.db.add_event(wid, "run_started", {})
        if wait:
            self._run(wid, payload)
        else:
            t = threading.Thread(target=self._run, args=(wid, payload), daemon=True, name=f"run-{wid}")
            self._threads[wid] = t
            t.start()
        return self.get(wid)

    def wait(self, workflow_id: str, timeout: float | None = None) -> None:
        t = self._threads.get(workflow_id)
        if t:
            t.join(timeout)

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
        return status

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

        if not approver.has_role(self.settings.approver_role):
            audit("denied", roles=list(approver.roles), required=self.settings.approver_role)
            raise Forbidden(f"approving requires the '{self.settings.approver_role}' role")
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

    def approvals(self, workflow_id: str) -> list[dict[str, Any]]:
        self.get(workflow_id)
        return self.db.approvals_for(workflow_id)

    def guardian(self, workflow_id: str) -> list[dict[str, Any]]:
        return self.get(workflow_id)["guardian_decisions"]

    def events_after(self, workflow_id: str, after: int = 0) -> list[dict[str, Any]]:
        if self.db.get_engagement(workflow_id) is None:
            raise KeyError(workflow_id)
        return self.db.events_after(workflow_id, after)
