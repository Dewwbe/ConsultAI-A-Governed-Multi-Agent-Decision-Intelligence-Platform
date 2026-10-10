import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API, fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { renderApp } from "@/test/utils";
import { AGENTS, EXAMPLE_QUESTIONS } from "./content";

const PARTNER = { user: "pat", roles: ["Partner"] };

describe("dashboard overview", () => {
  it("summarises the last 30 days with headline figures", async () => {
    renderApp("/", PARTNER);
    const runs = await screen.findByText("Engagements", { selector: "dt" });
    expect(runs.nextElementSibling).toHaveTextContent(String(fixtures.summary.runs));
    for (const label of ["Success rate", "Awaiting a partner", "Cost per success", "Typical run"]) {
      expect(screen.getByText(label, { selector: "dt" })).toBeInTheDocument();
    }
    expect(screen.getByRole("list", { name: "Engagements by status" })).toBeInTheDocument();
  });

  it("lists every agent in the pipeline with its job, and the spend each one caused", async () => {
    renderApp("/", PARTNER);
    const section = (await screen.findByRole("heading", { name: /agents that work on every engagement/i })).closest("section")!;
    for (const a of AGENTS) expect(within(section).getByText(new RegExp(`\\d+\\. ${a.name}$`))).toBeInTheDocument();
    const spend = await screen.findByRole("list", { name: "Spend by agent" });
    expect(within(spend).getByText("Evaluator")).toBeInTheDocument();
  });

  it("offers example questions that open the form already filled in", async () => {
    renderApp("/", PARTNER);
    const question = EXAMPLE_QUESTIONS.find((q) => q.form.industry === "Logistics")!;
    await userEvent.click(await screen.findByRole("button", { name: new RegExp(question.form.business_problem) }));
    expect(await screen.findByLabelText(/business question/i)).toHaveValue(question.form.business_problem);
    expect(screen.getByLabelText(/industry/i)).toHaveValue("Logistics");
    expect(screen.getByLabelText(/constraints/i)).toHaveValue(question.form.constraints);
  });

  it("says what the platform is and is not for", async () => {
    renderApp("/", PARTNER);
    expect(await screen.findByRole("heading", { name: /works best for/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /not designed for/i })).toBeInTheDocument();
  });

  it("shows recent engagements with their status", async () => {
    renderApp("/", PARTNER);
    const table = await screen.findByRole("table", { name: "Recent engagements" });
    expect(within(table).getAllByRole("row").length).toBe(Math.min(5, fixtures.list.items.length) + 1);
  });

  it("invites the first engagement when there is no history", async () => {
    server.use(http.get(`${API}/metrics/summary`, () => HttpResponse.json({ ...fixtures.summary, runs: 0 })));
    renderApp("/", PARTNER);
    expect(await screen.findByText("No engagements yet")).toBeInTheDocument();
  });
});
