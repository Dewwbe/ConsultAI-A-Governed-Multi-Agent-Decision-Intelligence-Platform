"""Semantic cache: reuse an earlier answer for a near-identical question, safely.

An entry is only served if ALL hold: same `embedding_version` (vectors are comparable), same
`source_version` (the underlying data/index has not changed), not expired, an identical
`scope` (e.g. the retrieval filters/permissions it was computed under, so a cached result can
never leak across users or classifications), and similarity above the threshold.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .embeddings import Embedder, cosine


@dataclass
class CacheEntry:
    query: str
    vector: list[float]
    value: Any
    scope: str
    source_version: str
    embedding_version: str
    created_at: dt.datetime
    expires_at: dt.datetime


class SemanticCache:
    def __init__(self, embedder: Embedder, threshold: float = 0.92, ttl_sec: float = 3600,
                 max_entries: int = 512,
                 clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC)):
        self.embedder, self.threshold, self.ttl = embedder, threshold, dt.timedelta(seconds=ttl_sec)
        self.max_entries, self._clock = max_entries, clock
        self.entries: list[CacheEntry] = []
        self.hits = self.misses = 0

    def get(self, query: str, *, source_version: str, scope: str = "") -> Any | None:
        now, vec = self._clock(), self.embedder.embed(query)
        self.entries = [e for e in self.entries if e.expires_at > now]  # drop expired
        best, best_sim = None, 0.0
        for e in self.entries:
            if (e.embedding_version != self.embedder.name or e.source_version != source_version
                    or e.scope != scope):
                continue
            sim = cosine(vec, e.vector)
            if sim >= self.threshold and sim > best_sim:
                best, best_sim = e, sim
        if best is None:
            self.misses += 1
            return None
        self.hits += 1
        return best.value

    def put(self, query: str, value: Any, *, source_version: str, scope: str = "") -> None:
        now = self._clock()
        self.entries.append(CacheEntry(query, self.embedder.embed(query), value, scope, source_version,
                                       self.embedder.name, now, now + self.ttl))
        del self.entries[:-self.max_entries]  # oldest out

    def invalidate_source(self, source_version: str) -> int:
        """Drop everything not built from `source_version` (call when a source is re-ingested)."""
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.source_version == source_version]
        return before - len(self.entries)
