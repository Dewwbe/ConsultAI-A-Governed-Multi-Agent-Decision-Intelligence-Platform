"""Retriever abstraction. `LocalRetriever` is a complete offline implementation (chunking,
BM25 + embedding hybrid ranking, metadata and permission filters, replayable records) so
Phase 2 runs without cloud services. `AzureSearchRetriever` implements the same Protocol
against Azure AI Search once the service exists."""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

from .chunking import Chunk, chunk_document
from .embeddings import Embedder, HashingEmbedder, cosine

CLASSIFICATION_RANK = {"public": 0, "internal": 1, "confidential": 2}
_TOKEN = re.compile(r"\w+")


@dataclass
class Evidence:
    claim: str
    source: str
    publication_date: str
    retrieved_at: str
    evidence: str
    confidence: float
    relevance: float
    doc_id: str = ""
    chunk_id: str = ""


@dataclass
class RetrievalRecord:
    """Stored for reproducibility: what did the agent actually see?"""
    retrieval_id: str
    query: str
    index: str
    document_ids: list[str]
    scores: list[float]
    retrieved_at: str
    filters: dict
    embedding_model: str = "n/a"
    reranker: str = "n/a"
    chunk_ids: list[str] = field(default_factory=list)
    content_hashes: list[str] = field(default_factory=list)  # lets a replay detect changed content
    index_version: str = ""
    k: int = 5


class ReplayMismatch(RuntimeError):
    """A stored retrieval can no longer be reproduced exactly (content changed or removed)."""


class Retriever(Protocol):
    def search(self, query: str, filters: dict | None = None, k: int = 5
               ) -> tuple[list[Evidence], RetrievalRecord]: ...

    def replay(self, record: RetrievalRecord) -> list[Evidence]: ...


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class LocalRetriever:
    """Filters: `country`, `industry` (a chunk that declares a different value is excluded),
    `max_classification` (chunks above this rank are excluded) and `groups` (a chunk with
    `allowed_groups` is visible only to a caller holding one of them)."""

    def __init__(self, corpus: list[dict] | None = None, embedder: Embedder | None = None,
                 index_name: str = "local"):
        self.embedder = embedder or HashingEmbedder()
        self.index_name = index_name
        self.chunks: dict[str, Chunk] = {}
        for doc in corpus or []:
            for c in chunk_document(doc):
                self.chunks[c.chunk_id] = c
        self._tokens = {cid: _tokens(c.text) for cid, c in self.chunks.items()}
        self._vectors = {cid: self.embedder.embed(c.text) for cid, c in self.chunks.items()}
        self._df: Counter[str] = Counter(t for toks in self._tokens.values() for t in set(toks))
        self._avg_len = (sum(len(t) for t in self._tokens.values()) / len(self._tokens)
                         if self._tokens else 1.0)
        self.index_version = hashlib.sha256(
            "".join(sorted(c.content_hash for c in self.chunks.values())).encode()).hexdigest()[:12]

    # -- filtering --------------------------------------------------------------------------
    @staticmethod
    def _visible(chunk: Chunk, filters: dict) -> bool:
        meta = chunk.metadata
        for key in ("country", "industry"):
            if key in filters and meta.get(key) not in (None, filters[key]):
                return False
        ceiling = filters.get("max_classification")
        if ceiling is not None and CLASSIFICATION_RANK.get(
                meta.get("classification", "internal"), 1) > CLASSIFICATION_RANK[ceiling]:
            return False
        allowed = meta.get("allowed_groups")
        return not allowed or bool(set(allowed) & set(filters.get("groups", [])))

    # -- ranking ----------------------------------------------------------------------------
    def _bm25(self, q_tokens: list[str], cid: str, k1: float = 1.5, b: float = 0.75) -> float:
        toks = self._tokens[cid]
        tf = Counter(toks)
        n = len(self._tokens)
        score = 0.0
        for t in set(q_tokens):
            if t not in tf:
                continue
            idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
            score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(toks) / self._avg_len))
        return score

    def _evidence(self, chunk: Chunk, relevance: float, now: str) -> Evidence:
        return Evidence(chunk.text, chunk.source, chunk.date, now, chunk.text, chunk.confidence,
                        round(relevance, 3), chunk.doc_id, chunk.chunk_id)

    def search(self, query, filters=None, k=5):
        filters = filters or {}
        now = dt.datetime.now(dt.UTC).isoformat()
        q_tokens = _tokens(query)
        q_vec = self.embedder.embed(query)
        pool = [cid for cid, c in self.chunks.items() if self._visible(c, filters)]
        lexical = {cid: self._bm25(q_tokens, cid) for cid in pool}
        top_lex = max(lexical.values(), default=0.0) or 1.0
        scored = []
        for cid in pool:
            lex = lexical[cid] / top_lex
            sem = max(0.0, cosine(q_vec, self._vectors[cid]))
            if lexical[cid] > 0:  # hybrid: lexical match required, embeddings re-weight it
                scored.append((0.6 * lex + 0.4 * sem, cid))
        scored.sort(key=lambda x: (-x[0], x[1]))
        top = scored[:k]
        ev = [self._evidence(self.chunks[cid], s, now) for s, cid in top]
        rec = RetrievalRecord(
            "ret_" + hashlib.sha1(f"{query}|{sorted(filters.items())}".encode()).hexdigest()[:8],
            query, self.index_name, [self.chunks[c].doc_id for _, c in top],
            [round(s, 3) for s, _ in top], now, filters, self.embedder.name, "none",
            [c for _, c in top], [self.chunks[c].content_hash for _, c in top],
            self.index_version, k)
        return ev, rec

    def metadata_for(self, chunk_id: str) -> dict[str, Any]:
        return dict(self.chunks[chunk_id].metadata)

    def replay(self, record: RetrievalRecord) -> list[Evidence]:
        """Rebuild exactly what the agent saw from the stored record. Raises ReplayMismatch if a
        chunk is gone or its text changed since (the citation would no longer be trustworthy)."""
        out = []
        for cid, h, score in zip(record.chunk_ids, record.content_hashes, record.scores, strict=True):
            chunk = self.chunks.get(cid)
            if chunk is None or chunk.content_hash != h:
                raise ReplayMismatch(f"{cid}: content changed or removed since retrieval "
                                     f"{record.retrieval_id}")
            out.append(self._evidence(chunk, score, record.retrieved_at))
        return out


def evidence_dicts(ev: list[Evidence]) -> list[dict[str, Any]]:
    return [asdict(e) for e in ev]
