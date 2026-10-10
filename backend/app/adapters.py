"""Choose the knowledge, data and memory backends from settings.

The defaults are the offline stand-ins, so nothing here touches the network unless a setting asks for it. Each Azure
backend is built lazily from its own settings and fails at start-up with a message naming the missing setting,
rather than on the first request.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.knowledge.demo_corpus import DEMO_CORPUS
from app.knowledge.embeddings import Embedder, HashingEmbedder
from app.knowledge.retriever import LocalRetriever
from app.memory.store import MemoryStore


@dataclass
class Backends:
    retriever: Any
    embedder: Embedder
    data_source: Any
    memory: MemoryStore


def _require(settings: Settings, *names: str) -> None:
    missing = [n.upper() for n in names if not getattr(settings, n)]
    if missing:
        raise RuntimeError(f"missing settings: {', '.join(missing)}")


def azure_credential(api_key: str = "") -> Any:
    """An API key if one is configured, otherwise Microsoft Entra ID."""
    if api_key:
        from azure.core.credentials import AzureKeyCredential
        return AzureKeyCredential(api_key)
    from azure.identity import DefaultAzureCredential
    return DefaultAzureCredential()


def build_embedder(settings: Settings, openai_client: Any = None) -> Embedder:
    if not settings.embedding_deployment:
        return HashingEmbedder()
    from app.knowledge.azure_search import AzureOpenAIEmbedder
    if openai_client is None:
        from app.control_plane.llm import AzureOpenAIProvider
        _require(settings, "azure_openai_endpoint")
        openai_client = AzureOpenAIProvider(endpoint=settings.azure_openai_endpoint, api_key=settings.azure_openai_api_key,
                                            api_version=settings.azure_openai_api_version,
                                            timeout_sec=settings.llm_timeout_sec).client
    return AzureOpenAIEmbedder(openai_client, settings.embedding_deployment, settings.embedding_dimensions or None)


def build_retriever(settings: Settings, embedder: Embedder) -> Any:
    if settings.retriever == "local":
        return LocalRetriever(DEMO_CORPUS, embedder=embedder)
    if settings.retriever == "azure_search":
        _require(settings, "azure_search_endpoint", "embedding_deployment")
        from azure.search.documents import SearchClient

        from app.knowledge.azure_search import AzureSearchRetriever
        client = SearchClient(settings.azure_search_endpoint, settings.azure_search_index,
                              azure_credential(settings.azure_search_api_key))
        return AzureSearchRetriever(client, embedder, settings.azure_search_index)
    raise RuntimeError(f"unknown RETRIEVER {settings.retriever!r} (use local or azure_search)")


def build_data_source(settings: Settings) -> Any:
    if settings.data_source == "sqlite":
        return None  # each run builds its own private in-memory dataset (a SQLite connection is not shared across runs)
    if settings.data_source == "databricks":
        _require(settings, "databricks_host", "databricks_http_path")
        from app.data.databricks_source import DatabricksDataSource
        return DatabricksDataSource(host=settings.databricks_host, http_path=settings.databricks_http_path,
                                    token=settings.databricks_token, catalog=settings.databricks_catalog)
    raise RuntimeError(f"unknown DATA_SOURCE {settings.data_source!r} (use sqlite or databricks)")


def build_memory(settings: Settings) -> MemoryStore:
    if settings.memory_store == "memory":
        return MemoryStore()
    if settings.memory_store == "cosmos":
        _require(settings, "cosmos_endpoint")
        from azure.cosmos import CosmosClient, PartitionKey

        from app.memory.cosmos_store import CosmosMemoryStore
        client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key or azure_credential())
        database = client.create_database_if_not_exists(settings.cosmos_database)
        container = database.create_container_if_not_exists(
            settings.cosmos_container, partition_key=PartitionKey(path="/pk"), default_ttl=-1)  # -1: items opt in to a TTL
        return CosmosMemoryStore(container)
    raise RuntimeError(f"unknown MEMORY_STORE {settings.memory_store!r} (use memory or cosmos)")


def build_backends(settings: Settings) -> Backends:
    embedder = build_embedder(settings)
    return Backends(build_retriever(settings, embedder), embedder, build_data_source(settings), build_memory(settings))
