# Status

Last updated 2026-10-08. Everything that can be built and verified without cloud services is built.

## Verified automatically

| Suite | Result |
|---|---|
| Backend (`pytest`) | 365 passed, 1 skipped (the optional Postgres test, which needs a server) |
| Frontend unit, component and accessibility (`npm test`) | 230 passed, 2 skipped (live-backend contract test, run in CI) |
| End to end (`npm run e2e`) | 8 passed: approve, reject, modify, role limits, Control Center, Governance, tablet layout |
| Static checks | `ruff`, `eslint`, `tsc --strict` and the production build are clean |
| CI | backend, frontend, generated-client freshness, live contract test, Playwright e2e |

## Built

| Area | What exists |
|---|---|
| Workflow | Six agents plus report, LangGraph with an approval interrupt, checkpointing, restart recovery |
| Control plane | Versioned policy, rules and AI Guardian, evaluator with bounded LLM judge, model router and gateway, budgets, circuit breakers, rate limits, run queue (429), tool timeouts, quality degradation |
| Security | Dev and Entra auth, RBAC matrix in policy, PII redaction, Key Vault references, secrets masked in logs |
| Observability | OpenTelemetry (OTLP and Azure Monitor exporters), per-run metrics and aggregates, MLflow export |
| API | Engagements, SSE events, approvals, evidence, trace, cost, metrics, governance (policy history with drift detection, tools, providers, budgets, degradation) |
| Frontend | New engagement, live pipeline, evidence and data views, partner review and approval, Control Center (overview and run), Governance, Entra sign-in, dark mode, axe-tested pages, tablet layouts |
| Demo | `python backend/scripts/demo.py`: API, seeded data and UI in one command |

## Built, tested against fakes, waiting for a live check

These are written and unit-tested against in-memory fakes of the Azure SDK clients (365 backend tests). What a fake
cannot prove is that the real service accepts them, so each has a live check in `scripts/verify_azure.py`.

| Item | Code | Switch on with | Live check |
|---|---|---|---|
| Azure AI Search retriever (hybrid search, security trimming in the query, replay by content hash), embeddings | `knowledge/azure_search.py`, `scripts/ingest_corpus.py` | `RETRIEVER=azure_search`, `AZURE_SEARCH_ENDPOINT`, `EMBEDDING_DEPLOYMENT` | `verify_azure.py --only search` |
| ADLS corpus reader | `knowledge/adls.py` | `ingest_corpus.py --adls`, `ADLS_ACCOUNT_URL`, `ADLS_CONTAINER` | `--only adls` |
| Databricks `DataSource` (single read-only SELECT, row cap, semantic layer from Unity Catalog) | `data/databricks_source.py` | `DATA_SOURCE=databricks`, `DATABRICKS_HOST`, `DATABRICKS_HTTP_PATH` | `--only databricks` |
| Cosmos DB `MemoryStore` (same rules as the in-memory store; TTL on facts) | `memory/cosmos_store.py` | `MEMORY_STORE=cosmos`, `COSMOS_ENDPOINT` | `--only cosmos` |
| Azure Monitor export | `observability/export.py` | `APPLICATIONINSIGHTS_CONNECTION_STRING` | `--only monitor` prints the query that finds the test span |
| Judge calibration | `control_plane/calibration.py`, `scripts/calibrate_judge.py` | needs real decisions | run the script; it states when the sample is too thin |
| Docker images | `infra/docker`, `frontend/Dockerfile` | `docker build` | API image built and answered `/health` |

## Not done: needs real services or real people

| Item | Why it is open |
|---|---|
| A live run of `verify_azure.py` | Needs your Azure resources and credentials; nothing above has touched a real Search, ADLS, Databricks, Cosmos or Application Insights service yet |
| Formal 20-run Phase 1 measurement | About 10 real-model runs showed 0% invalid structured output. Run `backend/scripts/measure_schema_validity.py` to complete the record |
| Judge calibration result | Needs at least 30 approved and 30 not-approved partner decisions on real runs. With fewer, the script reports "thin sample" |
| Foundry evaluators | The LLM judge, bounded by deterministic checks, is the evaluator; Foundry is not wired |

## Known limits

* The offline stub models give identical numbers for similar questions, so demo data looks repetitive. Real models vary.
* Dev authentication trusts request headers and refuses to start unless `ENVIRONMENT=dev`.
* Colour contrast is verified by the palette validator, not by axe (jsdom has no layout).
