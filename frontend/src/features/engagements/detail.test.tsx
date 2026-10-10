import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API, fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { renderApp } from "@/test/utils";

const AWAITING = fixtures.detail.workflow_id;
const COMPLETED = fixtures.completed.workflow_id;
const open = (id = AWAITING) => renderApp(`/engagements/${id}`);

async function tab(name: string) {
  await userEvent.click(await screen.findByRole("tab", { name: new RegExp(name, "i") }));
}

describe("engagement detail: header and pipeline", () => {
  it("shows the question, status, risk level and id", async () => {
    open();
    expect(await screen.findByRole("heading", { level: 1, name: "Should we expand into the UAE market?" })).toBeInTheDocument();
    expect(screen.getByText("Awaiting approval", { selector: "span" })).toBeInTheDocument();
    expect(screen.getAllByText("high risk").length).toBeGreaterThan(0);
    expect(screen.getByText(AWAITING)).toBeInTheDocument();
  });

  it("follows the run to the approval pause, with every step accounted for", async () => {
    open();
    const pipeline = await screen.findByRole("list", { name: "Pipeline progress" });
    await waitFor(() => expect(within(pipeline).getByText(/waiting for a partner/i)).toBeInTheDocument());
    for (const step of ["Discovery", "Research", "Data", "Financial", "Risk", "Solution", "Evaluation", "Guardian"]) {
      const item = within(pipeline).getByText(step).closest("li")!;
      expect(item).toHaveTextContent("Done");
    }
    expect(within(pipeline).getByText("Approval").closest("li")).toHaveAttribute("aria-current", "step");
    expect(within(pipeline).getByText("Report").closest("li")).toHaveTextContent("Pending");
    // a paused run closes its stream: the page says it is current rather than leaving the badge blank
    expect(await screen.findByText("Up to date")).toBeInTheDocument();
  });

  it("explains why approval is needed and links to the review screen", async () => {
    open();
    const notice = await screen.findByText("Waiting for a partner's decision");
    const alert = notice.closest("[role=alert]")!;
    expect(alert).toHaveTextContent(/high-risk action/i);
    expect(within(alert as HTMLElement).getByRole("link", { name: /review and decide/i })).toHaveAttribute("href", `/engagements/${AWAITING}/review`);
  });

  it("shows a typed not-found error for an engagement that does not exist", async () => {
    open("wf_missing");
    expect(await screen.findByText("Not found")).toBeInTheDocument();
    expect(within(screen.getByRole("main")).getByRole("link", { name: /engagements/i })).toHaveAttribute("href", "/engagements");
  });
});

describe("engagement detail: result panels", () => {
  it("summary: recommendation, assumptions, scores and Guardian reasons", async () => {
    open();
    expect(await screen.findByText("Recommendation: Pilot")).toBeInTheDocument();
    expect(screen.getByText("Option B")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Assumptions" })).toBeInTheDocument();
    expect(screen.getByText(/operating margin, from the data warehouse/)).toBeInTheDocument();
    for (const label of ["Groundedness", "Constraint satisfaction", "Task adherence", "Tool call accuracy"]) expect(screen.getByText(label)).toBeInTheDocument();
    expect(screen.getByText("ESCALATE")).toBeInTheDocument();
    expect(screen.getAllByText(/client-facing recommendation is a high-risk action/).length).toBeGreaterThan(0);
  });

  it("specification: question, constraints kept verbatim, analyses and data", async () => {
    open();
    await tab("Specification");
    expect(await screen.findByRole("heading", { name: "Decision question" })).toBeInTheDocument();
    expect(screen.getByText("Budget under $10M")).toBeInTheDocument();
    expect(screen.getByText("Launch within 18 months")).toBeInTheDocument();
    expect(screen.getByText("Market size")).toBeInTheDocument();
  });

  it("evidence: every claim shows its quote, source and verification", async () => {
    open();
    await tab("Evidence");
    const claims = await screen.findAllByText("Quote verified");
    expect(claims).toHaveLength(fixtures.evidence.claims.length);
    expect(screen.getByText(/Claims \(7\)/)).toBeInTheDocument();
    expect(screen.getAllByText(/synthetic:\/\//).length).toBeGreaterThan(0);
    expect(screen.getByRole("table", { name: /sources and how many claims/i })).toBeInTheDocument();
  });

  it("evidence: a stored retrieval can be replayed to confirm what the agent saw", async () => {
    open();
    await tab("Evidence");
    const replay = (await screen.findAllByRole("button", { name: /replay/i }))[0]!;
    await userEvent.click(replay);
    expect(await screen.findByText(/Reproduced exactly \(2 passages\)/)).toBeInTheDocument();
  });

  it("evidence: dropped claims are reported, not hidden", async () => {
    server.use(http.get(`${API}/engagements/:id/evidence`, () =>
      HttpResponse.json({ ...fixtures.evidence, rejected_claims: [{ reason: "unverified_citation", doc_ref: "D3", chunk_id: "c" }] })));
    open();
    await tab("Evidence");
    const alert = (await screen.findByText("1 claim was dropped")).closest("[role=alert]")!;
    expect(alert).toHaveTextContent("D3: the quote was not found in the cited source");
  });

  it("data: tables with their catalog meaning, and the read-only SQL that ran", async () => {
    open();
    await tab("Data");
    expect(await screen.findByText("finance.revenue")).toBeInTheDocument();
    expect(screen.getByText("finance.costs")).toBeInTheDocument();
    expect(screen.getAllByText(/owner: finance/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/SELECT/).length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText("baseline revenue")).toBeInTheDocument();
  });

  it("financials: baseline, cases, scenarios and sensitivity, with the recommended case marked", async () => {
    open();
    await tab("Financials");
    expect(await screen.findByText(/operating margin, from the data warehouse/)).toBeInTheDocument();
    const cases = screen.getByRole("table", { name: /financial cases/i });
    expect(within(cases).getAllByRole("row")).toHaveLength(4); // header + A, B, C
    expect(within(cases).getByText("Recommended").closest("tr")).toHaveTextContent("Pilot");
    expect(screen.getByRole("table", { name: /roi by scenario/i })).toHaveTextContent("Conservative");
    expect(screen.getByRole("table", { name: /roi sensitivity/i })).toHaveTextContent("-20%");
    expect(screen.getByRole("heading", { name: "Why each uplift" })).toBeInTheDocument();
  });

  it("risks: sorted by score with a level word and icon, and the mitigation", async () => {
    open();
    await tab("Risks");
    const table = await screen.findByRole("table", { name: /risks with probability/i });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.length).toBe(fixtures.detail.state.risks.length);
    const scores = rows.map((r) => Number(/(\d\.\d\d)$/.exec(within(r).getAllByText(/·/)[0]!.textContent!)?.[1]));
    expect([...scores].sort((a, b) => b - a)).toEqual(scores);
    expect(table).toHaveTextContent(/High|Medium|Low/);
    expect(table).toHaveTextContent("Engage local counsel early");
  });

  it("options: side by side, the recommendation marked, constraint compliance spelled out", async () => {
    open();
    await tab("Options");
    const table = await screen.findByRole("table", { name: /options compared/i });
    expect(within(table).getAllByText("Within constraints")).toHaveLength(3);
    expect(within(table).getByText("Recommended").closest("tr")).toHaveTextContent("Pilot");
  });

  it("options: a violated constraint is stated, with the reason", async () => {
    const options = fixtures.detail.state.options.map((o, i) => (i === 0 ? { ...o, within_constraints: false, constraint_violations: ["investment $8,000,000 exceeds ceiling $2,500,000"] } : o));
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json({ ...fixtures.detail, state: { ...fixtures.detail.state, options } })));
    open();
    await tab("Options");
    expect(await screen.findByText("Breaks constraints")).toBeInTheDocument();
    expect(screen.getByText(/exceeds ceiling \$2,500,000/)).toBeInTheDocument();
  });

  it("report: explains why there is none while approval is pending", async () => {
    open();
    await tab("Report");
    expect(await screen.findByText("No report yet")).toBeInTheDocument();
    expect(screen.getByText(/written after a partner approves/i)).toBeInTheDocument();
  });

  it("report: renders the markdown once the engagement completed", async () => {
    open(COMPLETED);
    expect(await screen.findByText("Completed", { selector: "span" })).toBeInTheDocument();
    await tab("Report");
    // each part of the report is its own titled section
    for (const name of ["1. Recommendation", "2. Partner decision", "3. Options considered", "4. Key risks", "5. Assumptions", "6. Quality checks", "Report text"]) {
      expect(await screen.findByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.getByText("Approved", { selector: "span" })).toBeInTheDocument();
    const options = screen.getByRole("table", { name: "Options considered" });
    expect(within(options).getByText("Recommended").closest("tr")).toHaveTextContent("Pilot");
    expect(screen.getByText("Return on investment", { selector: "dt" }).nextElementSibling).toHaveTextContent("75%");
    // and the text version is folded away below, for download or pasting
    await userEvent.click(screen.getByRole("button", { name: "Show the full text" }));
    expect(await screen.findByRole("heading", { name: /Engagement Report: Should we expand into the UAE market\?/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /download/i })).toBeInTheDocument();
  });

  it("report: markdown cannot inject HTML", async () => {
    const evil = { ...fixtures.completed, state: { ...fixtures.completed.state, report: { markdown: "# Title\n\n<img src=x onerror=alert(1)>\n\n<script>alert(2)</script>" } } };
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json(evil)));
    const { container } = open(COMPLETED);
    await tab("Report");
    await userEvent.click(await screen.findByRole("button", { name: "Show the full text" }));
    await screen.findByRole("heading", { name: "Title" });
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });
});

describe("engagement detail: states other than a clean pause", () => {
  it("escalated: says it stopped for investigation, with the reason", async () => {
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json({ ...fixtures.detail, status: "escalated", halted_reason: "financial_agent: no valid investment case was proposed" })));
    open();
    const notice = await screen.findByText("Stopped for human investigation");
    expect(notice.closest("[role=alert]")).toHaveTextContent("no valid investment case was proposed");
  });

  it("failed: shows the error", async () => {
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json({ ...fixtures.detail, status: "failed", error: "ValueError: graph exploded" })));
    open();
    expect(await screen.findByText("The run failed")).toBeInTheDocument();
    expect(screen.getByText("ValueError: graph exploded")).toBeInTheDocument();
  });

  it("rejected: says no report was produced", async () => {
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json({ ...fixtures.detail, status: "rejected" })));
    open();
    expect(await screen.findByText("Rejected by a partner")).toBeInTheDocument();
  });

  it("while running, panels wait for data instead of showing empty results", async () => {
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json({ ...fixtures.detail, status: "running", state: { business_problem: "Should we expand into the UAE market?" }, guardian_decisions: [] })));
    open();
    await screen.findByRole("heading", { level: 1, name: /expand into the UAE/ });
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(screen.queryByText("No recommendation")).not.toBeInTheDocument();
  });
});
