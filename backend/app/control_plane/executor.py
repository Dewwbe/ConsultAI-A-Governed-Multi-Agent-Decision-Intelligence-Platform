"""Single choke point for tool execution: guardian -> schema -> budget -> trace -> run."""
from __future__ import annotations

import time
from typing import Any

from app.observability.tracing import TraceStore

from .budget import Budget
from .guardian import Guardian
from .reliability import CircuitBreaker, call_with_retry
from .tool_registry import ToolRegistry


class ToolBlocked(Exception):
    def __init__(self, decision: dict[str, Any]):
        super().__init__("; ".join(decision["reasons"]))
        self.decision = decision


class ToolArgsInvalid(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, guardian: Guardian, budget: Budget,
                 trace: TraceStore, state_log: dict[str, list]):
        self.registry, self.guardian, self.budget, self.trace = registry, guardian, budget, trace
        self.log = state_log  # shared lists: guardian_decisions, failures
        self._breakers: dict[str, CircuitBreaker] = {}

    def call(self, agent: str, tool: str, args: dict[str, Any], resource: str | None = None) -> Any:
        contract = self.registry.get(tool)
        decision = self.guardian.review_tool_call(agent, tool, args, resource)
        self.log["guardian_decisions"].append(decision.to_dict())
        if decision.action != "ALLOW":
            raise ToolBlocked(decision.to_dict())

        errors = contract.validate(args)
        if errors:
            self.log["failures"].append({"type": "invalid_schema", "tool": tool, "errors": errors})
            raise ToolArgsInvalid(errors)

        self.budget.record(tool_calls=1, cost_usd=contract.cost_usd)
        breaker = self._breakers.setdefault(tool, CircuitBreaker())
        with self.trace.span(f"tool:{tool}", "tool", **{
                "gen_ai.agent.name": agent, "gen_ai.tool.name": tool,
                "consultai.tool_arguments": args, "consultai.risk_level": contract.risk_level,
                "consultai.cost_usd": contract.cost_usd}) as span:
            t0 = time.perf_counter()
            result = call_with_retry(lambda: contract.fn(**args),
                                     max_attempts=1 + contract.max_retries, breaker=breaker)
            if (time.perf_counter() - t0) * 1000 > contract.timeout_ms:
                span.attributes["consultai.slow"] = True  # hard cancel arrives with async tools (Phase 6)
            return result
