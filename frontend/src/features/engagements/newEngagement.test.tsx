import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API, fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { renderApp } from "@/test/utils";

const FORM = "/engagements/new";

function captureCreate() {
  const seen: { query: string; body: Record<string, unknown> }[] = [];
  server.use(
    http.post(`${API}/engagements`, async ({ request }) => {
      seen.push({ query: new URL(request.url).search, body: (await request.json()) as Record<string, unknown> });
      return HttpResponse.json({ ...fixtures.detail, workflow_id: "wf_new", status: "running", state: { business_problem: "Should we expand into the UAE market?" } });
    }),
  );
  return seen;
}

describe("new engagement form", () => {
  it("rejects an empty question with a summary that takes focus and links to the field", async () => {
    renderApp(FORM);
    await userEvent.click(screen.getByRole("button", { name: /start engagement/i }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Describe the business question.");
    await waitFor(() => expect(alert).toHaveFocus());
    expect(screen.getByLabelText(/business question/i)).toHaveAttribute("aria-invalid", "true");
    expect(within(alert).getByRole("link", { name: /describe the business question/i })).toHaveAttribute("href", "#business_problem");
  });

  it("clears a field's error as soon as the user edits it", async () => {
    renderApp(FORM);
    await userEvent.click(screen.getByRole("button", { name: /start engagement/i }));
    await screen.findByRole("alert");
    await userEvent.type(screen.getByLabelText(/business question/i), "Should we expand?");
    expect(screen.getByLabelText(/business question/i)).toHaveAttribute("aria-invalid", "false");
  });

  it("enforces the API's minimum length and list size client-side, without calling the API", async () => {
    const seen = captureCreate();
    renderApp(FORM);
    await userEvent.type(screen.getByLabelText(/business question/i), "abc");
    await userEvent.click(screen.getByRole("button", { name: /start engagement/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least 5 characters");
    expect(seen).toHaveLength(0);
  });

  it("fills the UAE example and starts the engagement in the background", async () => {
    const seen = captureCreate();
    renderApp(FORM);
    await userEvent.click(screen.getByRole("button", { name: /use the uae example/i }));
    expect(screen.getByLabelText(/business question/i)).toHaveValue("Should we expand into the UAE market?");
    expect(screen.getByLabelText(/constraints/i)).toHaveValue("Budget under $10M\nLaunch within 18 months");

    await userEvent.click(screen.getByRole("button", { name: /start engagement/i }));
    await waitFor(() => expect(seen).toHaveLength(1));
    expect(seen[0]?.query).toBe("?wait=false"); // returns at once; progress arrives over the stream
    expect(seen[0]?.body).toEqual({
      business_problem: "Should we expand into the UAE market?",
      industry: "Retail",
      objectives: ["Increase revenue"],
      constraints: ["Budget under $10M", "Launch within 18 months"],
      data_classification: "confidential",
    });
    // lands on the new engagement's page
    expect(await screen.findByText("wf_new")).toBeInTheDocument();
  });

  it("sends the chosen data classification", async () => {
    const seen = captureCreate();
    renderApp(FORM);
    await userEvent.type(screen.getByLabelText(/business question/i), "Is the market public?");
    await userEvent.click(screen.getByRole("radio", { name: /public/i }));
    await userEvent.click(screen.getByRole("button", { name: /start engagement/i }));
    await waitFor(() => expect(seen[0]?.body.data_classification).toBe("public"));
  });

  it("puts a server-side validation message next to its field", async () => {
    server.use(
      http.post(`${API}/engagements`, () =>
        HttpResponse.json({ detail: [{ loc: ["body", "industry"], msg: "String should have at most 200 characters" }] }, { status: 422 }),
      ),
    );
    renderApp(FORM);
    await userEvent.type(screen.getByLabelText(/business question/i), "A valid question");
    await userEvent.click(screen.getByRole("button", { name: /start engagement/i }));
    expect(await screen.findByText("String should have at most 200 characters", { selector: "p" })).toBeInTheDocument();
    expect(screen.getByLabelText(/industry/i)).toHaveAttribute("aria-invalid", "true");
  });

  it("explains a server failure and stays on the form so nothing is lost", async () => {
    server.use(http.post(`${API}/engagements`, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
    renderApp(FORM);
    await userEvent.type(screen.getByLabelText(/business question/i), "A valid question");
    await userEvent.click(screen.getByRole("button", { name: /start engagement/i }));
    expect(await screen.findByText("The server had a problem")).toBeInTheDocument();
    expect(screen.getByLabelText(/business question/i)).toHaveValue("A valid question");
  });

  it("disables the button while starting, so a double click cannot start two", async () => {
    let calls = 0;
    server.use(
      http.post(`${API}/engagements`, async () => {
        calls += 1;
        await new Promise((r) => setTimeout(r, 150));
        return HttpResponse.json({ ...fixtures.detail, workflow_id: "wf_new", status: "running" });
      }),
    );
    renderApp(FORM);
    await userEvent.click(screen.getByRole("button", { name: /use the uae example/i }));
    const start = screen.getByRole("button", { name: /start engagement/i });
    await userEvent.dblClick(start);
    expect(await screen.findByRole("button", { name: /starting/i })).toBeDisabled();
    await screen.findByText("wf_new");
    expect(calls).toBe(1);
  });
});
