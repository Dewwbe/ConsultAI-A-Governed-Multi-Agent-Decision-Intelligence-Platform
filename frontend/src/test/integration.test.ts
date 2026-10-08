/**
 * Contract test against a REAL running backend. Skipped unless E2E_API_URL is set:
 *
 *   (backend)   LLM_PROVIDER=stub uvicorn app.main:app --port 8030
 *   (frontend)  $env:E2E_API_URL = "http://localhost:8030"; npm test -- src/test/integration.test.ts
 *
 * It uses the same client, stream reader and pipeline logic as the app, so a backend change that would
 * break the UI shows up here instead of in front of a user.
 */
import { http, passthrough } from "msw";
import { describe, expect, it } from "vitest";
import { createApi } from "@/api/client";
import { unwrap } from "@/api/errors";
import { readSse } from "@/api/sse";
import { isTerminalEvent, type EngagementEvent } from "@/api/types";
import { derivePipeline } from "@/features/engagements/pipeline";
import { server } from "@/mocks/server";

const BASE = process.env.E2E_API_URL;
const PARTNER = { user: "pat", roles: ["Partner"] };

async function collect(base: string, id: string, after = 0): Promise<EngagementEvent[]> {
  const events: EngagementEvent[] = [];
  await readSse(`${base}/engagements/${id}/events?after=${after}`, {
    headers: { "X-Dev-User": PARTNER.user, "X-Dev-Roles": PARTNER.roles.join(",") },
    onMessage: (m) => events.push({ ...(m.data as object), id: m.id ?? 0, type: m.event } as EngagementEvent),
  });
  return events;
}

describe.skipIf(!BASE)("against a live backend", () => {
  it("runs an engagement end to end: create, stream, inspect, approve", async () => {
    server.use(http.all(`${BASE}/*`, () => passthrough())); // let real requests through the mock server
    const api = createApi({ baseUrl: BASE!, getIdentity: () => PARTNER });

    const created = await unwrap(
      api.POST("/engagements", {
        params: { query: { wait: false } },
        body: {
          business_problem: "Should we expand into the UAE market?",
          industry: "Retail",
          objectives: ["Increase revenue"],
          constraints: ["Budget under $10M", "Launch within 18 months"],
          data_classification: "confidential",
        },
      }),
    );
    expect(["running", "awaiting_approval"]).toContain(created.status);
    const id = created.workflow_id;

    // the stream ends when the run pauses for approval
    const events = await collect(BASE!, id);
    expect(events[0]?.type).toBe("run_started");
    expect(events.at(-1)?.type).toBe("approval_requested");
    expect(events.filter((e) => isTerminalEvent(e.type))).toHaveLength(1);
    const steps = derivePipeline(events, "awaiting_approval").flat();
    for (const s of steps.filter((x) => x.key !== "approval" && x.key !== "report_agent")) expect(s.state, s.key).toBe("done");
    expect(steps.find((s) => s.key === "approval")?.state).toBe("paused");

    // every panel's data is there
    const detail = await unwrap(api.GET("/engagements/{workflow_id}", { params: { path: { workflow_id: id } } }));
    expect(detail.status).toBe("awaiting_approval");
    expect(detail.state.recommendation?.id).toBeTruthy();
    expect(detail.state.financial_models?.length).toBeGreaterThan(0);
    expect(detail.state.risks?.length).toBeGreaterThan(0);
    expect(detail.state.options?.length).toBeGreaterThan(0);
    const evidence = await unwrap(api.GET("/engagements/{workflow_id}/evidence", { params: { path: { workflow_id: id } } }));
    expect(evidence.claims.length).toBeGreaterThan(0);
    expect(evidence.claims.every((c) => c.verified)).toBe(true);
    const tables = await unwrap(api.GET("/engagements/{workflow_id}/tables", { params: { path: { workflow_id: id } } }));
    expect(tables.datasets).toContain("finance.revenue");
    const listed = await unwrap(api.GET("/engagements", { params: { query: { status: "awaiting_approval", limit: 200 } } }));
    expect(listed.items.some((i) => i.workflow_id === id)).toBe(true);

    // the pause really needs a partner: an analyst is refused, the partner succeeds, the stream resumes
    const analyst = createApi({ baseUrl: BASE!, getIdentity: () => ({ user: "ann", roles: ["Analyst"] }) });
    await expect(
      unwrap(analyst.POST("/engagements/{workflow_id}/approval", { params: { path: { workflow_id: id } }, body: { decision: "approve", changes: {}, reason: "" } })),
    ).rejects.toMatchObject({ name: "ForbiddenError", status: 403 });
    const lastId = events.at(-1)!.id;
    const done = await unwrap(
      api.POST("/engagements/{workflow_id}/approval", { params: { path: { workflow_id: id } }, body: { decision: "approve", changes: {}, reason: "ok" } }),
    );
    expect(done.status).toBe("completed");
    expect(done.state.report?.markdown).toContain("Engagement Report");
    const later = await collect(BASE!, id, lastId);
    expect(later[0]?.type).toBe("approval_decided");
    expect(later.at(-1)?.type).toBe("run_completed");
    await expect(
      unwrap(api.POST("/engagements/{workflow_id}/approval", { params: { path: { workflow_id: id } }, body: { decision: "approve", changes: {}, reason: "" } })),
    ).rejects.toMatchObject({ name: "ConflictError", status: 409 });
  }, 60_000);

  it("reports a missing engagement as a typed 404 on both the data and the stream", async () => {
    server.use(http.all(`${BASE}/*`, () => passthrough()));
    const api = createApi({ baseUrl: BASE!, getIdentity: () => PARTNER });
    await expect(unwrap(api.GET("/engagements/{workflow_id}", { params: { path: { workflow_id: "wf_nope" } } }))).rejects.toMatchObject({ name: "NotFoundError" });
    await expect(collect(BASE!, "wf_nope")).rejects.toMatchObject({ name: "NotFoundError" });
  });
});
