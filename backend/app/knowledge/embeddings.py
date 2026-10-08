"""Embedders. `HashingEmbedder` is deterministic and offline (dev/tests); the Azure OpenAI
embedder replaces it when an embedding deployment exists. `name` is stored with every
retrieval record and semantic-cache entry as `embedding_version`."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

_WORD = re.compile(r"\w+")


class Embedder(Protocol):
    name: str

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    def __init__(self, dim: int = 256):
        self.dim = dim
        self.name = f"hashing-{dim}-v1"

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for w in _WORD.findall(text.lower()):
            for feat in [w] + [w[i:i + 3] for i in range(len(w) - 2)]:  # word + char trigrams
                h = int.from_bytes(hashlib.md5(feat.encode()).digest()[:4], "big")
                vec[h % self.dim] += 1.0 if (h >> 31) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
