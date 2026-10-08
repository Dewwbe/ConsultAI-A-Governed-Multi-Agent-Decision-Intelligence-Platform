# ConsultAI — Governed Multi-Agent Consulting Delivery Platform

Agents do the work. The control plane decides what they are allowed to do.

ConsultAI decomposes a business engagement into specialised agent tasks (Discovery, Research, Data Analyst, Financial, Risk, Solution), evaluates the output, passes it through a Guardian, and requires human approval for high-risk decisions. All of it runs under a control plane providing policy, routing, budgets, memory, tracing and audit.

## Design principles

1. **LLM chooses, deterministic code calculates.** Financial maths lives in `tools/financial.py`.
2. **Deterministic guardrails first, AI Guardian second, human approval third** (risk-based autonomy).
3. **Strict tool contracts.** Every tool call is schema-validated and policy-checked before execution.
4. **Success is not task completion.** Quality = outcome + evidence + safety (see `control_plane/evaluator.py`).
5. **Least-privilege state.** Each agent receives only the slice of state it needs.
6. **LangGraph orchestrates; MCP connects tools.** Neither does the other's job.

## Repository layout

```
backend/app/
  api/            FastAPI routes (engagements, approvals, control-center)
  agents/         Six agents + report agent, all extend BaseAgent
  control_plane/  policy, guardian, evaluator, router, budget, reliability, cache, tool registry
  workflow/       LangGraph state machine with interrupt-based approval
  tools/          Deterministic tools (financial maths, SQL validation)
  knowledge/      Retriever abstraction (Azure AI Search / local stub)
  memory/         Short-term / long-term / workflow memory abstraction
  observability/  OpenTelemetry tracing + cost/metrics
  schemas/        Pydantic models and EngagementState
policies/         Declarative policy files (YAML)
frontend/         React AI Control Center (placeholder, built in Phase 4)
infra/            Docker, compose
docs/             Implementation plan
```

## Quick start

```bash
cp .env.example .env
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload
```

By default the platform runs in **offline mode** (`LLM_PROVIDER=stub`), using deterministic stub agents so the full workflow, guardian, approval and tracing paths can be exercised without any cloud credentials. Set `LLM_PROVIDER=azure_openai` and the Azure variables in `.env` to switch to real models.

## API (current)

| Method | Path | Purpose |
|---|---|---|
| POST | `/engagements` | Start an engagement; runs until completion or approval interrupt |
| GET | `/engagements/{id}` | State, scores, trace summary |
| POST | `/engagements/{id}/approval` | `approve` / `modify` / `reject` a paused engagement |
| GET | `/control-center/{id}/trace` | Spans, tool calls, cost, guardian decisions |

See `docs/IMPLEMENTATION_PLAN.md` for the phased build plan.
