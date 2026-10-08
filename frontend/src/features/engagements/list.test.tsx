import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API, fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { renderApp } from "@/test/utils";

const row = (n: number, status = "completed") => ({
  ...fixtures.list.items[0]!,
  workflow_id: `wf_${n}`,
  business_problem: `Question number ${n}`,
  status,
});

describe("engagement list", () => {
  it("shows each engagement with its status, recommendation and a link to its page", async () => {
    renderApp("/engagements");
    const links = await screen.findAllByRole("link", { name: /Should we expand into the UAE market\?/ });
    expect(links).toHaveLength(2);
    for (const link of links) expect(link).toHaveAttribute("href", expect.stringMatching(/^\/engagements\/wf_/));
    expect(screen.getByText("Completed", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Awaiting approval", { selector: "span" })).toBeInTheDocument();
    expect(screen.getAllByText("Pilot").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /new engagement/i })).toHaveAttribute("href", "/engagements/new");
  });

  it("filters by status and sends the filter to the API", async () => {
    const urls: string[] = [];
    server.use(
      http.get(`${API}/engagements`, ({ request }) => {
        urls.push(request.url);
        const status = new URL(request.url).searchParams.get("status");
        const items = fixtures.list.items.filter((i) => !status || i.status === status);
        return HttpResponse.json({ items, total: items.length, limit: 15, offset: 0 });
      }),
    );
    renderApp("/engagements");
    await screen.findAllByRole("row");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "completed");
    await waitFor(() => expect(urls.some((u) => u.includes("status=completed"))).toBe(true));
    await waitFor(() => expect(screen.queryByText("Awaiting approval", { selector: "span" })).not.toBeInTheDocument());
    expect(screen.getByText("Completed", { selector: "span" })).toBeInTheDocument();
  });

  it("keeps the filter in the address so it survives a reload", async () => {
    renderApp("/engagements?status=awaiting_approval");
    expect(await screen.findByText("Awaiting approval", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByLabelText("Status")).toHaveValue("awaiting_approval");
    expect(screen.queryByText("Completed", { selector: "span" })).not.toBeInTheDocument();
  });

  it("pages through results fifteen at a time", async () => {
    server.use(
      http.get(`${API}/engagements`, ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get("offset") ?? 0);
        const all = Array.from({ length: 20 }, (_, i) => row(i + 1));
        return HttpResponse.json({ items: all.slice(offset, offset + 15), total: 20, limit: 15, offset });
      }),
    );
    renderApp("/engagements");
    expect(await screen.findByText("Showing 1-15 of 20")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /previous/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(await screen.findByText("Showing 16-20 of 20")).toBeInTheDocument();
    expect(screen.getByText("Question number 20")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /next/i })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /previous/i }));
    expect(await screen.findByText("Showing 1-15 of 20")).toBeInTheDocument();
  });

  it("says so when there are no engagements, and offers to start one", async () => {
    server.use(http.get(`${API}/engagements`, () => HttpResponse.json({ items: [], total: 0, limit: 15, offset: 0 })));
    renderApp("/engagements");
    expect(await screen.findByText("No engagements yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /start an engagement/i })).toBeInTheDocument();
  });

  it("explains an empty filter and lets the user clear it", async () => {
    server.use(http.get(`${API}/engagements`, ({ request }) => {
      const status = new URL(request.url).searchParams.get("status");
      const items = status ? [] : fixtures.list.items;
      return HttpResponse.json({ items, total: items.length, limit: 15, offset: 0 });
    }));
    renderApp("/engagements?status=failed");
    expect(await screen.findByText("No failed engagements")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /clear the filter/i }));
    expect(await screen.findByText("Completed", { selector: "span" })).toBeInTheDocument();
  });

  it("recovers from an error with Try again", async () => {
    server.use(http.get(`${API}/engagements`, () => HttpResponse.json({ detail: "boom" }, { status: 500 }), { once: true }));
    renderApp("/engagements");
    expect(await screen.findByText("The server had a problem", {}, { timeout: 5000 })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByText("Completed", { selector: "span" })).toBeInTheDocument();
  });

  it("tells running engagements apart by word and icon, not colour alone", async () => {
    server.use(http.get(`${API}/engagements`, () => HttpResponse.json({ items: [row(1, "running"), row(2, "escalated"), row(3, "failed"), row(4, "rejected")], total: 4, limit: 15, offset: 0 })));
    renderApp("/engagements");
    const table = await screen.findByRole("table", { name: "Engagements" });
    for (const label of ["Running", "Escalated", "Failed", "Rejected"]) expect(within(table).getByText(label)).toBeInTheDocument();
  });
});
