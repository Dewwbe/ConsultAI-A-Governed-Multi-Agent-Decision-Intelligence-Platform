import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { configureAxe } from "vitest-axe";
import { describe, expect, it } from "vitest";
import { fixtures } from "@/mocks/handlers";
import { renderApp } from "@/test/utils";

// jsdom has no layout, so colour contrast is checked separately (the palette is validated against its surfaces).
const axe = configureAxe({ rules: { "color-contrast": { enabled: false } } });

const ADMIN = { user: "ada", roles: ["Admin", "Partner"] };
const ID = fixtures.detail.workflow_id;

async function violations(container: HTMLElement) {
  const result = await axe(container);
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(" ")).join(", ")})`);
}

describe("accessibility (axe)", () => {
  it("dashboard", async () => {
    const { container } = renderApp("/", ADMIN);
    await screen.findByRole("heading", { level: 1 });
    expect(await violations(container)).toEqual([]);
  });

  it("engagement list", async () => {
    const { container } = renderApp("/engagements", ADMIN);
    await screen.findByRole("table");
    expect(await violations(container)).toEqual([]);
  });

  it("new engagement form, including its error summary", async () => {
    const { container } = renderApp("/engagements/new", ADMIN);
    await userEvent.click(await screen.findByRole("button", { name: /start engagement/i }));
    await screen.findByRole("alert");
    expect(await violations(container)).toEqual([]);
  });

  it("engagement detail", async () => {
    const { container } = renderApp(`/engagements/${ID}`, ADMIN);
    await screen.findByRole("tab", { name: /evidence/i });
    expect(await violations(container)).toEqual([]);
  });

  it("approval review", async () => {
    const { container } = renderApp(`/engagements/${ID}/review`, ADMIN);
    await screen.findByRole("heading", { level: 1 });
    expect(await violations(container)).toEqual([]);
  });

  it("control center overview", async () => {
    const { container } = renderApp("/control-center", ADMIN);
    await screen.findByText("Cost per successful task");
    expect(await violations(container)).toEqual([]);
  });

  it("control center run", async () => {
    const { container } = renderApp(`/control-center/${ID}`, ADMIN);
    await screen.findByRole("tab", { name: /trace/i });
    expect(await violations(container)).toEqual([]);
  });

  it.each(["policy", "tools", "providers", "budgets", "quality"])("governance: %s", async (tab) => {
    const { container } = renderApp("/governance", ADMIN);
    await userEvent.click(await screen.findByRole("tab", { name: new RegExp(`^${tab}`, "i") }));
    await waitFor(() => expect(screen.queryByText(/^Loading/)).not.toBeInTheDocument());
    expect(await violations(container)).toEqual([]);
  });
});
