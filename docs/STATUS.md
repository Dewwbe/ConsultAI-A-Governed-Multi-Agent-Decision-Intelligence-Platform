# Status

Last updated 2026-10-08. Everything that can be built and verified without cloud services is built.

## Verified automatically

| Suite | Result |
|---|---|
| Backend (`pytest`) | 323 passed, 1 skipped (the optional Postgres test, which needs a server) |
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

## Not done: needs real services or real people

| Item | Why it is open |
|---|---|
| Azure AI Search retriever, ADLS ingestion, embeddings | Needs an Azure Search index and a storage account; the retriever interface and a local stub exist |
| Databricks `DataSource` | Needs a workspace; a local SQL source exists behind the same interface |
| Cosmos DB `MemoryStore` | Needs a Cosmos account; an in-process store exists behind the interface |
| Formal 20-run Phase 1 measurement | About 10 real-model runs showed 0% invalid structured output; the 20-run record was shortened on request. Run `backend/scripts/measure_schema_validity.py` to complete it |
| Judge calibration against real partner decisions | Needs real decisions; the decision dataset is recorded and exportable (`scripts/export_decisions.py`) |
| Azure Monitor and Foundry evaluator verification | Exporters are written and unit-tested against fakes; not run against live Azure |
| Docker image build and Postgres test | Both need the Docker daemon or a Postgres server running locally; CI covers the Python and Node steps |

## Known limits

* The offline stub models give identical numbers for similar questions, so demo data looks repetitive. Real models vary.
* Dev authentication trusts request headers and refuses to start unless `ENVIRONMENT=dev`.
* Colour contrast is verified by the palette validator, not by axe (jsdom has no layout).
