import { http, HttpResponse } from "msw";
import completed from "./fixtures/completed.json";
import cost from "./fixtures/cost.json";
import detail from "./fixtures/detail.json";
import evidence from "./fixtures/evidence.json";
import eventsText from "./fixtures/events.sse.txt?raw";
import guardian from "./fixtures/guardian.json";
import list from "./fixtures/list.json";
import summary from "./fixtures/summary.json";
import timeseries from "./fixtures/timeseries.json";
import tables from "./fixtures/tables.json";
import budgets from "./fixtures/budgets.json";
import degradation from "./fixtures/degradation.json";
import policy from "./fixtures/policy.json";
import policyVersion from "./fixtures/policy_version.json";
import policyVersions from "./fixtures/policy_versions.json";
import providers from "./fixtures/providers.json";
import tools from "./fixtures/tools.json";
import trace from "./fixtures/trace.json";

export const API = "http://localhost:8000";

/** Fixtures were recorded from a real backend run, so the shapes are the contract's, not guesses. */
export const fixtures = { detail, completed, evidence, tables, trace, guardian, list, eventsText, cost, summary, timeseries, policy, policyVersions, policyVersion, tools, providers, budgets, degradation };

export function sseResponse(text: string, chunks = 3): Response {
  const enc = new TextEncoder();
  const size = Math.ceil(text.length / chunks);
  return new HttpResponse(
    new ReadableStream({
      start(controller) {
        for (let i = 0; i < text.length; i += size) controller.enqueue(enc.encode(text.slice(i, i + size)));
        controller.close();
      },
    }),
    { headers: { "Content-Type": "text/event-stream" } },
  );
}

const DONE_ID = completed.workflow_id;

/** Mirrors the backend contract. Tests override single endpoints with server.use(...). */
export const handlers = [
  http.get(`${API}/health`, () => HttpResponse.json({ status: "ok", llm_provider: "stub" })),
  http.get(`${API}/me`, ({ request }) => {
    const user = request.headers.get("x-dev-user") ?? "anonymous";
    const roles = (request.headers.get("x-dev-roles") ?? "").split(",").filter(Boolean);
    const permissions = roles.some((r) => r === "Admin" || r === "Auditor") ? ["governance:view"] : [];
    return HttpResponse.json({ user_id: user, name: user, roles, can_approve: roles.includes("Partner"), permissions });
  }),

  http.get(`${API}/engagements`, ({ request }) => {
    const url = new URL(request.url);
    const status = url.searchParams.get("status");
    const limit = Number(url.searchParams.get("limit") ?? 50);
    const offset = Number(url.searchParams.get("offset") ?? 0);
    const items = list.items.filter((i) => !status || i.status === status);
    return HttpResponse.json({ items: items.slice(offset, offset + limit), total: items.length, limit, offset });
  }),
  http.post(`${API}/engagements`, async ({ request }) => {
    const body = (await request.json()) as { business_problem: string; industry: string };
    return HttpResponse.json({
      ...detail,
      workflow_id: "wf_new",
      status: "running",
      pending_node: [],
      state: { business_problem: body.business_problem, industry: body.industry },
      guardian_decisions: [],
    });
  }),
  http.get(`${API}/engagements/:id`, ({ params }) => {
    if (params.id === "wf_missing") return HttpResponse.json({ detail: "engagement not found" }, { status: 404 });
    return HttpResponse.json(params.id === DONE_ID ? completed : { ...detail, workflow_id: params.id });
  }),
  http.get(`${API}/engagements/:id/evidence`, () => HttpResponse.json(evidence)),
  http.get(`${API}/engagements/:id/tables`, () => HttpResponse.json(tables)),
  http.get(`${API}/engagements/:id/approvals`, () => HttpResponse.json([])),
  http.get(`${API}/engagements/:id/cost`, () => HttpResponse.json(cost)),
  http.get(`${API}/engagements/:id/guardian`, () => HttpResponse.json(guardian)),
  http.get(`${API}/engagements/:id/events`, () => sseResponse(eventsText)),
  http.get(`${API}/metrics/summary`, () => HttpResponse.json(summary)),
  http.get(`${API}/metrics/timeseries`, ({ request }) =>
    HttpResponse.json({ ...timeseries, metric: new URL(request.url).searchParams.get("metric") ?? "cost_usd" }),
  ),
  http.get(`${API}/governance/policy`, () => HttpResponse.json(policy)),
  http.get(`${API}/governance/policy/versions`, () => HttpResponse.json(policyVersions)),
  http.get(`${API}/governance/policy/versions/:key`, () => HttpResponse.json(policyVersion)),
  http.get(`${API}/governance/tools`, () => HttpResponse.json(tools)),
  http.get(`${API}/governance/providers`, () => HttpResponse.json(providers)),
  http.get(`${API}/governance/budgets`, () => HttpResponse.json(budgets)),
  http.get(`${API}/governance/degradation`, () => HttpResponse.json(degradation)),
  http.get(`${API}/control-center/:id/trace`, () => HttpResponse.json(trace)),
  http.post(`${API}/engagements/:id/retrievals/:rid/replay`, ({ params }) =>
    HttpResponse.json({ retrieval_id: params.rid, reproduced: true, error: null, evidence: evidence.claims.slice(0, 2) }),
  ),
];
