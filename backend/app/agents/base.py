"""BaseAgent + runtime context. Agents never touch the control plane directly; they call
ctx.llm / ctx.tools, which enforce policy, schema, budget and tracing."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.control_plane.budget import Budget
from app.control_plane.executor import ToolExecutor
from app.control_plane.guardian import Guardian
from app.control_plane.llm import LLMGateway
from app.control_plane.policy import PolicyEngine
from app.knowledge.retriever import Retriever
from app.memory.store import MemoryStore
from app.observability.tracing import TraceStore
from app.schemas.state import EngagementState
from app.schemas.views import view_for


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
