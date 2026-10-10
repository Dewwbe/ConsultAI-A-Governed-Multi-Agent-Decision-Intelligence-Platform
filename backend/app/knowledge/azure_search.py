"""Azure AI Search retriever, Azure OpenAI embedder and index management.

`AzureSearchRetriever` implements the same `Retriever` protocol as `LocalRetriever`: hybrid keyword + vector
search, the same filters (`country`, `industry`, `max_classification`, `groups`), and a `RetrievalRecord` that
lets `replay` prove the agent saw exactly this text. Visibility rules are enforced in the index query itself
(security trimming), never by filtering results afterwards, so a caller cannot receive a passage above its
clearance even transiently.

The SDK clients are injected so everything here is unit-tested against fakes; `scripts/verify_azure.py`
exercises the real service.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
from dataclasses import dataclass
from typing import Any

from .chunking import Chunk
from .retriever import CLASSIFICATION_RANK, Evidence, ReplayMismatch, RetrievalRecord

VECTOR_FIELD = "embedding"
SELECT = ["chunk_id", "chunk_ref", "doc_id", "source", "date", "text", "confidence", "content_hash", "country", "industry",
          "classification", "allowed_groups", "policy_version"]


def chunk_key(chunk_id: str) -> str:
    """The index key for a chunk. Azure Search keys allow only letters, digits, `_`, `-` and `=`, and our chunk ids
    (`doc#3`, ADLS paths) contain other characters, so the key is the URL-safe base64 of the id. The readable id is
    kept in the `chunk_ref` field and is what the rest of the platform sees."""
    return base64.urlsafe_b64encode(chunk_id.encode()).decode()


class AzureOpenAIEmbedder:
    """Embeddings from an Azure OpenAI deployment. `name` is stored with every retrieval record and cache entry,
    so changing the model invalidates cached answers instead of silently mixing vector spaces."""

    def __init__(self, client: Any, deployment: str, dimensions: int | None = None):
        self._client, self.deployment, self.dimensions = client, deployment, dimensions
        self.name = f"azure-{deployment}" + (f"-{dimensions}" if dimensions else "")

    def embed(self, text: str) -> list[float]:
        kwargs: dict[str, Any] = {"model": self.deployment, "input": text}
        if self.dimensions:
            kwargs["dimensions"] = self.dimensions
        return list(self._client.embeddings.create(**kwargs).data[0].embedding)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        kwargs: dict[str, Any] = {"model": self.deployment, "input": texts}
        if self.dimensions:
            kwargs["dimensions"] = self.dimensions
        data = sorted(self._client.embeddings.create(**kwargs).data, key=lambda d: d.index)
        return [list(d.embedding) for d in data]


def _q(value: Any) -> str:
    """An OData string literal: single quotes are doubled, so a value can never end the literal early."""
    return "'" + str(value).replace("'", "''") + "'"


def build_filter(filters: dict) -> str | None:
    """OData filter equivalent to `LocalRetriever._visible`. A chunk that declares no country/industry matches
    everyone; a chunk with `allowed_groups` is visible only to a caller holding one of them."""
    parts: list[str] = []
    for key in ("country", "industry"):
        if key in filters:
            parts.append(f"({key} eq {_q(filters[key])} or {key} eq null)")
    ceiling = filters.get("max_classification")
    if ceiling is not None:
        allowed = [c for c, r in CLASSIFICATION_RANK.items() if r <= CLASSIFICATION_RANK[ceiling]]
        parts.append(f"(classification eq null or search.in(classification, {_q(','.join(allowed))}, ','))")
    groups = filters.get("groups", [])
    group_clause = "not allowed_groups/any()"
    if groups:
        group_clause = f"allowed_groups/any(g: search.in(g, {_q(','.join(groups))}, ',')) or {group_clause}"
    parts.append(f"({group_clause})")
    return " and ".join(parts)


def index_definition(name: str, dimensions: int) -> Any:
    """The index schema: filterable metadata for security trimming, a keyword-searchable text field and a vector field."""
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchableField,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )
    string, collection = SearchFieldDataType.String, SearchFieldDataType.Collection(SearchFieldDataType.String)
    fields = [
        SimpleField(name="chunk_id", type=string, key=True, filterable=True),
        SimpleField(name="chunk_ref", type=string, filterable=True),
        SimpleField(name="doc_id", type=string, filterable=True),
        SearchableField(name="source", type=string),
        SimpleField(name="date", type=string),
        SearchableField(name="text", type=string),
        SimpleField(name="confidence", type=SearchFieldDataType.Double),
        SimpleField(name="content_hash", type=string),
        SimpleField(name="country", type=string, filterable=True),
        SimpleField(name="industry", type=string, filterable=True),
        SimpleField(name="classification", type=string, filterable=True),
        SimpleField(name="allowed_groups", type=collection, filterable=True),
        SimpleField(name="policy_version", type=string, filterable=True),
        SearchField(name=VECTOR_FIELD, type=SearchFieldDataType.Collection(SearchFieldDataType.Single), searchable=True,
                    vector_search_dimensions=dimensions, vector_search_profile_name="consultai-vectors"),
    ]
    vector = VectorSearch(algorithms=[HnswAlgorithmConfiguration(name="consultai-hnsw")],
                          profiles=[VectorSearchProfile(name="consultai-vectors", algorithm_configuration_name="consultai-hnsw")])
    return SearchIndex(name=name, fields=fields, vector_search=vector)


def ensure_index(index_client: Any, name: str, dimensions: int) -> None:
    """Create the index, or update it if the schema changed. Safe to run on every deploy."""
    index_client.create_or_update_index(index_definition(name, dimensions))


def _chunk_from(doc: dict[str, Any]) -> Chunk:
    meta = {k: doc[k] for k in ("country", "industry", "classification", "allowed_groups", "policy_version")
            if doc.get(k) not in (None, [])}
    return Chunk(doc["chunk_ref"], doc["doc_id"], doc.get("source", ""), doc.get("date") or "unknown", doc["text"],
                 doc.get("confidence") or 0.7, meta)


class AzureSearchRetriever:
    def __init__(self, client: Any, embedder: Any, index_name: str = "consultai-chunks"):
        self.client, self.embedder, self.index_name = client, embedder, index_name

    def search(self, query: str, filters: dict | None = None, k: int = 5) -> tuple[list[Evidence], RetrievalRecord]:
        from azure.search.documents.models import VectorizedQuery
        filters = filters or {}
        now = dt.datetime.now(dt.UTC).isoformat()
        vector = VectorizedQuery(vector=self.embedder.embed(query), k_nearest_neighbors=max(k * 3, 10), fields=VECTOR_FIELD)
        hits = list(self.client.search(search_text=query, vector_queries=[vector], filter=build_filter(filters),
                                       select=SELECT, top=k))
        top = max((h["@search.score"] for h in hits), default=0.0) or 1.0
        evidence, chunks = [], []
        for h in hits:
            chunk = _chunk_from(h)
            chunks.append(chunk)
            # Hybrid (RRF) scores are tiny and only comparable within one query, so relevance is relative to the best hit.
            evidence.append(Evidence(chunk.text, chunk.source, chunk.date, now, chunk.text, chunk.confidence,
                                     round(h["@search.score"] / top, 3), chunk.doc_id, chunk.chunk_id))
        hashes = [c.content_hash for c in chunks]
        record = RetrievalRecord(
            "ret_" + hashlib.sha1(f"{query}|{sorted(filters.items())}".encode()).hexdigest()[:8], query, self.index_name,
            [c.doc_id for c in chunks], [round(h["@search.score"], 5) for h in hits], now, filters, self.embedder.name,
            "none", [c.chunk_id for c in chunks], hashes, hashlib.sha256("".join(sorted(hashes)).encode()).hexdigest()[:12], k)
        return evidence, record

    def metadata_for(self, chunk_id: str) -> dict[str, Any]:
        return dict(_chunk_from(self.client.get_document(key=chunk_key(chunk_id))).metadata)

    def replay(self, record: RetrievalRecord) -> list[Evidence]:
        """Fetch each stored chunk by id and check its text still hashes the same. A missing or changed chunk raises
        `ReplayMismatch`: the citation would no longer be trustworthy."""
        out = []
        for cid, expected, score in zip(record.chunk_ids, record.content_hashes, record.scores, strict=True):
            try:
                chunk = _chunk_from(self.client.get_document(key=chunk_key(cid)))
            except Exception as exc:  # the SDK raises ResourceNotFoundError; a fake may raise KeyError
                if type(exc).__name__ in {"ResourceNotFoundError", "KeyError"}:
                    raise ReplayMismatch(f"{cid}: removed since retrieval {record.retrieval_id}") from exc
                raise
            if chunk.content_hash != expected:
                raise ReplayMismatch(f"{cid}: content changed since retrieval {record.retrieval_id}")
            out.append(Evidence(chunk.text, chunk.source, chunk.date, record.retrieved_at, chunk.text, chunk.confidence,
                                round(score, 3), chunk.doc_id, chunk.chunk_id))
        return out


@dataclass
class IngestReport:
    documents: int
    chunks_uploaded: int
    chunks_removed: int
    failed: list[str]


def ingest_documents(docs: list[dict[str, Any]], client: Any, embedder: Any, batch_size: int = 50) -> IngestReport:
    """Chunk, embed and upload documents. Chunks of a re-ingested document that no longer exist (it got shorter) are
    deleted, so a search never returns text the source no longer contains."""
    from .chunking import chunk_document
    uploaded, removed, failed = 0, 0, []
    for doc in docs:
        chunks = chunk_document(doc)
        vectors = embedder.embed_many([c.text for c in chunks]) if hasattr(embedder, "embed_many") else [
            embedder.embed(c.text) for c in chunks]
        rows = [{"chunk_id": chunk_key(c.chunk_id), "chunk_ref": c.chunk_id, "doc_id": c.doc_id, "source": c.source, "date": c.date, "text": c.text,
                 "confidence": c.confidence, "content_hash": c.content_hash, "country": c.metadata.get("country"),
                 "industry": c.metadata.get("industry"), "classification": c.metadata.get("classification", "internal"),
                 "allowed_groups": c.metadata.get("allowed_groups", []), "policy_version": c.metadata.get("policy_version"),
                 VECTOR_FIELD: v} for c, v in zip(chunks, vectors, strict=True)]
        for i in range(0, len(rows), batch_size):
            for result in client.merge_or_upload_documents(documents=rows[i:i + batch_size]):
                if getattr(result, "succeeded", True):
                    uploaded += 1
                else:
                    failed.append(f"{result.key}: {getattr(result, 'error_message', 'upload failed')}")
        keep = {c.chunk_id for c in chunks}
        stale = [{"chunk_id": h["chunk_id"]} for h in client.search(search_text="*", filter=f"doc_id eq {_q(doc['id'])}",
                                                                     select=["chunk_id", "chunk_ref"], top=1000)
                 if h["chunk_ref"] not in keep]
        if stale:
            client.delete_documents(documents=stale)
            removed += len(stale)
    return IngestReport(len(docs), uploaded, removed, failed)
