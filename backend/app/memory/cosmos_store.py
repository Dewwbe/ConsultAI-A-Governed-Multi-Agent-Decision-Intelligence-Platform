"""Cosmos DB `MemoryStore`: the same methods as the in-memory store, persisted.

One container, partitioned by `/pk`, holds four kinds of item (`kind`: turn, summary, memory, retrieval). The
in-memory store's rules still apply because this subclass only changes where data lives: `observe` classifies before
anything is remembered, sensitive text is never stored verbatim, facts expire, and long-term items carry a Cosmos TTL
so expiry is enforced by the service as well as on read. The container client is injected for tests.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from typing import Any

from .store import MemoryItem, MemoryStore


def _ttl(item: MemoryItem) -> int | None:
    if item.expires_at is None:
        return None
    return max(1, int((dt.datetime.fromisoformat(item.expires_at) - dt.datetime.now(dt.UTC)).total_seconds()))


class CosmosMemoryStore(MemoryStore):
    def __init__(self, container: Any) -> None:
        super().__init__()
        self.container = container
        self._hydrated: set[str] = set()

    def _put(self, pk: str, kind: str, body: dict[str, Any], ttl: int | None = None) -> None:
        doc = {"id": uuid.uuid4().hex, "pk": pk, "kind": kind, **body}
        if ttl is not None:
            doc["ttl"] = ttl
        self.container.create_item(doc)

    def _get(self, pk: str, kind: str) -> list[dict[str, Any]]:
        return list(self.container.query_items(
            query="SELECT * FROM c WHERE c.pk = @pk AND c.kind = @kind ORDER BY c._ts",
            parameters=[{"name": "@pk", "value": pk}, {"name": "@kind", "value": kind}], partition_key=pk))

    # -- short-term -------------------------------------------------------------------------
    def add_turn(self, conversation_id: str, role: str, content: str) -> None:
        super().add_turn(conversation_id, role, content)
        self._put(conversation_id, "turn", {"role": role, "content": content})

    def add_summary(self, conversation_id: str, summary: str) -> None:
        super().add_summary(conversation_id, summary)
        self._put(conversation_id, "summary", {"summary": summary})

    def turns(self, conversation_id: str) -> list[dict]:
        return [{"role": d["role"], "content": d["content"]} for d in self._get(conversation_id, "turn")]

    # -- long-term --------------------------------------------------------------------------
    def remember(self, key: str, item: MemoryItem) -> None:
        super().remember(key, item)
        self._put(key, "memory", {"item": dataclasses.asdict(item)}, _ttl(item))

    def recall(self, key: str, scope: str | None = None) -> list[MemoryItem]:
        items = [MemoryItem(**d["item"]) for d in self._get(key, "memory")]
        return [i for i in items if (scope is None or i.scope == scope) and not i.expired()]

    def observe(self, **kwargs: Any):
        """Hydrate the keys `observe` may write to once per process, so its duplicate check sees what is already stored."""
        for key in (f"engagement:{kwargs.get('engagement_id')}", f"user:{kwargs['user_id']}"):
            if key not in self._hydrated:
                self._hydrated.add(key)
                self.long_term.setdefault(key, []).extend(self.recall(key))
        return super().observe(**kwargs)

    # -- retrievals -------------------------------------------------------------------------
    def log_retrieval(self, workflow_id: str, record: Any) -> None:
        super().log_retrieval(workflow_id, record)
        self._put(workflow_id, "retrieval", {"record": dataclasses.asdict(record)})
