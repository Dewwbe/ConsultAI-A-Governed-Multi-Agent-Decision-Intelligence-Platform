"""Retriever wrapper that serves repeated searches from a SemanticCache.

Cache scope is the exact filter set plus `k`, so a result computed under one caller's
permissions/classification is never served to another; `source_version` is the index version,
so re-ingesting content invalidates stale entries automatically.
"""
from __future__ import annotations

import json
from typing import Any

from .retriever import Evidence, RetrievalRecord, Retriever
from .semantic_cache import SemanticCache


class CachedRetriever:
    def __init__(self, inner: Retriever, cache: SemanticCache):
        self.inner, self.cache = inner, cache

    def search(self, query: str, filters: dict | None = None, k: int = 5
               ) -> tuple[list[Evidence], RetrievalRecord]:
        version = getattr(self.inner, "index_version", "")
        scope = json.dumps({"f": filters or {}, "k": k}, sort_keys=True, default=str)
        hit = self.cache.get(query, source_version=version, scope=scope)
        if hit is not None:
            return hit
        result = self.inner.search(query, filters=filters, k=k)
        self.cache.put(query, result, source_version=version, scope=scope)
        return result

    def replay(self, record: RetrievalRecord) -> list[Evidence]:
        return self.inner.replay(record)  # replays always read the source, never the cache

    def __getattr__(self, name: str) -> Any:  # chunks, index_version, metadata_for ...
        return getattr(self.inner, name)
