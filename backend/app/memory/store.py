"""Memory classes: short-term turns, long-term facts/preferences/decisions, summaries, and the
retrieval log. In-memory now; the Cosmos DB implementation (same methods) lands with the Azure
adapters. Long-term writes go through `observe`, which applies the classification rule."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from .classifier import SENSITIVE_REASON, MemoryDecision, classify_memory

FACT_TTL_DAYS = 180  # engagement facts go stale; preferences and decisions do not


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass
class MemoryItem:
    type: str            # preference | fact | decision | summary
    scope: str           # engagement | user | global
    value: Any
    confidence: str = "high"
    source: str = "user"
    created_at: str = field(default_factory=lambda: _now().isoformat())
    expires_at: str | None = None

    def expired(self, now: dt.datetime | None = None) -> bool:
        return self.expires_at is not None and dt.datetime.fromisoformat(self.expires_at) <= (now or _now())


class MemoryStore:
    """Not every sentence becomes long-term memory: use `observe`, or classify before `remember`."""

    def __init__(self) -> None:
        self.short_term: dict[str, list[dict]] = {}
        self.long_term: dict[str, list[MemoryItem]] = {}
        self.summaries: dict[str, list[str]] = {}
        self.retrievals: dict[str, list[Any]] = {}

    # -- short-term -------------------------------------------------------------------------
    def add_turn(self, conversation_id: str, role: str, content: str) -> None:
        self.short_term.setdefault(conversation_id, []).append({"role": role, "content": content})

    def add_summary(self, conversation_id: str, summary: str) -> None:
        self.summaries.setdefault(conversation_id, []).append(summary)

    # -- long-term --------------------------------------------------------------------------
    def remember(self, key: str, item: MemoryItem) -> None:
        self.long_term.setdefault(key, []).append(item)

    def recall(self, key: str, scope: str | None = None) -> list[MemoryItem]:
        return [i for i in self.long_term.get(key, [])
                if (scope is None or i.scope == scope) and not i.expired()]

    def observe(self, *, conversation_id: str, user_id: str, text: str, role: str = "user",
                engagement_id: str | None = None) -> MemoryDecision:
        """Record a turn, and promote it to long-term memory only if the rule says it is durable
        and safe. Sensitive text is not kept verbatim even in short-term history."""
        decision = classify_memory(text, engagement_scoped=engagement_id is not None)
        self.add_turn(conversation_id, role, "[redacted]" if decision.reason == SENSITIVE_REASON else text)
        if not decision.store:
            return decision
        key = f"{decision.scope}:{engagement_id if decision.scope == 'engagement' else user_id}"
        if any(i.value == text for i in self.long_term.get(key, [])):
            return MemoryDecision(False, reason="duplicate")
        expires = (_now() + dt.timedelta(days=FACT_TTL_DAYS)).isoformat() if decision.type == "fact" else None
        self.remember(key, MemoryItem(decision.type, decision.scope, text, source=role, expires_at=expires))
        return decision

    # -- retrievals -------------------------------------------------------------------------
    def log_retrieval(self, workflow_id: str, record: Any) -> None:
        self.retrievals.setdefault(workflow_id, []).append(record)
