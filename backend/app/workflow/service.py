"""EngagementService: wires the control plane, runs the graph, handles approval resume."""
from __future__ import annotations

import datetime as dt
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
from app.knowledge.retriever import LocalRetriever, ReplayMismatch
from app.knowledge.semantic_cache import SemanticCache
from app.memory.store import MemoryStore
from app.observability.metrics import engagement_metrics
from app.observability.tracing import TraceStore
from app.workflow.graph import RUNTIMES, build_graph


class EngagementService:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.policy = PolicyEngine.from_file(self.settings.policy_file)
        self.graph = build_graph()
        self.memory = MemoryStore()
        self.index_retriever = LocalRetriever(DEMO_CORPUS)  # built once; Azure AI Search later
        self.cache = SemanticCache(self.index_retriever.embedder)
        self.registry = default_registry()
        self.traces: dict[str, TraceStore] = {}
        self.index: dict[str, dict[str, Any]] = {}  # workflow_id -> request summary, insertion-ordered
        self.llm_breaker = CircuitBreaker()  # shared across engagements: one provider, one health

    def _runtime(self, workflow_id: str) -> RuntimeContext:
        s = self.settings
        trace = TraceStore(workflow_id)
        budget = Budget(s.max_tokens, s.max_cost_usd, s.max_duration_sec, s.max_tool_calls)
        guardian = Guardian(self.policy)
        log: dict[str, list] = {"guardian_decisions": [], "failures": []}
        llm = LLMGateway(ModelRouter(self.policy), self._provider(), budget, trace, log,
                         breaker=self.llm_breaker)
        tools = ToolExecutor(self.registry, guardian, budget, trace, log)
        self.traces[workflow_id] = trace
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

    def start(self, *, business_problem: str, industry: str = "", objectives: list[str] | None = None,
              constraints: list[str] | None = None, user_id: str = "anonymous",
              data_classification: str = "confidential") -> dict[str, Any]:
        wid = f"wf_{uuid.uuid4().hex[:10]}"
        RUNTIMES[wid] = self._runtime(wid)
        self.index[wid] = {"business_problem": business_problem, "industry": industry,
                           "created_at": dt.datetime.now(dt.UTC).isoformat()}
        for text in [*(objectives or []), *(constraints or [])]:  # only durable, safe text is kept
            self.memory.observe(conversation_id=f"conv_{wid[3:]}", user_id=user_id, text=text,
                                engagement_id=wid)
        self.graph.invoke({
            "workflow_id": wid, "engagement_id": wid, "conversation_id": f"conv_{wid[3:]}",
            "user_id": user_id, "preferences": {}, "data_classification": data_classification,
            "business_problem": business_problem, "industry": industry,
            "objectives": objectives or [], "constraints": constraints or [],
        }, self._cfg(wid))
        return self.get(wid)

    def approve(self, workflow_id: str, decision: str, changes: dict | None = None,
                reason: str = "") -> dict[str, Any]:
        if decision not in {"approve", "modify", "reject"}:
            raise ValueError("decision must be approve | modify | reject")
        self.graph.invoke(Command(resume={"decision": decision, "changes": changes or {},
                                          "reason": reason}), self._cfg(workflow_id))
        return self.get(workflow_id)

    def get(self, workflow_id: str) -> dict[str, Any]:
        snap = self.graph.get_state(self._cfg(workflow_id))
        state = dict(snap.values)
        ctx = RUNTIMES[workflow_id]
        summary = self.traces[workflow_id].summary()
        status = ("awaiting_approval" if snap.next else
                  "escalated" if state.get("halted") else
                  "rejected" if state.get("approval_status") == "rejected" else "completed")
        return {"workflow_id": workflow_id, "status": status, "pending_node": list(snap.next),
                "halted_reason": state.get("halted"),
                "state": state, "guardian_decisions": ctx.log["guardian_decisions"],
                "metrics": engagement_metrics(summary, {**state, **ctx.log}),
                "budget": {"tokens": ctx.budget.tokens, "cost_usd": round(ctx.budget.cost_usd, 6),
                           "tool_calls": ctx.budget.tool_calls}}

    def list(self, status: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Newest first. Status is derived from the checkpoint, so filter after computing it."""
        rows = []
        for wid in reversed(self.index):
            d = self.get(wid)
            if status and d["status"] != status:
                continue
            st = d["state"]
            rows.append({"workflow_id": wid, "status": d["status"], **self.index[wid],
                         "risk_level": st.get("risk_level"),
                         "recommendation": (st.get("recommendation") or {}).get("name"),
                         "cost_usd": d["budget"]["cost_usd"]})
        return {"items": rows[offset:offset + limit], "total": len(rows), "limit": limit, "offset": offset}

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
        return self.traces[workflow_id].summary()
