"""BaseAgent + runtime context. Agents never touch the control plane directly; they call
ctx.llm / ctx.tools, which enforce policy, schema, budget and tracing."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.control_plane.budget import Budget
from app.control_plane.degradation import DegradationState
from app.control_plane.executor import ToolExecutor
from app.control_plane.guardian import Guardian
from app.control_plane.llm import LLMGateway
from app.control_plane.policy import PolicyEngine
from app.knowledge.retriever import Retriever
from app.memory.store import MemoryStore
from app.observability.tracing import TraceStore
from app.schemas.state import EngagementState
from app.schemas.views import view_for


class InsufficientData(RuntimeError):
    """An agent cannot produce trustworthy output because required inputs are missing."""


@dataclass
class RuntimeContext:
    workflow_id: str
    policy: PolicyEngine
    guardian: Guardian
    budget: Budget
    trace: TraceStore
    llm: LLMGateway
    tools: ToolExecutor
    retriever: Retriever
    memory: MemoryStore
    log: dict[str, list]  # guardian_decisions, failures (shared with ToolExecutor)
    degradation: DegradationState = field(default_factory=DegradationState)  # how cautious to be for this run
    data_source: Any = None  # enterprise data (Databricks or the offline stand-in); None -> the agent default


class BaseAgent(ABC):
    name: str

    def __init__(self, ctx: RuntimeContext):
        self.ctx = ctx

    def run(self, state: EngagementState) -> dict[str, Any]:
        view = view_for(self.name, state)  # least-privilege slice
        with self.ctx.trace.span(self.name, "agent", **{"gen_ai.agent.name": self.name}):
            return self.execute(view)

    @abstractmethod
    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        """Return a partial state update containing only keys this agent owns."""
