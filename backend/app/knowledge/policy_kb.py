"""Policy knowledge base: look up internal policy clauses with their policy version, so an
answer or a Guardian reason can cite the exact version it relied on.
All entries are PLACEHOLDERS for development."""
from __future__ import annotations

from dataclasses import dataclass

from .retriever import LocalRetriever

DEMO_POLICIES = [
    {"id": "pol_investment_1", "source": "policy://investment-approval", "date": "2026-10-01",
     "text": "investment commitments above one million dollars require partner approval before commitment",
     "confidence": 0.95, "classification": "internal", "policy_version": "2026.10.1"},
    {"id": "pol_data_1", "source": "policy://data-handling", "date": "2026-10-01",
     "text": "confidential client data may only be processed by approved providers in approved regions",
     "confidence": 0.95, "classification": "internal", "policy_version": "2026.10.1"},
    {"id": "pol_data_0", "source": "policy://data-handling", "date": "2025-04-01",
     "text": "confidential client data may be processed by any approved provider",
     "confidence": 0.5, "classification": "internal", "policy_version": "2025.4.0"},
]


@dataclass(frozen=True)
class PolicyClause:
    text: str
    source: str
    policy_version: str
    chunk_id: str
    relevance: float


class PolicyKB:
    def __init__(self, retriever: LocalRetriever | None = None):
        self.retriever = retriever or LocalRetriever(DEMO_POLICIES, index_name="policy-kb")

    def lookup(self, topic: str, *, policy_version: str | None = None, k: int = 3) -> list[PolicyClause]:
        """Clauses relevant to `topic`, newest policy version first. Pass `policy_version` to see
        what a past run was governed by."""
        ev, _ = self.retriever.search(topic, k=10)
        clauses = [PolicyClause(e.evidence, e.source, self.retriever.metadata_for(e.chunk_id)["policy_version"],
                                e.chunk_id, e.relevance) for e in ev]
        if policy_version:
            clauses = [c for c in clauses if c.policy_version == policy_version]
        clauses.sort(key=lambda c: (c.policy_version, c.relevance), reverse=True)
        return clauses[:k]
