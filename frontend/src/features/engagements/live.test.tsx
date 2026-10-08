import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { liveConfig } from "@/api/liveConfig";
import { API, fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { renderApp } from "@/test/utils";

const ID = fixtures.detail.workflow_id;
const original = { ...liveConfig, retryDelaysMs: [...liveConfig.retryDelaysMs] };

beforeEach(() => {
  liveConfig.retryDelaysMs = [5, 5, 5];
  liveConfig.pollMs = 40;
});
afterEach(() => {
  liveConfig.retryDelaysMs = original.retryDelaysMs;
  liveConfig.pollMs = original.pollMs;
});

const enc = new TextEncoder();
const msg = (id: number, type: string, data: object = {}) => `id: ${id}\nevent: ${type}\ndata: ${JSON.stringify(data)}\n\n`;
const started = (id: number, name: string) => msg(id, "step_started", { name, kind: "agent" });
const finished = (id: number, name: string) => msg(id, "step_finished", { name, kind: "agent", status: "ok", latency_ms: 12 });

/** A stream the test controls: push events when it wants, then close or break it. */
function controllable() {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const stream = new ReadableStream<Uint8Array>({ start: (c) => { ctrl = c; } });
  return {
    response: () => new HttpResponse(stream, { headers: { "Content-Type": "text/event-stream" } }),
    push: (text: string) => ctrl.enqueue(enc.encode(text)),
    close: () => ctrl.close(),
    break: () => ctrl.error(new TypeError("network error")),
  };
}

const runningDetail = { ...fixtures.detail, status: "running", pending_node: [], guardian_decisions: [], state: { business_problem: "Should we expand into the UAE market?" } };
const stepOf = (name: string) => screen.getByText(name, { selector: "span" }).closest("li")!;

describe("live pipeline over server-sent events", () => {
  it("shows progress as it happens, then the pause, and refreshes the data behind it", async () => {
    const stream = controllable();
    let status: "running" | "awaiting" = "running";
    server.use(
      http.get(`${API}/engagements/:id/events`, () => stream.response()),
      http.get(`${API}/engagements/:id`, () => HttpResponse.json(status === "running" ? runningDetail : fixtures.detail)),
    );
    renderApp(`/engagements/${ID}`);
    await screen.findByRole("heading", { level: 1, name: /expand into the UAE/ });
    expect(screen.getByText("Running", { selector: "span" })).toBeInTheDocument();

    stream.push(msg(1, "run_started") + started(2, "discovery_agent") + finished(3, "discovery_agent") + started(4, "research_agent") + started(5, "data_agent"));
    await waitFor(() => expect(stepOf("Discovery")).toHaveTextContent("Done"));
    expect(stepOf("Research")).toHaveTextContent("Running");
    expect(stepOf("Data")).toHaveTextContent("Running");
    expect(stepOf("Financial")).toHaveTextContent("Pending");
    expect(await screen.findByText("Live")).toBeInTheDocument();

    status = "awaiting";
    const rest = ["research_agent", "data_agent"].map((n, i) => finished(6 + i, n)).join("")
      + ["financial_agent", "risk_agent", "solution_agent", "evaluator", "guardian"].map((n, i) => started(10 + i * 2, n) + finished(11 + i * 2, n)).join("")
      + msg(30, "approval_requested", { status: "awaiting_approval", risk_level: "high" });
    stream.push(rest);
    stream.close();

    await waitFor(() => expect(stepOf("Approval")).toHaveTextContent("Waiting"));
    expect(stepOf("Guardian")).toHaveTextContent("Done");
    // the engagement query was refreshed from the events: the badge and the summary now reflect the paused run
    expect(await screen.findByText("Awaiting approval", { selector: "span" })).toBeInTheDocument();
    expect(await screen.findByText("Recommendation: Pilot")).toBeInTheDocument();
    expect(await screen.findByText("Up to date")).toBeInTheDocument();
  });

  it("reconnects after a dropped connection from the last event it saw, with nothing missed or repeated", async () => {
    const first = controllable();
    const second = controllable();
    const urls: string[] = [];
    server.use(
      http.get(`${API}/engagements/:id/events`, ({ request }) => {
        urls.push(request.url);
        return (urls.length === 1 ? first : second).response();
      }),
      http.get(`${API}/engagements/:id`, () => HttpResponse.json(runningDetail)),
    );
    renderApp(`/engagements/${ID}`);
    await screen.findByRole("heading", { level: 1 });

    first.push(msg(1, "run_started") + started(2, "discovery_agent") + finished(3, "discovery_agent"));
    await waitFor(() => expect(stepOf("Discovery")).toHaveTextContent("Done"));
    first.break(); // the network drops

    await waitFor(() => expect(urls).toHaveLength(2));
    expect(urls[0]).toContain("after=0");
    expect(urls[1]).toContain("after=3"); // resumes after the last event received
    // the server replays only what is new; the earlier steps are still shown, and not counted twice
    second.push(started(4, "research_agent"));
    await waitFor(() => expect(stepOf("Research")).toHaveTextContent("Running"));
    expect(stepOf("Discovery")).toHaveTextContent("Done");
    expect(within(stepOf("Discovery")).queryByText("×2")).not.toBeInTheDocument();
    second.close();
  });

  it("falls back to polling when the stream keeps failing, and still tracks the run", async () => {
    let detailCalls = 0;
    server.use(
      http.get(`${API}/engagements/:id/events`, () => HttpResponse.error()),
      http.get(`${API}/engagements/:id`, () => {
        detailCalls += 1;
        return HttpResponse.json(detailCalls < 3 ? runningDetail : fixtures.detail);
      }),
    );
    renderApp(`/engagements/${ID}`);
    expect(await screen.findByText(/Live updates unavailable/)).toBeInTheDocument();
    // polling carries on until the run stops running...
    expect(await screen.findByText("Awaiting approval", { selector: "span" }, { timeout: 4000 })).toBeInTheDocument();
    // ...and the pipeline is rebuilt from the trace instead of the stream
    await waitFor(() => expect(stepOf("Guardian")).toHaveTextContent("Done"));
    expect(stepOf("Approval")).toHaveTextContent("Waiting");
    const callsWhenDone = detailCalls;
    await new Promise((r) => setTimeout(r, 200));
    expect(detailCalls).toBe(callsWhenDone); // polling stops once the run is no longer running
  });

  it("does not retry a stream the user may not read: it shows the typed error", async () => {
    let streamCalls = 0;
    server.use(
      http.get(`${API}/engagements/:id/events`, () => {
        streamCalls += 1;
        return HttpResponse.json({ detail: "missing bearer token" }, { status: 401 });
      }),
      http.get(`${API}/engagements/:id`, () => HttpResponse.json({ detail: "missing bearer token" }, { status: 401 })),
    );
    renderApp(`/engagements/${ID}`);
    expect(await screen.findByText("Sign-in required")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 100));
    expect(streamCalls).toBe(1);
  });

  it("marks a retried step with the number of attempts", async () => {
    const stream = controllable();
    server.use(
      http.get(`${API}/engagements/:id/events`, () => stream.response()),
      http.get(`${API}/engagements/:id`, () => HttpResponse.json(runningDetail)),
    );
    renderApp(`/engagements/${ID}`);
    await screen.findByRole("heading", { level: 1 });
    stream.push(started(1, "solution_agent") + finished(2, "solution_agent") + started(3, "solution_agent") + finished(4, "solution_agent"));
    await waitFor(() => expect(within(stepOf("Solution")).getByText("×2")).toBeInTheDocument());
    stream.close();
  });
});
