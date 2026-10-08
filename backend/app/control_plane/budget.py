"""Engagement-level budget: tokens, cost, duration, tool calls."""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    max_tokens: int = 100_000
    max_cost_usd: float = 2.0
    max_duration_sec: int = 300
    max_tool_calls: int = 100
    tokens: int = 0
    cost_usd: float = 0.0
    tool_calls: int = 0
    started: float = field(default_factory=time.monotonic)

    def record(self, tokens: int = 0, cost_usd: float = 0.0, tool_calls: int = 0) -> None:
        self.tokens += tokens
        self.cost_usd += cost_usd
        self.tool_calls += tool_calls
        self.check()

    def check(self) -> None:
        if self.tokens > self.max_tokens:
            raise BudgetExceeded(f"token budget exceeded ({self.tokens}/{self.max_tokens})")
        if self.cost_usd > self.max_cost_usd:
            raise BudgetExceeded(f"cost budget exceeded (${self.cost_usd:.2f}/${self.max_cost_usd:.2f})")
        if self.tool_calls > self.max_tool_calls:
            raise BudgetExceeded(f"tool-call budget exceeded ({self.tool_calls}/{self.max_tool_calls})")
        if time.monotonic() - self.started > self.max_duration_sec:
            raise BudgetExceeded("duration budget exceeded")
