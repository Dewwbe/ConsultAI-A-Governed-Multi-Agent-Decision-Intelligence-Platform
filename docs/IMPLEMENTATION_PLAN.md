# ConsultAI — Project Implementation Plan

Version 1.0 · 7 October 2026

## 1. Purpose and scope

Build ConsultAI, a governed multi-agent consulting delivery platform, in seven phases. Each phase ends in a demonstrable, tested increment. The base repository delivered with this plan already contains the Phase 0 foundation and the offline skeleton of Phases 1, 3 and 4 (see section 3).

**Guiding rule:** agents do the work; the control plane decides what they may do.

## 2. Assumptions and open items (to be confirmed)

| # | Item | Impact | Proposed handling |
|---|---|---|---|
| 1 | Azure subscription with Azure OpenAI/Foundry, AI Search, Cosmos DB, ADLS Gen2 and Databricks available | Blocks Phases 1–2 against real services | Develop offline first (stub provider, local retriever); switch via config |
| 2 | Model names/versions are not fixed | Router uses tiers (`small`/`medium`/`reasoning`) mapped via env vars | Fill `MODEL_*` once deployments exist |
| 3 | No real client or market dataset | Demo corpus and demo data source are placeholders | Create a synthetic retail dataset in Phase 2 |
| 4 | Price table in `router.py` is illustrative | Cost metrics are indicative until updated | Load from `model_registry` in Phase 5 |
| 5 | Frontend not started | Human approval works through API only | Phase 4 |
| 6 | Team size and calendar not stated | Durations below are effort estimates for one engineer | Rescale when staffing is known |

## 3. Current state of the base repository

| Area | Status |
|---|---|
| Policy engine (allow/deny/escalate, versioned cache, provider rules) | Implemented, tested |
| Tool registry with JSON-schema contracts | Implemented, tested |
| Financial tools (ROI, NPV, payback, scenario, sensitivity) | Implemented, tested |
| SQL read-only validator | Implemented, tested |
| Budget manager, retry/backoff, circuit breaker | Implemented, tested |
| Model router (tier, budget downgrade, data-classification filter) | Implemented, tested |
| Guardian (deterministic rules) and heuristic evaluator | Implemented; evaluator is heuristic |
| Six agents + report agent | Implemented against a **stub LLM provider**; Azure provider is a placeholder |
| LangGraph workflow with `interrupt()` approval and resume | Implemented, tested (approve / modify / reject) |
| Tracing (OTel spans + in-process store) and metrics | Implemented; no exporter configured |
| Retriever, memory store | In-memory only |
| FastAPI endpoints, Dockerfile, compose, CI | Implemented |
| Frontend, Azure integrations, MLflow, persistence | Not started |

Tests: 21 passing (`cd backend && pytest`).

**Known deviation from the architecture diagram:** Financial and Risk run sequentially, because the specification has the Risk Agent consuming financial output. Research and Data run in parallel.

## 4. Phased plan

Effort is indicative for one engineer.

### Phase 0 — Foundation (done in base repo)
Repository, CI, containers, policy file, state model with least-privilege views.
**Exit:** CI green; `docker compose up` serves `/health`.

### Phase 1 — Core agents on real models (≈2 weeks)
- Implement `AzureOpenAIProvider` with structured outputs, token/cost accounting, 429 `Retry-After` handling.
- Replace stub outputs in Discovery, Research, Data, Solution with real prompts; version prompts in a prompt registry (file-based first).
- Add malformed-output path: schema validation → repair prompt → fallback model → escalate.
- Add `GET /engagements` listing and request validation.
**Exit:** an end-to-end run on a real model for the UAE example produces schema-valid output at every step; invalid-schema rate measured on 20 runs.

### Phase 2 — Enterprise knowledge and data (≈3 weeks)
- ADLS Gen2 → chunking → embeddings → Azure AI Search index with metadata (country, industry, classification, permissions).
- `AzureSearchRetriever`: hybrid + semantic ranking, permission filters, citation verification; persist `RetrievalRecord`.
- Databricks: Delta tables, Unity Catalog, SQL warehouse; implement `DataSource`; populate the semantic layer (table context) from catalog metadata.
- Cosmos DB `MemoryStore` (turns, summaries, facts, preferences); classification rule so not every sentence becomes long-term memory.
- Policy KB lookups and semantic cache with `source_version`, `expiration`, `embedding_version`.
**Exit:** research claims carry verified sources; Data Agent answers only from SQL; a retrieval can be replayed from its stored record.

### Phase 3 — Decision intelligence (≈1.5 weeks)
- Extend financial tools (margin, growth inputs from Data Agent output rather than fixed cases).
- Risk taxonomy store and historical-risk lookup; calibrate probability/impact guidance.
- Solution Agent: constraint-aware option generation; explicit assumptions list.
**Exit:** every number in a recommendation traces to a tool call; options respect stated constraints in tests.

### Phase 4 — Trust: evaluation, guardian, approval UI (≈3 weeks)
- Replace heuristic evaluator with LLM-judge/Foundry/MLflow evaluators (groundedness, task adherence, tool-call accuracy, contradiction detection); keep `EvaluationReport` interface.
- Guardian Layer 2: LLM reviewer that may only make decisions stricter; ALLOW/BLOCK/MODIFY/RETRY handling for MODIFY and RETRY (currently ALLOW/BLOCK/ESCALATE).
- Persist approvals and workflow state in PostgreSQL; switch LangGraph checkpointer from `MemorySaver` to a Postgres saver.
- React approval screen (approve / modify / reject) and Entra ID auth.
- Record human decisions as an evaluation dataset.
**Exit:** a high-risk run pauses, survives an API restart, and resumes after approval.

### Phase 5 — Observability (≈2 weeks)
- OTLP export to Azure Monitor/Application Insights; MLflow tracing and trace-level evaluation.
- Full metric set (intent, tool, safety, business, economics) with cost per successful task.
- AI Control Center UI: trace explorer, guardian log, cost and quality views.
**Exit:** one dashboard shows agents, retrieved evidence, tool calls, cost, latency, scores, guardian decisions and the reason for each approval.

### Phase 6 — Production resilience (≈2 weeks)
- Per-tool connect/read/total timeouts with real cancellation (async tools); workflow deadline.
- Token-bucket rate limiting, concurrency limits, queueing.
- Provider fallback respecting data classification; circuit breakers per provider.
- Quality-degradation controller: when groundedness or tool correctness falls below thresholds, reduce autonomy, use stronger model or more retrieval, require review.
- Key Vault for secrets; RBAC; PII handling at the gateway.
**Exit:** fault-injection tests (timeouts, 429s, malformed output, quality drop) behave as specified.

### Phase 7 — Optimisation (≈2 weeks, optional)
- Prompt A/B, retrieval tuning, semantic caching, model-routing tuning.
- Fine-tuning gate: only after an evaluation dataset exists; candidates are tool selection, structured output and risk classification (not knowledge).
**Exit:** documented before/after on cost per successful task and quality.

**Total indicative effort:** about 15.5 weeks for one engineer including Phase 7; about 13.5 weeks without it. Parallel work on the frontend (Phases 4–5) can shorten the calendar.

## 5. Cross-cutting requirements

- **Security:** default-deny policy, no secrets in repo, least-privilege state views, read-only SQL, provider allow-list per data classification.
- **Testing:** unit tests for every control-plane component; workflow tests for approve/modify/reject; fault-injection tests from Phase 6; evaluation set curated from Phase 4 onward.
- **Documentation:** README anti-reward-hacking section (success is outcome + evidence + safety, not task completion); architecture decision records for each major choice.

## 6. Risks

| Risk | Mitigation |
|---|---|
| Cloud service access delayed | Offline mode keeps development unblocked |
| LLM-judge evaluators are themselves noisy | Calibrate against human decisions collected at approval |
| Cost overrun during development | Engagement budgets enforced in code; low-cost tier by default |
| Scope creep across seven phases | Each phase has an exit criterion; Phase 7 is optional |
| Synthetic data weakens the demo | Build a coherent synthetic retail dataset in Phase 2 |

## 7. Demo target

An interviewer can submit "Should we expand into the UAE?", watch agents run, inspect evidence, tool calls, cost and scores, see the Guardian escalate, and approve, modify or reject in the Control Center.
