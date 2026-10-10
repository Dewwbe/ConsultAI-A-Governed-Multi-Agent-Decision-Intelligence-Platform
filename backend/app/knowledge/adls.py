"""Read the knowledge corpus from Azure Blob Storage (which includes ADLS Gen2 accounts).

Convention: each `.json` blob is one document `{"id", "source", "text", "date", ...metadata}`; each `.md` or `.txt` blob
is a document whose id and source are its path and whose metadata comes from the blob's own metadata (`country`,
`industry`, `classification`, `allowed_groups` as a comma-separated list, `policy_version`, `date`).

This uses the Blob endpoint, not the Data Lake (`dfs`) one: the Blob endpoint reads ADLS Gen2 accounts too, and unlike
the Data Lake endpoint it works when soft delete or blob events are on (Azure's defaults). The container client is
injected, so reading is tested against a fake.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

TEXT_SUFFIXES = (".md", ".txt")
META_KEYS = ("country", "industry", "classification", "policy_version", "date")


def _doc_from_text(path: str, text: str, metadata: dict[str, str] | None) -> dict[str, Any]:
    meta = metadata or {}
    doc: dict[str, Any] = {"id": path, "source": path, "text": text}
    doc.update({k: meta[k] for k in META_KEYS if meta.get(k)})
    if meta.get("allowed_groups"):
        doc["allowed_groups"] = [g.strip() for g in meta["allowed_groups"].split(",") if g.strip()]
    return doc


def read_corpus(container: Any, prefix: str = "") -> Iterator[dict[str, Any]]:
    """Yield documents under `prefix`. Malformed JSON and unsupported file types are skipped: one bad file must not
    stop an ingest of the rest."""
    for blob in container.list_blobs(name_starts_with=prefix or None, include=["metadata"]):
        path = blob.name
        if not path.lower().endswith((".json", *TEXT_SUFFIXES)):
            continue  # also skips ADLS folder markers
        raw = container.download_blob(path).readall().decode("utf-8")
        if path.lower().endswith(".json"):
            try:
                doc = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(doc, dict) and doc.get("id") and doc.get("text"):
                doc.setdefault("source", path)
                yield doc
        else:
            yield _doc_from_text(path, raw, getattr(blob, "metadata", None))


def blob_endpoint(account_url: str) -> str:
    """Accept either spelling of the account address: `.dfs.core.windows.net` is rewritten to the Blob endpoint."""
    return account_url.rstrip("/").replace(".dfs.core.", ".blob.core.")


def file_system_client(account_url: str, container: str, credential: Any = None) -> Any:
    """A container client. With no credential it uses Microsoft Entra ID (DefaultAzureCredential)."""
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient
    service = BlobServiceClient(blob_endpoint(account_url), credential=credential or DefaultAzureCredential())
    return service.get_container_client(container)
