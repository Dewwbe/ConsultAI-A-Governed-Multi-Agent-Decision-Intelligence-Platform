"""Document chunking. Chunks carry stable ids so a citation can always be traced to a passage."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

# metadata that travels with every chunk and is filterable in the index
METADATA_FIELDS = ("country", "industry", "classification", "allowed_groups", "policy_version")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    source: str
    date: str
    text: str
    confidence: float = 0.7
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()[:16]


def chunk_text(text: str, max_words: int = 120, overlap: int = 20) -> list[str]:
    """Sliding word window. Short texts stay whole; windows overlap so a sentence cut at a
    boundary still appears intact in one chunk."""
    if overlap >= max_words:
        raise ValueError("overlap must be smaller than max_words")
    words = text.split()
    if len(words) <= max_words:
        return [" ".join(words)] if words else []
    step = max_words - overlap
    return [" ".join(words[i:i + max_words]) for i in range(0, len(words) - overlap, step)]


def chunk_document(doc: dict[str, Any], max_words: int = 120, overlap: int = 20) -> list[Chunk]:
    meta = {k: doc[k] for k in METADATA_FIELDS if k in doc}
    return [Chunk(f"{doc['id']}#{i}", doc["id"], doc["source"], doc.get("date", "unknown"), t,
                  doc.get("confidence", 0.7), meta)
            for i, t in enumerate(chunk_text(doc["text"], max_words, overlap))]


_NORM = re.compile(r"[\W_]+")


def normalise(text: str) -> str:
    return _NORM.sub(" ", text.lower()).strip()


def quote_in_chunk(quote: str, chunk_text_: str) -> bool:
    """Citation check: the quoted span must appear verbatim (ignoring case, spacing and
    punctuation) in the cited chunk."""
    q = normalise(quote)
    return len(q) >= 8 and q in normalise(chunk_text_)
