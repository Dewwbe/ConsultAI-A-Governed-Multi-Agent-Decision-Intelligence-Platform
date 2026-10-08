import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API, fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { renderApp } from "@/test/utils";

const ID = fixtures.detail.workflow_id;
const PARTNER = { user: "pat", roles: ["Partner"] };
const run = (id = ID, identity = PARTNER) => renderApp(`/control-center/${id}`, identity);
const open = async (tab: RegExp) => userEvent.click(await screen.findByRole("tab", { name: tab }));

const withFlags = { ...fixtures.summary, flags: [{ metric: "groundedness", value: 0.5, threshold: 0.75, message: "Average groundedness 0.50 is below the policy minimum 0.75" }] };

describe("Control Center overview", () => {
  it("summarises quality, cost and safety across runs", async () => {
    renderApp("/control-center", PARTNER);
    expect(await screen.findByRole("heading", { level: 1, name: "Control Center" })).toBeInTheDocument();
    const s = fixtures.summary;
    expect(await screen.findByText("Cost per successful task")).toBeInTheDocument();
    expect(screen.getByText("Runs", { selector: "dt" }).nextElementSibling).toHaveTextContent(String(s.runs));
    for (const label of ["Success rate", "Escalation rate", "Median decision time", "Typical run time"]) expect(screen.getByText(label, { selector: "dt" })).toBeInTheDocument();
    for (const heading of ["Tools and models", "Safety", "Understanding the task"]) expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    expect(screen.getByText(`Policy ${s.policy_version}`)).toBeInTheDocument();
  });

  it("charts quality over time with a legend, and offers the same data as a table", async () => {
    renderApp("/control-center", PARTNER);
    const card = (await screen.findByRole("heading", { name: "Quality over time" })).closest("div[class*=rounded-lg]") as HTMLElement;
    expect(within(card).getByRole("list", { name: "Legend" })).toHaveTextContent("Contradiction free");
    expect(within(card).getByRole("img", { name: /Groundedness, Tool accuracy, Contradiction free over time/ })).toBeInTheDocument();
    await userEvent.click(within(card).getByRole("button", { name: "View as table" }));
    const table = within(card).getByRole("table", { name: "Quality over time" });
    expect(within(table).getAllByRole("columnheader").map((c) => c.textContent)).toEqual(["Period", "Groundedness", "Tool accuracy", "Contradiction free"]);
    expect(within(table).getAllByRole("row").length).toBeGreaterThan(1);
  });

  it("warns, in words, when a metric has slipped below policy", async () => {
    server.use(http.get(`${API}/metrics/summary`, () => HttpResponse.json(withFlags)));
    renderApp("/control-center", PARTNER);
    const alert = (await screen.findByText("Quality is below policy")).closest("[role=alert]")!;
    expect(alert).toHaveTextContent("Average groundedness 0.50 is below the policy minimum 0.75");
  });

  it("reports the real recorded run's constraint miss (the infeasible-budget case) as a flag", async () => {
    renderApp("/control-center", PARTNER);
    expect(await screen.findByText(/Average constraint satisfaction 0\.67 is below the policy minimum 0\.90/)).toBeInTheDocument();
  });

  it("shows no warning when everything meets policy", async () => {
    server.use(http.get(`${API}/metrics/summary`, () => HttpResponse.json({ ...fixtures.summary, flags: [] })));
    renderApp("/control-center", PARTNER);
    await screen.findByText("Cost per successful task");
    expect(screen.queryByText("Quality is below policy")).not.toBeInTheDocument();
  });

  it("changes the time window and asks the API for it", async () => {
    const seen: (string | null)[] = [];
    server.use(
      http.get(`${API}/metrics/summary`, ({ request }) => {
        seen.push(new URL(request.url).searchParams.get("since"));
        return HttpResponse.json(fixtures.summary);
      }),
    );
    renderApp("/control-center", PARTNER);
    await screen.findByText("Cost per successful task");
    expect(seen[0]).toMatch(/^\d{4}-\d\d-\d\dT\d\d:00:00\.000Z$/); // default: last 7 days, on an hour boundary
    await userEvent.selectOptions(screen.getByLabelText("Window"), "all");
    await waitFor(() => expect(seen).toContain(null)); // "all time" sends no start
  });

  it("says so when the window has no runs", async () => {
    server.use(http.get(`${API}/metrics/summary`, () => HttpResponse.json({ ...fixtures.summary, runs: 0, by_status: {}, flags: [] })));
    renderApp("/control-center", PARTNER);
    expect(await screen.findByText("No runs in this window")).toBeInTheDocument();
  });

  it("recovers from an error with Try again", async () => {
    server.use(http.get(`${API}/metrics/summary`, () => HttpResponse.json({ detail: "boom" }, { status: 500 }), { once: true }));
    renderApp("/control-center", PARTNER);
    expect(await screen.findByText("The server had a problem", {}, { timeout: 6000 })).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /try again/i })[0]!);
    expect(await screen.findByText("Cost per successful task")).toBeInTheDocument();
  });

  it("links every recent run to its inspector", async () => {
    renderApp("/control-center", PARTNER);
    const table = await screen.findByRole("table", { name: "Recent runs" });
    const links = within(table).getAllByRole("link");
    expect(links).toHaveLength(fixtures.list.items.length);
    expect(links[0]).toHaveAttribute("href", expect.stringMatching(/^\/control-center\/wf_/));
  });
});

describe("run inspector: one screen for a reviewer", () => {
  it("shows agents, evidence, tool calls, cost, latency, scores and why approval was triggered", async () => {
    run();
    expect(await screen.findByRole("heading", { level: 1, name: "Should we expand into the UAE market?" })).toBeInTheDocument();
    expect(await screen.findByText("Why a human was (or was not) needed")).toBeInTheDocument();
    expect(screen.getByText(/client-facing recommendation is a high-risk action/)).toBeInTheDocument();
    for (const title of ["Agents and how long each took", "Evidence retrieved", "Scores against policy", "Cost by agent"]) {
      expect(screen.getByText(title)).toBeInTheDocument();
    }
    expect(screen.getAllByText("Tool calls").length).toBeGreaterThanOrEqual(2); // the stat, the card and the tab
    expect(screen.getByText(/verified claims from \d+ sources/)).toBeInTheDocument();
    expect(await screen.findAllByText("meets minimum")).toHaveLength(4); // groundedness, constraints, adherence, tool accuracy
    expect(screen.getByRole("list", { name: "Time per agent" })).toHaveTextContent("financial_agent");
  });

  it("links back to the engagement and the overview", async () => {
    run();
    await screen.findByRole("heading", { level: 1 });
    expect(screen.getByRole("link", { name: /open the engagement/i })).toHaveAttribute("href", `/engagements/${ID}`);
    expect(within(screen.getByRole("main")).getByRole("link", { name: /control center/i })).toHaveAttribute("href", "/control-center");
  });

  it("explains a missing run", async () => {
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json({ detail: "engagement not found" }, { status: 404 })));
    run("wf_missing");
    expect(await screen.findByText("Not found")).toBeInTheDocument();
  });
});

describe("trace explorer", () => {
  it("lists every span with its kind, and inspects one on click", async () => {
    run();
    await open(/^Trace/);
    const list = await screen.findByRole("list", { name: "Spans" });
    expect(within(list).getAllByRole("button")).toHaveLength(fixtures.trace.spans.length);
    await userEvent.click(within(list).getByRole("button", { name: /^financial_agent/ }));
    const detail = await screen.findByRole("region", { name: "Details of financial_agent" });
    expect(detail).toHaveTextContent("Agent");
    expect(detail).toHaveTextContent("Status");
  });

  it("shows model calls with tokens, cost, model tier and the prompt used", async () => {
    run();
    await open(/^Trace/);
    const list = await screen.findByRole("list", { name: "Spans" });
    await userEvent.click(within(list).getAllByRole("button", { name: /^llm:financial/ })[0]!);
    const detail = await screen.findByRole("region", { name: /Details of llm:financial/ });
    expect(detail).toHaveTextContent(/Tokens\s*\d+ in, \d+ out/);
    expect(detail).toHaveTextContent("financial_cases@v3");
    expect(detail).toHaveTextContent("MODEL_REASONING (reasoning)");
  });

  it("filters spans by kind", async () => {
    run();
    await open(/^Trace/);
    const list = await screen.findByRole("list", { name: "Spans" });
    const before = within(list).getAllByRole("button").length;
    await userEvent.click(screen.getByRole("checkbox", { name: /Model call/ }));
    expect(within(list).getAllByRole("button").length).toBeLessThan(before);
    expect(within(list).queryAllByRole("button", { name: /^llm:/ })).toHaveLength(0);
  });

  it("explains when payloads are hidden from the viewer, but still shows structure", async () => {
    const hidden = {
      ...fixtures.trace,
      redaction: { payloads_redacted: true, pii_scrubbed: 2, reason: "confidential engagement: payloads need the owner, Partner or Admin role" },
      spans: fixtures.trace.spans.map((s) => ({
        ...s,
        attributes: Object.fromEntries(Object.entries(s.attributes).map(([k, v]) => [k, ["consultai.tool_arguments", "consultai.tool_result", "consultai.sql"].includes(k) ? "[redacted: needs the owner, Partner or Admin role]" : v])),
      })),
    };
    server.use(http.get(`${API}/control-center/:id/trace`, () => HttpResponse.json(hidden)));
    run(ID, { user: "ann", roles: ["Analyst"] });
    await open(/^Trace/);
    expect(await screen.findByText("Some detail is hidden from you")).toBeInTheDocument();
    expect(screen.getByText(/2 personal identifiers or secrets were masked/)).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "Spans" });
    await userEvent.click(within(list).getAllByRole("button", { name: /^tool:calculate_roi/ })[0]!);
    const detail = await screen.findByRole("region", { name: /Details of tool:calculate_roi/ });
    expect(detail).toHaveTextContent("hidden for your role");
    expect(detail).not.toHaveTextContent('"investment"');
  });

  it("shows an error span's message", async () => {
    const failing = { ...fixtures.trace, spans: [{ ...fixtures.trace.spans[0]!, status: "error", error: "SchemaEscalation('no valid case')" }] };
    server.use(http.get(`${API}/control-center/:id/trace`, () => HttpResponse.json(failing)));
    run();
    await open(/^Trace/);
    await userEvent.click(await screen.findByRole("button", { name: new RegExp(`^${failing.spans[0]!.name}`) }));
    expect(await screen.findByText(/SchemaEscalation/)).toBeInTheDocument();
    expect(screen.getByText(/1 failed/)).toBeInTheDocument();
  });
});

describe("tool-call inspector", () => {
  it("lists tool calls with their outcome and opens arguments, result and the Guardian's decision", async () => {
    run();
    await open(/^Tool calls/);
    const table = await screen.findByRole("table", { name: "Tool calls" });
    expect(within(table).getAllByText("Succeeded").length).toBeGreaterThan(3);
    await userEvent.click(within(table).getAllByRole("button", { name: "calculate_roi" })[0]!);
    const inspector = await screen.findByRole("region", { name: /Inspector for tool:calculate_roi/ });
    expect(inspector).toHaveTextContent("Guardian decision for this call");
    expect(inspector).toHaveTextContent("ALLOW");
    expect(inspector).toHaveTextContent(/policy 2026\.\d+\.\d+/);
    expect(inspector).toHaveTextContent('"investment"');
    expect(inspector).toHaveTextContent('"roi"');
    expect(inspector).toHaveTextContent("1 attempt");
  });

  const blocked = {
    ...fixtures.trace,
    spans: [
      { ...fixtures.trace.spans[0]!, span_id: "t1", kind: "tool", name: "tool:send_client_email", status: "error", error: "ToolBlocked('blocked')", attributes: {
        "gen_ai.tool.name": "send_client_email", "gen_ai.agent.name": "research_agent", "consultai.outcome": "blocked",
        "consultai.tool_arguments": { to: "client" }, "consultai.guardian": { action: "BLOCK", risk_level: "high", risk_score: 1, subject: "research_agent.send_client_email", reasons: ["tool is blocked for this agent"], policy_version: "2026.10.3" } } },
      { ...fixtures.trace.spans[0]!, span_id: "t2", kind: "tool", name: "tool:calculate_roi", status: "error", error: "ToolArgsInvalid", attributes: {
        "gen_ai.tool.name": "calculate_roi", "gen_ai.agent.name": "financial_agent", "consultai.outcome": "invalid_arguments",
        "consultai.schema_errors": ["-5 is less than or equal to the minimum of 0"], "consultai.tool_arguments": { investment: -5 },
        "consultai.guardian": { action: "ALLOW", risk_level: "low", risk_score: 0.1, subject: "financial_agent.calculate_roi", reasons: ["allowed"], policy_version: "2026.10.3" } } },
      { ...fixtures.trace.spans[0]!, span_id: "t3", kind: "tool", name: "tool:flaky", status: "ok", error: null, attributes: {
        "gen_ai.tool.name": "flaky", "consultai.outcome": "ok", "consultai.attempts": 2, "consultai.tool_arguments": {}, "consultai.tool_result": { ok: true } } },
    ],
  };

  it("makes refusals visible: blocked by the Guardian, invalid arguments with the schema errors, and retries", async () => {
    server.use(http.get(`${API}/control-center/:id/trace`, () => HttpResponse.json(blocked)));
    run();
    await open(/^Tool calls/);
    const table = await screen.findByRole("table", { name: "Tool calls" });
    expect(within(table).getByText("Blocked by Guardian")).toBeInTheDocument();
    expect(within(table).getByText("Invalid arguments")).toBeInTheDocument();

    await userEvent.click(within(table).getByRole("button", { name: "send_client_email" }));
    expect(await screen.findByText("tool is blocked for this agent")).toBeInTheDocument();
    expect(screen.getByText("BLOCK")).toBeInTheDocument();

    await userEvent.click(within(table).getByRole("button", { name: "calculate_roi" }));
    expect(await screen.findByText("Schema validation errors")).toBeInTheDocument();
    expect(screen.getByText(/less than or equal to the minimum/)).toBeInTheDocument();

    await userEvent.click(within(table).getByRole("button", { name: "flaky" }));
    expect(await screen.findByText(/2 attempts \(the first failed with a transient error and was retried\)/)).toBeInTheDocument();
  });
});

describe("retrieval inspector", () => {
  it("shows the query, filters, passages with their scores, and the models used", async () => {
    run();
    await open(/^Retrievals/);
    const list = await screen.findByRole("list", { name: "Retrievals" });
    const first = within(list).getAllByRole("listitem")[0]!;
    expect(first).toHaveTextContent("Search 1");
    expect(first).toHaveTextContent("Embedding model");
    expect(first).toHaveTextContent(/hashing-\d+-v1/);
    expect(first).toHaveTextContent("Max classification: confidential");
    expect(first).toHaveTextContent("synthetic://");
    expect(within(first).getByRole("list", { name: /Relevance of the passages/ })).toBeInTheDocument();
    expect(first).toHaveTextContent(/SYNTHETIC DEMO DATA/); // the passage text itself: "what did the agent actually see?"
  });

  it("hides passage text and query for a viewer who may not see payloads, but keeps ids, sources and scores", async () => {
    const redacted = {
      ...fixtures.trace,
      spans: fixtures.trace.spans.map((s) => {
        if (s.kind !== "retrieval") return s;
        const r = s.attributes["consultai.retrieval"] as { documents: Record<string, unknown>[] };
        return { ...s, attributes: { ...s.attributes, "consultai.query": "[redacted: needs the owner, Partner or Admin role]",
          "consultai.retrieval": { retrieval_id: "r", index: "local", embedding_model: "hashing-256-v1", index_version: "v", k: 2, redacted: true,
            documents: r.documents.map(({ doc_id, chunk_id, source, score }) => ({ doc_id, chunk_id, source, score })) } } };
      }),
    };
    server.use(http.get(`${API}/control-center/:id/trace`, () => HttpResponse.json(redacted)));
    run(ID, { user: "ann", roles: ["Analyst"] });
    await open(/^Retrievals/);
    const first = within(await screen.findByRole("list", { name: "Retrievals" })).getAllByRole("listitem")[0]!;
    expect(first).toHaveTextContent("The query text is hidden for your role");
    expect(first).toHaveTextContent("Passage text hidden for your role");
    expect(first).not.toHaveTextContent("SYNTHETIC DEMO DATA");
    expect(first).toHaveTextContent("synthetic://");
  });
});

describe("Guardian log", () => {
  it("shows recommendation-level decisions with reasons and the policy version, and why approval was triggered", async () => {
    run();
    await open(/^Guardian/);
    expect(await screen.findByText("Why approval was triggered")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Guardian decisions" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.length).toBeGreaterThan(0);
    expect(within(table).getByText("Recommendation")).toBeInTheDocument();
    expect(within(table).getByText("ESCALATE")).toBeInTheDocument();
    expect(table).toHaveTextContent(/2026\.\d+\.\d+/);
    expect(table).toHaveTextContent("client-facing recommendation is a high-risk action");
  });

  it("can include every per-tool decision too", async () => {
    run();
    await open(/^Guardian/);
    const table = await screen.findByRole("table", { name: "Guardian decisions" });
    const workflowOnly = within(table).getAllByRole("row").length;
    await userEvent.click(screen.getByRole("checkbox", { name: /recommendation-level decisions only/i }));
    expect(within(screen.getByRole("table", { name: "Guardian decisions" })).getAllByRole("row").length).toBeGreaterThan(workflowOnly);
    expect(screen.getByRole("table", { name: "Guardian decisions" })).toHaveTextContent(/financial_agent\.calculate_roi/);
  });

  it("shows retry feedback and the layer that made a decision", async () => {
    server.use(http.get(`${API}/engagements/:id/guardian`, () => HttpResponse.json([
      { action: "RETRY", risk_level: "medium", risk_score: 0.5, reasons: ["rationale contradicts the ROI"], subject: "workflow", source: "deterministic", feedback: "fix the ROI figure", policy_version: "2026.10.3" },
      { action: "ESCALATE", risk_level: "high", risk_score: 0.9, reasons: ["reviewer: partner should look"], subject: "workflow", source: "combined", policy_version: "2026.10.3" },
    ])));
    run();
    await open(/^Guardian/);
    expect(await screen.findByText("Feedback: fix the ROI figure")).toBeInTheDocument();
    expect(screen.getByText("Combined")).toBeInTheDocument();
  });

  it("says so when there are none yet", async () => {
    server.use(http.get(`${API}/engagements/:id/guardian`, () => HttpResponse.json([])));
    run();
    await open(/^Guardian/);
    expect(await screen.findByText("No Guardian decisions yet")).toBeInTheDocument();
  });
});

describe("cost and quality", () => {
  it("breaks cost down by agent and model, shows cost per successful task and budget use with meters", async () => {
    run();
    await open(/^Cost/);
    expect(await screen.findByText("Estimated cost")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Cost by agent" })).toHaveTextContent("financial_agent");
    expect(screen.getByRole("list", { name: "Cost by model" })).toHaveTextContent(/reasoning \(MODEL_REASONING\)/);
    expect(screen.getByText("Not successful")).toBeInTheDocument(); // not yet approved: success needs the whole outcome
    for (const name of ["Cost", "Tokens", "Tool calls", "Time"]) expect(screen.getByRole("meter", { name })).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Cost" })).toHaveAttribute("aria-valuetext", expect.stringMatching(/within budget/));
  });

  it("shows a successful run's cost per successful task", async () => {
    server.use(http.get(`${API}/engagements/:id/cost`, () => HttpResponse.json({ ...fixtures.cost, successful: true, cost_per_successful_task: fixtures.cost.total_cost_usd })));
    run();
    await open(/^Cost/);
    expect(await screen.findByText("Successful")).toBeInTheDocument();
    expect(screen.getByText("This run succeeded")).toBeInTheDocument();
  });

  it("warns when a run is near or over a budget", async () => {
    const tight = { ...fixtures.cost, budget: { ...fixtures.cost.budget, cost_usd: { used: 2.4, limit: 2 } } };
    server.use(http.get(`${API}/engagements/:id/cost`, () => HttpResponse.json(tight)));
    run();
    await open(/^Cost/);
    expect(await screen.findByRole("meter", { name: "Cost" })).toHaveAttribute("aria-valuetext", expect.stringMatching(/over budget/));
  });

  it("quality: every score beside its policy minimum, with below-minimum called out in words", async () => {
    const low = { ...fixtures.detail, state: { ...fixtures.detail.state, evaluation_scores: { ...fixtures.detail.state.evaluation_scores, groundedness: 0.5 } } };
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json(low)));
    run();
    await open(/^Quality/);
    const list = await screen.findByRole("list", { name: "Evaluation scores" });
    expect(await within(list).findByText(/below minimum 0\.75/)).toBeInTheDocument();
    expect(within(list).getAllByText(/meets/).length).toBeGreaterThan(0);
    expect(screen.getByText(/policy 2026\.\d+\.\d+/)).toBeInTheDocument();
  });

  it("quality: lists what the evaluators noticed", async () => {
    const noted = { ...fixtures.detail, state: { ...fixtures.detail.state, failures: [{ type: "eval_issue", issue: "contradiction (medium, judge): rationale cites an unsupported margin" }] } };
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json(noted)));
    run();
    await open(/^Quality/);
    expect(await screen.findByText(/rationale cites an unsupported margin/)).toBeInTheDocument();
  });
});
