from __future__ import annotations

from typing import Any

from app.knowledge.chunking import quote_in_chunk
from app.knowledge.retriever import Evidence, evidence_dicts
from app.observability.payload import cap_payload
from app.prompts import get_prompt
from app.schemas.json_schema import NUM, STR, arr, obj

from .base import BaseAgent

SCHEMA = obj(claims=arr(obj(claim=STR, doc_ref=STR, quote=STR, confidence=NUM)))


class ResearchAgent(BaseAgent):
    """RAG research: plan queries -> retrieve -> LLM extracts claims -> every claim is bound to a
    retrieved document by code. Phase 2 adds hybrid retrieval, reranking and citation verification."""
    name = "research_agent"

    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        spec = view["engagement_spec"]
        queries = [f"{a} {spec['decision_question']}" for a in spec["required_analysis"]]
        docs: list[Evidence] = []
        seen: set[str] = set()
        # An engagement may only use material at or below its own classification, and only what
        # the caller's groups permit (real group membership arrives with Entra ID in Phase 4).
        filters = {"max_classification": view.get("data_classification", "confidential"),
                   "groups": ["all"]}
        for q in queries:
            with self.ctx.trace.span("retrieval", "retrieval", **{"consultai.query": q}) as span:
                ev, rec = self.ctx.retriever.search(q, filters=filters, k=2 * self.ctx.degradation.actions.retrieval_k_multiplier)
                self.ctx.memory.log_retrieval(self.ctx.workflow_id, rec)
                span.attributes["consultai.document_ids"] = rec.document_ids
                span.attributes["consultai.retrieval"] = cap_payload({
                    "retrieval_id": rec.retrieval_id, "index": rec.index, "embedding_model": rec.embedding_model,
                    "reranker": rec.reranker, "filters": rec.filters, "k": rec.k, "index_version": rec.index_version,
                    "documents": [{"doc_id": e.doc_id, "chunk_id": e.chunk_id, "source": e.source,
                                   "score": e.relevance, "text": e.evidence} for e in ev]})
            for e in ev:  # de-duplicate by source+text
                if e.chunk_id not in seen:
                    seen.add(e.chunk_id)
                    docs.append(e)
        if not docs:
            return {"research_results": [], "citations": []}

        refs = {f"D{i}": e for i, e in enumerate(docs, 1)}
        stub = {"claims": [{"claim": e.claim, "doc_ref": ref, "quote": e.evidence, "confidence": e.confidence}
                           for ref, e in refs.items()]}
        out = self.ctx.llm.structured(
            agent=self.name, task="research_synthesis", prompt=get_prompt("research"), schema=SCHEMA,
            variables={"decision_question": spec["decision_question"],
                       "required_analysis": spec["required_analysis"],
                       "documents": "\n\n".join(f"[{r}] source={e.source} date={e.publication_date}\n{e.evidence}"
                                                for r, e in refs.items())},
            context={"stub_output": stub},
            data_classification=view.get("data_classification", "confidential")).content["claims"]

        results: list[dict] = []
        for c in out:
            src = refs.get(c["doc_ref"])
            if src is None:  # claim cites a document the agent never retrieved: reject it
                self.ctx.log["failures"].append({"type": "unsupported_claim", "doc_ref": c["doc_ref"]})
                continue
            if not quote_in_chunk(c["quote"], src.evidence):  # citation verification
                self.ctx.log["failures"].append({"type": "unverified_citation", "doc_ref": c["doc_ref"],
                                                 "chunk_id": src.chunk_id})
                continue
            d = evidence_dicts([src])[0]
            results.append({**d, "claim": c["claim"], "quote": c["quote"], "verified": True,
                            "confidence": max(0.0, min(1.0, c["confidence"]))})
        return {"research_results": results, "citations": sorted({r["source"] for r in results})}
