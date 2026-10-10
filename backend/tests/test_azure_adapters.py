"""The Azure adapters, tested against in-memory fakes of their SDK clients. They check our logic (filters, hashing,
replay, stale-chunk cleanup, read-only enforcement, persistence rules); `scripts/verify_azure.py` checks the real services."""
from __future__ import annotations

import json
import re
from types import SimpleNamespace as NS

import pytest

from app.adapters import (
    build_backends,
    build_data_source,
    build_embedder,
    build_memory,
    build_retriever,
)
from app.config import Settings
from app.data.databricks_source import DatabricksDataSource
from app.knowledge.adls import read_corpus
from app.knowledge.azure_search import (
    AzureOpenAIEmbedder,
    AzureSearchRetriever,
    build_filter,
    chunk_key,
    index_definition,
    ingest_documents,
)
from app.knowledge.chunking import chunk_document
from app.knowledge.embeddings import HashingEmbedder
from app.knowledge.retriever import ReplayMismatch
from app.memory.cosmos_store import CosmosMemoryStore
from app.memory.store import MemoryItem


# ---- Azure OpenAI embeddings -----------------------------------------------------------------------------------------
class FakeOpenAI:
    def __init__(self):
        self.calls = []
        self.embeddings = NS(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        inputs = kw["input"] if isinstance(kw["input"], list) else [kw["input"]]
        # returned out of order on purpose: the embedder must sort by index
        return NS(data=[NS(index=i, embedding=[float(len(t)), float(i)]) for i, t in reversed(list(enumerate(inputs)))])


def test_embedder_names_the_model_and_keeps_input_order():
    client = FakeOpenAI()
    emb = AzureOpenAIEmbedder(client, "emb-3", dimensions=256)
    assert emb.name == "azure-emb-3-256"
    assert emb.embed("abc") == [3.0, 0.0]
    assert emb.embed_many(["a", "bb", "ccc"]) == [[1.0, 0.0], [2.0, 1.0], [3.0, 2.0]]
    assert client.calls[0]["dimensions"] == 256 and client.calls[0]["model"] == "emb-3"
    assert emb.embed_many([]) == []


# ---- security trimming ---------------------------------------------------------------------------------------------
def test_filter_matches_the_local_retrievers_visibility_rules():
    f = build_filter({"country": "UAE", "industry": "Retail", "max_classification": "internal", "groups": ["g1", "g2"]})
    assert "(country eq 'UAE' or country eq null)" in f and "(industry eq 'Retail' or industry eq null)" in f
    assert "search.in(classification, 'public,internal', ',')" in f  # confidential is excluded
    assert "allowed_groups/any(g: search.in(g, 'g1,g2', ','))" in f and "not allowed_groups/any()" in f


def test_a_caller_without_groups_only_sees_unrestricted_chunks():
    assert build_filter({}) == "(not allowed_groups/any())"


def test_filter_values_cannot_break_out_of_their_literal():
    f = build_filter({"country": "x' or classification eq 'confidential"})
    assert "country eq 'x'' or classification eq ''confidential'" in f


# ---- index schema ---------------------------------------------------------------------------------------------------
def test_index_has_a_key_filterable_metadata_and_a_vector_field():
    index = index_definition("idx", 1536)
    fields = {f.name: f for f in index.fields}
    assert fields["chunk_id"].key and fields["text"].searchable
    assert all(fields[n].filterable for n in ("country", "industry", "classification", "allowed_groups", "doc_id"))
    assert fields["embedding"].vector_search_dimensions == 1536
    assert index.vector_search.profiles[0].name == fields["embedding"].vector_search_profile_name


# ---- retriever + ingest ----------------------------------------------------------------------------------------------
KEY = chunk_key("d1#0")
DOC = {"id": "d1", "source": "market-report.pdf", "date": "2026-01-01", "country": "UAE", "classification": "internal",
       "text": "The UAE retail market grew 6 percent last year driven by tourism and e-commerce."}


class FakeSearch:
    """Stores documents by chunk id; `search` returns everything matching a naive text overlap and records the call."""

    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.last = {}

    def merge_or_upload_documents(self, documents):
        for d in documents:
            # the real service rejects any other character in a key (this is what broke the first live ingest)
            assert re.fullmatch(r"[A-Za-z0-9_=-]+", d["chunk_id"]), f"invalid Azure Search key {d['chunk_id']!r}"
            self.docs[d["chunk_id"]] = dict(d)
        return [NS(key=d["chunk_id"], succeeded=True) for d in documents]

    def delete_documents(self, documents):
        for d in documents:
            self.docs.pop(d["chunk_id"], None)

    def get_document(self, key):
        if key not in self.docs:
            raise KeyError(key)
        return dict(self.docs[key])

    def search(self, search_text, filter=None, select=None, top=50, vector_queries=None):
        self.last = {"text": search_text, "filter": filter, "vectors": vector_queries, "top": top}
        if filter and filter.startswith("doc_id eq "):
            want = filter.split("'")[1]
            return [{"chunk_id": d["chunk_id"], "chunk_ref": d["chunk_ref"]} for d in self.docs.values() if d["doc_id"] == want]
        words = set(search_text.lower().split())
        hits = [dict(d, **{"@search.score": 0.03 - 0.01 * i}) for i, d in enumerate(self.docs.values())
                if words & set(d["text"].lower().split())]
        return hits[:top]


@pytest.fixture
def indexed():
    client, emb = FakeSearch(), HashingEmbedder(8)
    report = ingest_documents([DOC], client, emb)
    return client, emb, report


def test_ingest_uploads_every_chunk_with_vectors_and_a_content_hash(indexed):
    client, _, report = indexed
    assert (report.documents, report.chunks_uploaded, report.failed) == (1, 1, [])
    row = client.docs[KEY]
    assert len(row["embedding"]) == 8 and row["content_hash"] == chunk_document(DOC)[0].content_hash
    assert row["classification"] == "internal" and row["allowed_groups"] == []


def test_reingesting_a_shorter_document_removes_its_stale_chunks():
    client, emb = FakeSearch(), HashingEmbedder(8)
    long = {**DOC, "text": " ".join(f"word{i}" for i in range(300))}
    ingest_documents([long], client, emb)
    before = len(client.docs)
    assert before > 1
    report = ingest_documents([{**long, "text": "short now"}], client, emb)
    assert [d["chunk_ref"] for d in client.docs.values()] == ["d1#0"] and report.chunks_removed == before - 1


def test_search_returns_evidence_with_a_replayable_record(indexed):
    client, emb, _ = indexed
    ev, rec = AzureSearchRetriever(client, emb, "idx").search("UAE retail market", {"country": "UAE"}, k=3)
    assert [e.chunk_id for e in ev] == ["d1#0"] and ev[0].relevance == 1.0 and ev[0].source == "market-report.pdf"
    assert rec.index == "idx" and rec.embedding_model == emb.name and rec.chunk_ids == ["d1#0"] and rec.k == 3
    assert client.last["filter"].startswith("(country eq 'UAE'") and client.last["vectors"][0].fields == "embedding"


def test_replay_reproduces_the_evidence_and_detects_changes(indexed):
    client, emb, _ = indexed
    retriever = AzureSearchRetriever(client, emb)
    _, rec = retriever.search("UAE retail market")
    assert retriever.replay(rec)[0].evidence == DOC["text"]
    client.docs[KEY]["text"] = "edited after the agent read it"
    with pytest.raises(ReplayMismatch, match="content changed"):
        retriever.replay(rec)
    del client.docs[KEY]
    with pytest.raises(ReplayMismatch, match="removed"):
        retriever.replay(rec)


def test_policy_metadata_is_available_for_a_chunk(indexed):
    client, emb, _ = indexed
    assert AzureSearchRetriever(client, emb).metadata_for("d1#0")["country"] == "UAE"


def test_failed_uploads_are_reported_not_hidden():
    client = FakeSearch()
    client.merge_or_upload_documents = lambda documents: [NS(key="d1#0", succeeded=False, error_message="quota")]
    report = ingest_documents([DOC], client, HashingEmbedder(8))
    assert report.failed == ["d1#0: quota"] and report.chunks_uploaded == 0


# ---- ADLS ---------------------------------------------------------------------------------------------------------
class FakeContainer_:
    """A blob container: `list_blobs` yields names (and metadata), `download_blob` returns the body."""

    def __init__(self, files: dict[str, tuple[str, dict | None]]):
        self.files, self.listed_prefix = files, None

    def list_blobs(self, name_starts_with=None, include=None):
        self.listed_prefix = name_starts_with
        return [NS(name=n, metadata=m) for n, (_, m) in self.files.items()]

    def download_blob(self, name):
        return NS(readall=lambda: self.files[name][0].encode())


def test_reads_json_and_text_documents_and_skips_the_rest():
    container = FakeContainer_({
        "a.json": (json.dumps({"id": "a", "text": "alpha text", "country": "UAE"}), None),
        "b.md": ("beta text", {"classification": "confidential", "allowed_groups": "g1, g2", "country": "KSA"}),
        "broken.json": ("{not json", None),
        "no-text.json": (json.dumps({"id": "x"}), None),
        "image.png": ("binary", None),
        "folder": ("", {"hdi_isfolder": "true"}),  # an ADLS folder marker
    })
    docs = list(read_corpus(container, "knowledge/"))
    assert container.listed_prefix == "knowledge/"
    assert [d["id"] for d in docs] == ["a", "b.md"]
    assert docs[0]["source"] == "a.json"
    assert docs[1]["allowed_groups"] == ["g1", "g2"] and docs[1]["classification"] == "confidential"


@pytest.mark.parametrize("given,expected", [
    ("https://acct.dfs.core.windows.net", "https://acct.blob.core.windows.net"),
    ("https://acct.blob.core.windows.net/", "https://acct.blob.core.windows.net"),
])
def test_either_account_address_works(given, expected):
    from app.knowledge.adls import blob_endpoint
    assert blob_endpoint(given) == expected


# ---- Databricks -------------------------------------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, conn):
        self.conn, self.description, self.rows = conn, None, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, statement, params=None):
        self.conn.executed.append((statement, params))
        cols, rows = self.conn.respond(statement)
        self.description, self.rows = [(c,) for c in cols], rows

    def fetchmany(self, n):
        return self.rows[:n]

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, respond):
        self.executed, self.respond = [], respond

    def cursor(self):
        return FakeCursor(self)


def test_databricks_runs_one_select_and_caps_rows():
    conn = FakeConn(lambda s: (["n"], [(i,) for i in range(50)]))
    src = DatabricksDataSource(connection=conn, max_rows=10)
    assert len(src.query("SELECT n FROM finance.revenue;")) == 10
    assert src.query("WITH x AS (SELECT 1 n) SELECT * FROM x")[0] == {"n": 0}


@pytest.mark.parametrize("sql", ["DROP TABLE finance.revenue", "SELECT 1; DELETE FROM finance.revenue", "UPDATE t SET a=1",
                                 "  insert into t values (1)"])
def test_databricks_refuses_anything_but_a_single_select(sql):
    conn = FakeConn(lambda s: ([], []))
    with pytest.raises(PermissionError):
        DatabricksDataSource(connection=conn).query(sql)
    assert conn.executed == []


def test_databricks_describe_builds_the_semantic_layer_from_catalog_metadata():
    def respond(s):
        if "information_schema.columns" in s:
            return ["column_name", "data_type", "comment"], [("date", "string", "Month"), ("revenue", "double", None)]
        if "information_schema.tables" in s:
            return ["comment", "table_owner"], [("Monthly revenue", "finance-team")]
        return ["tag_value"], [("confidential",)]
    conn = FakeConn(respond)
    layer = DatabricksDataSource(connection=conn).describe(["finance.revenue", "bad name; DROP", "x"])
    assert list(layer) == ["finance.revenue"]
    assert layer["finance.revenue"] == {"description": "Monthly revenue", "owner": "finance-team", "sensitivity": "confidential",
                                        "columns": {"date": "Month [string]", "revenue": "[double]"}}
    assert all(p == ["finance", "revenue"] for _, p in conn.executed)  # table names are bound parameters, never interpolated


def test_databricks_lists_catalogs():
    conn = FakeConn(lambda s: (["catalog"], [("main",), ("workspace",)]))
    assert DatabricksDataSource(connection=conn).catalogs() == ["main", "workspace"]


def test_databricks_describe_skips_unknown_tables():
    assert DatabricksDataSource(connection=FakeConn(lambda s: ([], []))).describe(["finance.nothing"]) == {}


# ---- Cosmos memory ---------------------------------------------------------------------------------------------------
class FakeContainer:
    def __init__(self):
        self.items: list[dict] = []

    def create_item(self, doc):
        self.items.append(dict(doc))

    def query_items(self, query, parameters, partition_key):
        p = {x["name"]: x["value"] for x in parameters}
        return [i for i in self.items if i["pk"] == p["@pk"] == partition_key and i["kind"] == p["@kind"]]


def test_memory_survives_a_new_process():
    container = FakeContainer()
    first = CosmosMemoryStore(container)
    first.observe(conversation_id="c1", user_id="u1", text="We always prefer phased market entry", engagement_id=None)
    second = CosmosMemoryStore(container)  # a restart: nothing in process memory
    assert [i.value for i in second.recall("user:u1")] == ["We always prefer phased market entry"]
    assert [t["content"] for t in second.turns("c1")] == ["We always prefer phased market entry"]


def test_duplicates_are_not_stored_twice_across_restarts():
    container = FakeContainer()
    text = "We always prefer phased market entry"
    CosmosMemoryStore(container).observe(conversation_id="c1", user_id="u1", text=text)
    CosmosMemoryStore(container).observe(conversation_id="c2", user_id="u1", text=text)
    assert len([i for i in container.items if i["kind"] == "memory"]) == 1


def test_sensitive_text_is_never_persisted_verbatim():
    container = FakeContainer()
    CosmosMemoryStore(container).observe(conversation_id="c1", user_id="u1", text="my password is hunter2hunter2")
    assert "hunter2" not in json.dumps(container.items)


def test_facts_carry_a_ttl_and_expired_items_are_not_recalled():
    container = FakeContainer()
    store = CosmosMemoryStore(container)
    store.observe(conversation_id="c1", user_id="u1", engagement_id="e1", text="The client budget is capped at 10M dollars")
    fact = next(i for i in container.items if i["kind"] == "memory")
    assert 0 < fact["ttl"] <= 180 * 86400
    store.remember("user:u9", MemoryItem("fact", "user", "old", expires_at="2020-01-01T00:00:00+00:00"))
    assert store.recall("user:u9") == []


def test_retrievals_are_persisted():
    from app.knowledge.retriever import RetrievalRecord
    container = FakeContainer()
    rec = RetrievalRecord("ret_1", "q", "idx", ["d1"], [0.5], "now", {}, chunk_ids=["d1#0"], content_hashes=["h"])
    CosmosMemoryStore(container).log_retrieval("wf_1", rec)
    saved = [i for i in container.items if i["kind"] == "retrieval"]
    assert saved[0]["pk"] == "wf_1" and saved[0]["record"]["chunk_ids"] == ["d1#0"]


# ---- choosing backends ------------------------------------------------------------------------------------------------
def settings(**kw):
    return Settings(_env_file=None, llm_provider="stub", **kw)


def test_defaults_are_the_offline_stand_ins():
    b = build_backends(settings())
    assert type(b.embedder).__name__ == "HashingEmbedder" and type(b.retriever).__name__ == "LocalRetriever"
    assert b.data_source is None and type(b.memory).__name__ == "MemoryStore"


@pytest.mark.parametrize("build,kw,missing", [
    (lambda s: build_retriever(s, HashingEmbedder()), {"retriever": "azure_search"}, "AZURE_SEARCH_ENDPOINT"),
    (build_data_source, {"data_source": "databricks"}, "DATABRICKS_HOST"),
    (build_memory, {"memory_store": "cosmos"}, "COSMOS_ENDPOINT"),
    (build_embedder, {"embedding_deployment": "emb"}, "AZURE_OPENAI_ENDPOINT"),
])
def test_an_azure_backend_without_its_settings_fails_at_start_up_naming_the_setting(build, kw, missing):
    with pytest.raises(RuntimeError, match=missing):
        build(settings(**kw))


@pytest.mark.parametrize("build,kw", [
    (lambda s: build_retriever(s, HashingEmbedder()), {"retriever": "nope"}),
    (build_data_source, {"data_source": "nope"}),
    (build_memory, {"memory_store": "nope"}),
])
def test_unknown_backend_names_are_rejected(build, kw):
    with pytest.raises(RuntimeError, match="unknown"):
        build(settings(**kw))


def test_backend_secrets_are_masked_in_settings_output():
    shown = repr(settings(databricks_token="dapi-secret", cosmos_key="cosmos-secret", azure_search_api_key="search-secret"))
    assert "secret" not in shown


def test_keys_are_url_safe_for_awkward_ids_and_round_trip_through_search():
    client, emb = FakeSearch(), HashingEmbedder(8)
    awkward = {**DOC, "id": "reports/2026/uae market.pdf"}  # an ADLS path: slashes and a space
    ingest_documents([awkward], client, emb)
    retriever = AzureSearchRetriever(client, emb)
    ev, rec = retriever.search("UAE retail market")
    assert ev[0].chunk_id == "reports/2026/uae market.pdf#0"  # callers still see the readable id
    assert retriever.replay(rec)[0].chunk_id == "reports/2026/uae market.pdf#0"
