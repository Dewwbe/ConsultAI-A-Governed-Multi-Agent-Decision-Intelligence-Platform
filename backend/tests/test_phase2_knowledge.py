import pytest
from fastapi.testclient import TestClient

from app.control_plane.llm import ProviderResponse
from app.data.sqlite_source import SqliteDataSource
from app.knowledge.chunking import chunk_document, chunk_text, quote_in_chunk
from app.knowledge.demo_corpus import DEMO_CORPUS
from app.knowledge.retriever import LocalRetriever, ReplayMismatch
from app.main import app
from app.tools.sql_validator import SQLValidationError, validate_readonly_sql
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M"]}


# ---- chunking ----------------------------------------------------------------------------
def test_chunking_windows_overlap_and_ids_are_stable():
    text = " ".join(f"w{i}" for i in range(300))
    chunks = chunk_text(text, max_words=100, overlap=20)
    assert len(chunks) >= 3 and all(len(c.split()) <= 100 for c in chunks)
    assert chunks[0].split()[-20:] == chunks[1].split()[:20]
    assert " ".join(chunk_text("short text")) == "short text" and chunk_text("") == []
    doc = {"id": "d", "source": "s", "text": text, "country": "UAE", "classification": "public"}
    cs = chunk_document(doc)
    assert [c.chunk_id for c in cs] == [f"d#{i}" for i in range(len(cs))]
    assert cs[0].metadata == {"country": "UAE", "classification": "public"}
    with pytest.raises(ValueError):
        chunk_text("a b c", max_words=5, overlap=5)


def test_quote_verification():
    chunk = "The UAE retail market is growing, driven by tourism & online demand."
    assert quote_in_chunk("retail market is growing", chunk)
    assert quote_in_chunk("TOURISM and online demand".replace("and", "&"), chunk)
    assert not quote_in_chunk("market is shrinking fast", chunk)
    assert not quote_in_chunk("", chunk) and not quote_in_chunk("the", chunk)


# ---- retrieval ---------------------------------------------------------------------------
def test_hybrid_search_ranks_relevant_chunk_first():
    r = LocalRetriever(DEMO_CORPUS)
    ev, rec = r.search("regulatory approval licensing", k=3)
    assert ev[0].doc_id == "doc_demo_2" and ev[0].chunk_id == "doc_demo_2#0"
    assert rec.chunk_ids == [e.chunk_id for e in ev] and rec.embedding_model.startswith("hashing")
    assert r.search("zzzz qqqq")[0] == []


def test_permission_and_classification_filters():
    r = LocalRetriever(DEMO_CORPUS)
    q = "partner pricing negotiation"
    ids = lambda f: {e.doc_id for e in r.search(q, filters=f, k=10)[0]}
    assert "doc_demo_4" not in ids({"groups": ["all"]})                 # not in `partners`
    assert "doc_demo_4" in ids({"groups": ["partners"]})
    assert "doc_demo_4" not in ids({"groups": ["partners"], "max_classification": "internal"})
    q = "retail market growth demand"
    assert "doc_demo_1" not in ids({"groups": ["all"], "country": "UK"})  # metadata filter
    q = "retail market growth demand"
    assert "doc_demo_1" in ids({"groups": ["all"], "country": "UAE", "max_classification": "public"})


def test_retrieval_can_be_replayed_and_detects_changed_content():
    r = LocalRetriever(DEMO_CORPUS)
    ev, rec = r.search("market growth demand", k=2)
    replayed = r.replay(rec)
    assert [e.chunk_id for e in replayed] == [e.chunk_id for e in ev]
    assert [e.evidence for e in replayed] == [e.evidence for e in ev]
    changed = [dict(d) for d in DEMO_CORPUS]
    changed[0]["text"] += " edited"
    with pytest.raises(ReplayMismatch):
        LocalRetriever(changed).replay(rec)


# ---- research agent: citation verification --------------------------------------------------
class FabricatingProvider:
    """Cites a real doc with a made-up quote, and a doc that was never retrieved."""
    name = "azure_openai"

    def complete_json(self, *, task, system, prompt, schema, context, model):
        if task == "research_synthesis":
            out = {"claims": [
                {"claim": "ok", "doc_ref": "D1", "quote": context["stub_output"]["claims"][0]["quote"],
                 "confidence": 0.9},
                {"claim": "invented", "doc_ref": "D1", "quote": "the market will triple overnight",
                 "confidence": 0.9},
                {"claim": "ghost", "doc_ref": "D99", "quote": "does not matter at all", "confidence": 0.9},
            ]}
        else:
            out = context.get("stub_output", {})
        return ProviderResponse(out, "", 10, 10)


def test_unverified_and_unsupported_claims_are_dropped():
    svc = EngagementService()
    svc._provider = lambda: FabricatingProvider()
    wid = svc.start(**REQ)["workflow_id"]
    ev = svc.evidence(wid)
    assert [c["claim"] for c in ev["claims"]] == ["ok"] and ev["claims"][0]["verified"] is True
    assert {r["reason"] for r in ev["rejected_claims"]} == {"unverified_citation", "unsupported_claim"}


def test_engagement_cannot_use_material_above_its_classification():
    svc = EngagementService()
    wid = svc.start(**{**REQ, "data_classification": "public"})["workflow_id"]
    docs = {c["doc_id"] for c in svc.evidence(wid)["claims"]}
    assert docs == {"doc_demo_1"}  # only the public document is usable


# ---- data layer ----------------------------------------------------------------------------
def test_sqlite_source_serves_synthetic_data_read_only():
    src = SqliteDataSource()
    rows = src.query("SELECT region, SUM(revenue) AS revenue FROM finance.revenue GROUP BY region")
    assert {r["region"] for r in rows} == {"home", "north", "south", "east"} and rows[0]["revenue"] > 0
    with pytest.raises(Exception, match="readonly|read-only"):
        src.query("DELETE FROM finance.revenue")
    allowed = ["finance.revenue"]
    with pytest.raises(SQLValidationError):
        validate_readonly_sql("SELECT * FROM sales.customers", allowed)


def test_semantic_layer_is_built_from_catalog_metadata():
    layer = SqliteDataSource().describe(["finance.revenue", "unknown.table"])
    assert set(layer) == {"finance.revenue"}
    assert layer["finance.revenue"]["owner"] == "finance"
    assert "[REAL]" in layer["finance.revenue"]["columns"]["revenue"]  # live type + catalog comment


# ---- API ------------------------------------------------------------------------------------
def test_evidence_tables_and_replay_endpoints():
    c = TestClient(app)
    wid = c.post("/engagements", json=REQ).json()["workflow_id"]
    ev = c.get(f"/engagements/{wid}/evidence").json()
    assert ev["claims"] and all(x["verified"] for x in ev["claims"])
    assert {s["source"] for s in ev["sources"]} == {x["source"] for x in ev["claims"]}
    rid = ev["retrievals"][0]["retrieval_id"]
    rep = c.post(f"/engagements/{wid}/retrievals/{rid}/replay").json()
    assert rep["reproduced"] is True and rep["evidence"]
    tb = c.get(f"/engagements/{wid}/tables").json()
    assert tb["datasets"] == ["finance.revenue"] and tb["queries"][0]["row_count"] == 4
    assert "revenue" in tb["table_context"]["finance.revenue"]["columns"]
    assert c.get("/engagements/nope/evidence").status_code == 404
    assert c.get("/engagements/nope/tables").status_code == 404
    assert c.post(f"/engagements/{wid}/retrievals/nope/replay").status_code == 404
