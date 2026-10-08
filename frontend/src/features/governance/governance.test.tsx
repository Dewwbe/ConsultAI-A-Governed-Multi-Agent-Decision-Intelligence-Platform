import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API, fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { renderApp } from "@/test/utils";

const ADMIN = { user: "ada", roles: ["Admin"] };
const open = async (tab: RegExp) => userEvent.click(await screen.findByRole("tab", { name: tab }));

describe("Governance", () => {
  it("is open to Auditors as well as Admins", async () => {
    renderApp("/governance", { user: "aud", roles: ["Auditor"] });
    expect(await screen.findByRole("heading", { level: 1, name: "Governance" })).toBeInTheDocument();
  });

  it("shows the policy in force with each agent's permissions", async () => {
    renderApp("/governance", ADMIN);
    expect(await screen.findByText(fixtures.policy.version, { selector: "strong" })).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "What each agent may do" });
    expect(within(table).getAllByRole("row").length).toBe(fixtures.policy.agents.length + 1);
    expect(screen.getByRole("table", { name: "Permissions by role" })).toHaveTextContent("governance:view");
  });

  it("lists policy versions and shows the text of one on request", async () => {
    renderApp("/governance", ADMIN);
    const table = await screen.findByRole("table", { name: "Policy versions" });
    expect(within(table).getByText("Consistent")).toBeInTheDocument();
    await userEvent.click(within(table).getByRole("button", { name: /view text of/i }));
    expect(await screen.findByLabelText(/^Policy .* text$/)).toHaveTextContent(fixtures.policyVersion.content.slice(0, 20).trim());
  });

  it("flags policy drift in words", async () => {
    server.use(http.get(`${API}/governance/policy/versions`, () => HttpResponse.json(fixtures.policyVersions.map((v) => ({ ...v, drift: true })))));
    renderApp("/governance", ADMIN);
    expect(await screen.findByText("Policy drift detected")).toBeInTheDocument();
    expect(screen.getByText("Drift")).toBeInTheDocument();
  });

  it("shows the tool registry with risk, timeouts and which agents may use each tool", async () => {
    renderApp("/governance", ADMIN);
    await open(/^tools/i);
    const table = await screen.findByRole("table", { name: "Tool registry" });
    expect(within(table).getAllByRole("row").length).toBe(fixtures.tools.length + 1);
    expect(within(table).getByText("calculate_growth")).toBeInTheDocument();
  });

  it("shows provider health, and a tripped breaker with when it will retry", async () => {
    const tripped = structuredClone(fixtures.providers);
    const first = tripped.providers[0]!;
    Object.assign(first.breaker, { state: "open", trips: 2, retry_in_sec: 12.2, last_error: "503 from upstream" });
    server.use(http.get(`${API}/governance/providers`, () => HttpResponse.json(tripped)));
    renderApp("/governance", ADMIN);
    await open(/^providers/i);
    const table = await screen.findByRole("table", { name: "Provider health and limits" });
    expect(within(table).getByText("Tripped")).toBeInTheDocument();
    expect(within(table).getByText(/retry in 13 s/)).toBeInTheDocument();
    expect(within(table).getByText("503 from upstream")).toBeInTheDocument();
    expect(screen.getByText(/No fallbacks/)).toBeInTheDocument();
  });

  it("alerts when a run is near a budget limit", async () => {
    const near = structuredClone(fixtures.budgets);
    near.recent[0] = { ...near.recent[0]!, utilization: 0.92, near_limit: true, tightest: "cost_usd" };
    near.near_limit_count = 1;
    server.use(http.get(`${API}/governance/budgets`, () => HttpResponse.json(near)));
    renderApp("/governance", ADMIN);
    await open(/^budgets/i);
    expect(await screen.findByText("1 run is near a budget limit")).toBeInTheDocument();
    expect(screen.getByText("Near limit")).toBeInTheDocument();
  });

  it("explains the quality level and what it changes", async () => {
    renderApp("/governance", ADMIN);
    await open(/^quality/i);
    expect(await screen.findByText("Current level:")).toBeInTheDocument();
    expect(screen.getByText("Partner review", { selector: "dt" })).toBeInTheDocument();
  });

  it("explains a missing permission instead of showing an empty page", async () => {
    server.use(http.get(`${API}/governance/policy`, () => HttpResponse.json({ detail: "needs governance:view" }, { status: 403 })));
    renderApp("/governance", ADMIN);
    expect(await screen.findByText("Not permitted")).toBeInTheDocument();
  });
});

describe("Phase 6 behaviour elsewhere in the UI", () => {
  it("tells the user when the platform is busy, and for how long", async () => {
    server.use(
      http.post(`${API}/engagements`, () => HttpResponse.json({ detail: "queue full" }, { status: 429, headers: { "Retry-After": "30" } })),
    );
    renderApp("/engagements/new", { user: "ann", roles: ["Analyst"] });
    await userEvent.click(screen.getByRole("button", { name: /use the uae example/i }));
    await userEvent.click(screen.getByRole("button", { name: /start engagement/i }));
    expect(await screen.findByText("The platform is busy")).toBeInTheDocument();
    expect(screen.getByText(/about 30 seconds/)).toBeInTheDocument();
  });

  it("shows a queued engagement as waiting for a slot", async () => {
    server.use(http.get(`${API}/engagements/:id`, ({ params }) => HttpResponse.json({ ...fixtures.detail, workflow_id: params.id, status: "queued" })));
    renderApp("/engagements/wf_q", { user: "ann", roles: ["Analyst"] });
    expect(await screen.findByText(/starts automatically when a slot frees up/)).toBeInTheDocument();
  });
});
