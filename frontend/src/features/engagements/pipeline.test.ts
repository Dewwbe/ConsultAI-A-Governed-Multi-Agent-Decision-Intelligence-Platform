import { describe, expect, it } from "vitest";
import type { EngagementEvent, TraceOut } from "@/api/types";
import { SseParser } from "@/api/sse";
import eventsText from "@/mocks/fixtures/events.sse.txt?raw";
import trace from "@/mocks/fixtures/trace.json";
import { STEP_KEYS, derivePipeline, describeProgress, eventsFromTrace } from "./pipeline";

let n = 0;
const ev = (type: string, extra: Partial<EngagementEvent> = {}): EngagementEvent => ({ id: ++n, type, ...extra });
const start = (name: string) => ev("step_started", { name, kind: "agent" });
const finish = (name: string, status = "ok", latency_ms = 10) => ev("step_finished", { name, kind: "agent", status, latency_ms });
const states = (groups: ReturnType<typeof derivePipeline>) => Object.fromEntries(groups.flat().map((s) => [s.key, s.state]));

describe("derivePipeline", () => {
  it("lists the steps in the plan's order, with Research and Data in one group", () => {
    const groups = derivePipeline([], undefined);
    expect(groups.map((g) => g.map((s) => s.label))).toEqual([
      ["Discovery"], ["Research", "Data"], ["Financial"], ["Risk"], ["Solution"], ["Evaluation"], ["Guardian"], ["Approval"], ["Report"],
    ]);
    expect(groups.flat().every((s) => s.state === "pending")).toBe(true);
    expect(groups.flat().map((s) => s.key)).toEqual(STEP_KEYS);
  });

  it("shows the running step and what is done", () => {
    const groups = derivePipeline([ev("run_started"), start("discovery_agent"), finish("discovery_agent", "ok", 2100), start("research_agent"), start("data_agent")], "running");
    const s = states(groups);
    expect(s["discovery_agent"]).toBe("done");
    expect(s["research_agent"]).toBe("running");
    expect(s["data_agent"]).toBe("running");
    expect(s["financial_agent"]).toBe("pending");
    expect(groups[0]?.[0]?.latencyMs).toBe(2100);
    expect(describeProgress(groups)).toBe("Running: Research and Data");
  });

  it("marks a step that finished with an error", () => {
    const groups = derivePipeline([start("financial_agent"), finish("financial_agent", "error")], "escalated");
    expect(states(groups)["financial_agent"]).toBe("error");
    expect(describeProgress(groups)).toBe("Financial failed");
  });

  it("counts a Guardian retry as a second attempt", () => {
    const events = ["solution_agent", "evaluator", "guardian", "solution_agent", "evaluator", "guardian"].flatMap((name) => [start(name), finish(name)]);
    const solution = derivePipeline(events, "running").flat().find((s) => s.key === "solution_agent");
    expect(solution).toMatchObject({ state: "done", attempts: 2, note: "ran 2 times" });
  });

  it("pauses at Approval, then completes it with the decision", () => {
    const base = [start("guardian"), finish("guardian")];
    const paused = derivePipeline([...base, ev("approval_requested")], "awaiting_approval");
    expect(states(paused)["approval"]).toBe("paused");
    expect(paused.flat().find((s) => s.key === "approval")?.note).toBe("waiting for a partner");
    expect(describeProgress(paused)).toContain("waiting for a partner");
    const decided = derivePipeline([...base, ev("approval_requested"), ev("approval_decided", { decision: "modify" }), start("report_agent"), finish("report_agent")], "completed");
    expect(decided.flat().find((s) => s.key === "approval")).toMatchObject({ state: "done", note: "modified" });
    expect(states(decided)["report_agent"]).toBe("done");
  });

  it("skips Approval when it was not required and the run completed", () => {
    const groups = derivePipeline([start("guardian"), finish("guardian"), start("report_agent"), finish("report_agent")], "completed");
    expect(groups.flat().find((s) => s.key === "approval")).toMatchObject({ state: "skipped", note: "not required" });
  });

  it("skips what was never reached when the run escalates or is rejected", () => {
    const esc = states(derivePipeline([start("discovery_agent"), finish("discovery_agent", "error")], "escalated"));
    expect(esc["discovery_agent"]).toBe("error");
    expect(["research_agent", "financial_agent", "guardian", "approval", "report_agent"].map((k) => esc[k])).toEqual(Array(5).fill("skipped"));
    const rejected = states(derivePipeline([start("guardian"), finish("guardian"), ev("approval_requested"), ev("approval_decided", { decision: "reject" })], "rejected"));
    expect(rejected["approval"]).toBe("done");
    expect(rejected["report_agent"]).toBe("skipped");
  });

  it("turns a running step into an error if the run failed", () => {
    expect(states(derivePipeline([start("risk_agent")], "failed"))["risk_agent"]).toBe("error");
  });

  it("reproduces the real run from the backend's recorded stream", () => {
    const events: EngagementEvent[] = new SseParser().push(eventsText).map((m) => ({ ...(m.data as object), id: m.id ?? 0, type: m.event }) as EngagementEvent);
    expect(events[0]?.type).toBe("run_started");
    expect(events.at(-1)?.type).toBe("approval_requested");
    const groups = derivePipeline(events, "awaiting_approval");
    const s = states(groups);
    for (const k of ["discovery_agent", "research_agent", "data_agent", "financial_agent", "risk_agent", "solution_agent", "evaluator", "guardian"]) expect(s[k], k).toBe("done");
    expect(s["approval"]).toBe("paused");
    expect(s["report_agent"]).toBe("pending");
  });
});

describe("eventsFromTrace (polling fallback)", () => {
  it("rebuilds step events from the trace's agent, evaluator and guardian spans", () => {
    const events = eventsFromTrace(trace as unknown as TraceOut, "awaiting_approval");
    const names = events.filter((e) => e.type === "step_started").map((e) => e.name);
    expect(names).toEqual(expect.arrayContaining(["discovery_agent", "financial_agent", "evaluator", "guardian"]));
    expect(events.at(-1)?.type).toBe("approval_requested");
    const s = states(derivePipeline(events, "awaiting_approval"));
    expect(s["guardian"]).toBe("done");
    expect(s["approval"]).toBe("paused");
  });

  it("treats a span with no latency yet as still running while the run is running", () => {
    const t = { spans: [{ kind: "agent", name: "risk_agent", status: "ok", latency_ms: 0 }] } as unknown as TraceOut;
    expect(states(derivePipeline(eventsFromTrace(t, "running"), "running"))["risk_agent"]).toBe("running");
  });
});
