"""Check each configured Azure service end to end, with real calls.

    python backend/scripts/verify_azure.py
    python backend/scripts/verify_azure.py --only search monitor

Each check prints PASS, FAIL (with the reason) or SKIP (the service is not configured). It never prints a secret.
Checks that write (Cosmos) use a marked test item and delete it. Exit code is 1 if anything configured fails.

  openai    chat completion and an embedding from the configured deployments
  search    the index exists, a filtered hybrid search works, and a caller without clearance sees nothing restricted
  adls      the container is readable and holds documents
  databricks  SELECT 1, and the semantic layer for the policy's allowed tables
  cosmos    write, read and delete a test memory item
  monitor   a marked span is accepted by Application Insights (then how to find it)
  keyvault  every keyvault: reference in the environment resolves
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.adapters import azure_credential, build_embedder
from app.config import Settings, get_settings


class Skip(Exception):
    pass


def need(s: Settings, *names: str) -> None:
    missing = [n.upper() for n in names if not getattr(s, n)]
    if missing:
        raise Skip(f"not configured ({', '.join(missing)})")


def check_openai(s: Settings) -> str:
    need(s, "azure_openai_endpoint", "model_small")
    from app.control_plane.llm import AzureOpenAIProvider
    client = AzureOpenAIProvider(endpoint=s.azure_openai_endpoint, api_key=s.azure_openai_api_key,
                                 api_version=s.azure_openai_api_version, timeout_sec=s.llm_timeout_sec).client
    reply = client.chat.completions.create(model=s.model_small, messages=[{"role": "user", "content": "Reply with: ok"}],
                                           max_completion_tokens=16)
    out = f"chat deployment '{s.model_small}' answered ({reply.usage.total_tokens} tokens)"
    if s.embedding_deployment:
        out += f"; embeddings {len(build_embedder(s).embed('probe'))} dimensions"
    else:
        out += "; embedding deployment not set (EMBEDDING_DEPLOYMENT), so retrieval would use the offline embedder"
    return out


def check_search(s: Settings) -> str:
    need(s, "azure_search_endpoint", "embedding_deployment", "azure_openai_endpoint")
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient

    from app.knowledge.azure_search import AzureSearchRetriever
    cred = azure_credential(s.azure_search_api_key)
    index = SearchIndexClient(s.azure_search_endpoint, cred).get_index(s.azure_search_index)
    client = SearchClient(s.azure_search_endpoint, s.azure_search_index, cred)
    count = client.get_document_count()
    if count == 0:
        raise RuntimeError("the index is empty: run scripts/ingest_corpus.py first")
    retriever = AzureSearchRetriever(client, build_embedder(s), s.azure_search_index)
    ev, record = retriever.search("market entry risk", {"max_classification": "public"}, k=3)
    leaked = [e.chunk_id for e in ev if retriever.metadata_for(e.chunk_id).get("classification") not in (None, "public")]
    if leaked:
        raise RuntimeError(f"security trimming failed: public-only caller received {leaked}")
    unclear = [e.chunk_id for e in retriever.search("confidential client data", {"max_classification": "public"}, 20)[0]
               if retriever.metadata_for(e.chunk_id).get("allowed_groups")]
    if unclear:
        raise RuntimeError(f"group-restricted chunks were returned to a caller with no groups: {unclear}")
    if ev:
        retriever.replay(record)  # raises if a chunk cannot be reproduced exactly
    return f"index '{index.name}' has {count} chunks; filtered search returned {len(ev)}; replay reproduced it"


def check_adls(s: Settings) -> str:
    need(s, "adls_account_url", "adls_container")
    from app.knowledge.adls import file_system_client, read_corpus
    docs = list(read_corpus(file_system_client(s.adls_account_url, s.adls_container), s.adls_prefix))
    if not docs:
        raise RuntimeError("no .json/.md/.txt documents found under the configured container and prefix")
    return f"{len(docs)} readable document(s)"


def check_databricks(s: Settings) -> str:
    need(s, "databricks_host", "databricks_http_path")
    from app.control_plane.policy import PolicyEngine
    from app.data.databricks_source import DatabricksDataSource
    src = DatabricksDataSource(host=s.databricks_host, http_path=s.databricks_http_path, token=s.databricks_token,
                               catalog=s.databricks_catalog)
    if src.query("SELECT 1 AS one") != [{"one": 1}]:
        raise RuntimeError("SELECT 1 did not return one row")
    available = src.catalogs()
    if s.databricks_catalog not in available:
        raise RuntimeError(f"catalog '{s.databricks_catalog}' not found. Set DATABRICKS_CATALOG to one of: {', '.join(available)}")
    tables = PolicyEngine.from_file(s.policy_file).agent_spec("data_agent").get("allowed_tables", [])
    layer = src.describe(tables)
    missing = [t for t in tables if t not in layer]
    if missing:
        raise RuntimeError(f"allowed tables not visible to this identity or catalog: {missing}")
    return f"warehouse reachable; semantic layer built for {len(layer)} table(s)"


def check_cosmos(s: Settings) -> str:
    need(s, "cosmos_endpoint")
    from app.adapters import build_memory
    store = build_memory(s.model_copy(update={"memory_store": "cosmos"}))
    key = f"verify:{uuid.uuid4().hex[:8]}"
    from app.memory.store import MemoryItem
    store.remember(key, MemoryItem("preference", "global", "verification item", source="verify_azure", expires_at=None))
    got = store.recall(key)
    for d in store._get(key, "memory"):  # clean up: the test item is not real memory
        store.container.delete_item(d["id"], partition_key=key)
    if [i.value for i in got] != ["verification item"]:
        raise RuntimeError(f"read back {got!r}")
    return "wrote, read back and deleted a test item"


def check_monitor(s: Settings) -> str:
    need(s, "applicationinsights_connection_string")
    raw = s.applicationinsights_connection_string
    parts = dict(p.split("=", 1) for p in raw.strip().strip("\"'").split(";") if "=" in p)
    problems = []
    if raw != raw.strip() or raw[:1] in "\"'" or raw[-1:] in "\"'":
        problems.append("it has quotes or spaces around it (remove them)")
    if "InstrumentationKey" not in parts:
        shape = "looks like a bare GUID: that is the Application ID or key, not the connection string" if len(raw.strip()) < 60             else "has no 'InstrumentationKey=' part"
        problems.append(shape)
    if "IngestionEndpoint" not in parts:
        problems.append("has no 'IngestionEndpoint=https://...' part")
    if problems:
        raise RuntimeError(f"APPLICATIONINSIGHTS_CONNECTION_STRING is not a connection string: {'; '.join(problems)}. "
                           f"It is {len(raw)} characters and has these parts: {sorted(parts) or 'none'}. Copy "
                           "'Connection String' from the Application Insights Overview page.")
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
    marker = f"verify-{uuid.uuid4().hex[:8]}"
    exporter = AzureMonitorTraceExporter(connection_string=s.applicationinsights_connection_string)
    results: list[SpanExportResult] = []
    original = exporter.export
    exporter.export = lambda spans, **kw: results.append(original(spans, **kw)) or results[-1]  # type: ignore[method-assign]
    provider = TracerProvider(resource=Resource.create({"service.name": "consultai-verify"}))
    from opentelemetry import trace
    trace.set_tracer_provider(provider)  # the Azure exporter reads the resource from the global provider
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("verify").start_as_current_span("consultai.verify", attributes={"consultai.verification": marker}):
        pass
    provider.force_flush()
    if not results or results[-1] != SpanExportResult.SUCCESS:
        raise RuntimeError("Application Insights did not accept the span (check the connection string and network)")
    return (f"span accepted. It appears in Application Insights within a few minutes. Find it with:\n"
            f"      dependencies | where customDimensions['consultai.verification'] == '{marker}'")


def check_keyvault(s: Settings) -> str:
    need(s, "key_vault_url")
    from app.security.secrets import KeyVaultSecretProvider
    refs = [k for k, v in os.environ.items() if v.startswith("keyvault:")]
    if not refs:
        return "vault reachable; no keyvault: references are set in the environment"
    provider = KeyVaultSecretProvider(s.key_vault_url)
    for k in refs:
        provider.get(os.environ[k].removeprefix("keyvault:"))
    return f"{len(refs)} reference(s) resolved ({', '.join(refs)})"


CHECKS: dict[str, Callable[[Settings], str]] = {
    "openai": check_openai, "search": check_search, "adls": check_adls, "databricks": check_databricks,
    "cosmos": check_cosmos, "monitor": check_monitor, "keyvault": check_keyvault}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", choices=CHECKS, help="run only these checks")
    args = ap.parse_args()
    settings = get_settings()
    failed = 0
    for name in args.only or CHECKS:
        started = time.monotonic()
        try:
            detail, status = CHECKS[name](settings), "PASS"
        except Skip as why:
            detail, status = str(why), "SKIP"
        except Exception as exc:  # noqa: BLE001
            detail, status, failed = f"{type(exc).__name__}: {exc}", "FAIL", failed + 1
        print(f"{status:4}  {name:10} {detail}  [{time.monotonic() - started:.1f}s]")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
