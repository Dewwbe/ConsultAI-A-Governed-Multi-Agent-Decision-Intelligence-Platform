import { http, HttpResponse } from "msw";
import completed from "./fixtures/completed.json";
import detail from "./fixtures/detail.json";
import evidence from "./fixtures/evidence.json";
import eventsText from "./fixtures/events.sse.txt?raw";
import guardian from "./fixtures/guardian.json";
import list from "./fixtures/list.json";
import tables from "./fixtures/tables.json";
import trace from "./fixtures/trace.json";

export const API = "http://localhost:8000";

/** Fixtures were recorded from a real backend run, so the shapes are the contract's, not guesses. */
export const fixtures = { detail, completed, evidence, tables, trace, guardian, list, eventsText };

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
    return HttpResponse.json({ user_id: user, name: user, roles, can_approve: roles.includes("Partner") });
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
  http.get(`${API}/engagements/:id/guardian`, () => HttpResponse.json(guardian)),
  http.get(`${API}/engagements/:id/events`, () => sseResponse(eventsText)),
  http.get(`${API}/control-center/:id/trace`, () => HttpResponse.json(trace)),
  http.post(`${API}/engagements/:id/retrievals/:rid/replay`, ({ params }) =>
    HttpResponse.json({ retrieval_id: params.rid, reproduced: true, error: null, evidence: evidence.claims.slice(0, 2) }),
  ),
];
