"""Create the Azure AI Search index and load documents into it.

    python backend/scripts/ingest_corpus.py --demo        # the built-in demo corpus (a quick end-to-end check)
    python backend/scripts/ingest_corpus.py --adls        # every document under ADLS_CONTAINER / ADLS_PREFIX

Needs AZURE_SEARCH_ENDPOINT, EMBEDDING_DEPLOYMENT and AZURE_OPENAI_ENDPOINT (and ADLS_ACCOUNT_URL / ADLS_CONTAINER
for --adls) in the environment or .env. Authentication is a key if one is set, otherwise Microsoft Entra ID
(`az login`). Safe to re-run: documents are merged by chunk id and chunks that no longer exist are removed.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.adapters import azure_credential, build_embedder
from app.config import get_settings
from app.knowledge.azure_search import ensure_index, ingest_documents


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--demo", action="store_true", help="load the built-in demo corpus")
    src.add_argument("--adls", action="store_true", help="load documents from Azure Data Lake Storage")
    args = ap.parse_args()

    s = get_settings()
    missing = [n.upper() for n in ("azure_search_endpoint", "embedding_deployment", "azure_openai_endpoint") if not getattr(s, n)]
    if args.adls:
        missing += [n.upper() for n in ("adls_account_url", "adls_container") if not getattr(s, n)]
    if missing:
        print(f"missing settings: {', '.join(missing)}", file=sys.stderr)
        return 2

    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient

    embedder = build_embedder(s)
    dimensions = len(embedder.embed("dimension probe"))
    credential = azure_credential(s.azure_search_api_key)
    ensure_index(SearchIndexClient(s.azure_search_endpoint, credential), s.azure_search_index, dimensions)
    print(f"index '{s.azure_search_index}' ready ({dimensions}-dimension vectors, {embedder.name})")

    if args.demo:
        from app.knowledge.demo_corpus import DEMO_CORPUS
        docs = list(DEMO_CORPUS)
    else:
        from app.knowledge.adls import file_system_client, read_corpus
        docs = list(read_corpus(file_system_client(s.adls_account_url, s.adls_container), s.adls_prefix))
    print(f"read {len(docs)} document(s)")
    report = ingest_documents(docs, SearchClient(s.azure_search_endpoint, s.azure_search_index, credential), embedder)
    print(f"uploaded {report.chunks_uploaded} chunk(s), removed {report.chunks_removed} stale chunk(s)")
    for failure in report.failed:
        print(f"  FAILED {failure}", file=sys.stderr)
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
