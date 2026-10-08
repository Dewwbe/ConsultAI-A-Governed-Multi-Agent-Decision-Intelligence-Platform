import datetime as dt

import pytest

from app.knowledge.cached import CachedRetriever
from app.knowledge.demo_corpus import DEMO_CORPUS
from app.knowledge.embeddings import HashingEmbedder
from app.knowledge.policy_kb import PolicyKB
from app.knowledge.retriever import LocalRetriever
from app.knowledge.semantic_cache import SemanticCache
from app.memory.classifier import classify_memory
from app.memory.store import MemoryItem, MemoryStore
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M", "Launch within 18 months"]}


# ---- memory classification ----------------------------------------------------------------
@pytest.mark.parametrize("text,store,kind", [
    ("I prefer concise executive summaries", True, "preference"),
    ("Please always show costs in USD", True, "preference"),
    ("Budget under $10M", True, "fact"),
    ("Launch within 18 months", True, "fact"),
    ("Our company operates 40 stores in Europe", True, "fact"),
    ("thanks", False, "none"),
    ("ok", False, "none"),
    ("What is the market size?", False, "none"),
    ("Should we expand into the UAE market?", False, "none"),
    ("The weather is nice today in London", False, "none"),
])
def test_classification_rule(text, store, kind):
    d = classify_memory(text)
    assert (d.store, d.type) == (store, kind), d


@pytest.mark.parametrize("text", [
    "My email is jane.doe@example.com, remember it",
    "Our budget is $5M and my password is hunter2",
    "Call me on +44 7700 900123 about the budget",
    "Use api key " + "sk" + "_live_" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6" + " always",  # built at runtime: no scannable literal
    "Charge card 4111 1111 1111 1111 for the budget",
])
def test_sensitive_text_is_never_stored(text):
    m = MemoryStore()
    d = m.observe(conversation_id="c", user_id="u", text=text)
    assert d.store is False and "personal data" in d.reason
    assert not m.long_term and m.short_term["c"][0]["content"] == "[redacted]"


def test_observe_scopes_dedupes_and_expires():
    m = MemoryStore()
    m.observe(conversation_id="c", user_id="u1", text="I prefer concise executive summaries")
    again = m.observe(conversation_id="c", user_id="u1", text="I prefer concise executive summaries")
    assert again.reason == "duplicate" and len(m.recall("user:u1")) == 1
    assert m.recall("user:u2") == []                                  # other users see nothing
    m.observe(conversation_id="c", user_id="u1", text="Budget under $10M", engagement_id="wf_1")
    fact = m.recall("engagement:wf_1")[0]
    assert fact.scope == "engagement" and fact.expires_at is not None
    fact.expires_at = (dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)).isoformat()
    assert m.recall("engagement:wf_1") == []                          # expired facts are not recalled
    assert len(m.short_term["c"]) == 3                               # every turn stays short-term


def test_remember_still_supports_decisions():
    m = MemoryStore()
    m.remember("human_feedback", MemoryItem("decision", "global", {"x": 1}))
    assert len(m.recall("human_feedback")) == 1


def test_engagement_start_stores_only_durable_inputs():
    svc = EngagementService()
    wid = svc.start(**REQ)["workflow_id"]
    stored = [i.value for i in svc.memory.recall(f"engagement:{wid}")]
    assert "Budget under $10M" in stored and "Launch within 18 months" in stored
    assert "Increase revenue" not in stored  # an objective phrase is not a durable fact


# ---- semantic cache -----------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)

    def __call__(self):
        return self.now


def make_cache(**kw):
    clock = Clock()
    return SemanticCache(HashingEmbedder(), clock=clock, **kw), clock


def test_cache_hit_and_miss_on_similarity():
    c, _ = make_cache()
    c.put("regulatory approval licensing timeline", "A", source_version="v1")
    assert c.get("regulatory approval licensing timeline", source_version="v1") == "A"
    assert c.get("completely different topic about oranges", source_version="v1") is None
    assert (c.hits, c.misses) == (1, 1)


def test_cache_respects_source_version_expiry_scope_and_embedding_version():
    c, clock = make_cache(ttl_sec=60)
    c.put("market size", "A", source_version="v1", scope="s1")
    assert c.get("market size", source_version="v2", scope="s1") is None   # source changed
    assert c.get("market size", source_version="v1", scope="s2") is None   # other permissions
    c.embedder.name = "hashing-other"
    assert c.get("market size", source_version="v1", scope="s1") is None   # vectors not comparable
    c.embedder.name = "hashing-256-v1"
    assert c.get("market size", source_version="v1", scope="s1") == "A"
    clock.now += dt.timedelta(seconds=61)
    assert c.get("market size", source_version="v1", scope="s1") is None   # expired
    assert c.entries == []


def test_cache_invalidate_source_and_capacity():
    c, _ = make_cache(max_entries=2)
    for i in range(3):
        c.put(f"query number {i}", i, source_version="v1")
    assert len(c.entries) == 2
    c.put("another", 9, source_version="v2")
    assert len(c.entries) == 2  # capacity evicts the oldest
    assert c.invalidate_source("v2") == 1 and [e.value for e in c.entries] == [9]


def test_cached_retriever_never_crosses_permission_scopes():
    inner = LocalRetriever(DEMO_CORPUS)
    r = CachedRetriever(inner, SemanticCache(inner.embedder))
    q = "partner pricing negotiation margin"
    partners, _ = r.search(q, filters={"groups": ["partners"]}, k=5)
    everyone, _ = r.search(q, filters={"groups": ["all"]}, k=5)
    assert "doc_demo_4" in {e.doc_id for e in partners}
    assert "doc_demo_4" not in {e.doc_id for e in everyone}               # no leak via the cache
    r.search(q, filters={"groups": ["partners"]}, k=5)
    assert r.cache.hits == 1
    assert r.index_version == inner.index_version                         # delegation works


def test_second_engagement_is_served_from_cache():
    svc = EngagementService()
    svc.start(**REQ)
    before = svc.cache.hits
    wid = svc.start(**REQ)["workflow_id"]
    assert svc.cache.hits > before
    ev = svc.evidence(wid)
    rid = ev["retrievals"][0]["retrieval_id"]
    assert svc.replay_retrieval(wid, rid)["reproduced"] is True


# ---- policy KB ----------------------------------------------------------------------------
def test_policy_lookup_returns_versioned_clauses_newest_first():
    kb = PolicyKB()
    clauses = kb.lookup("confidential client data providers")
    assert [c.policy_version for c in clauses] == ["2026.10.1", "2025.4.0"]
    assert clauses[0].source == "policy://data-handling"
    old = kb.lookup("confidential client data providers", policy_version="2025.4.0")
    assert [c.policy_version for c in old] == ["2025.4.0"]
    assert kb.lookup("investment commitments partner approval")[0].source == "policy://investment-approval"
