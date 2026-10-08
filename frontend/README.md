# AI Control Center (React) — Phase 4/5

Planned views, all backed by the existing API:

1. **Engagement review** — recommendation, evidence/financial/groundedness scores, cost, Approve / Modify / Reject
   (`POST /engagements/{id}/approval`).
2. **Trace explorer** — span tree from `GET /control-center/{id}/trace` (agents, LLM calls, tools, retrievals).
3. **Guardian log** — ALLOW / BLOCK / ESCALATE decisions with reasons.
4. **Cost & quality** — tokens, latency, cost per successful task, evaluation scores over time.

Scaffold with `npm create vite@latest . -- --template react-ts` when Phase 4 starts.
