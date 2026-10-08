import type { EngagementEvent, EngagementStatus, TraceOut } from "@/api/types";

export type StepState = "pending" | "running" | "done" | "error" | "paused" | "skipped";

export interface PipelineStep {
  key: string;
  label: string;
  state: StepState;
  /** How many times the step started (a Guardian retry sends the run back through Solution). */
  attempts: number;
  latencyMs?: number;
  note?: string;
}

/** Steps in one group run side by side (Research and Data are parallel). */
export type PipelineGroup = PipelineStep[];

interface StepDef {
  key: string;
  label: string;
}

/** Order from the plan: Discovery -> Research/Data -> Financial -> Risk -> Solution -> Evaluation ->
 *  Guardian -> Approval -> Report. Keys are the span names the backend emits. */
const DEFS: StepDef[][] = [
  [{ key: "discovery_agent", label: "Discovery" }],
  [
    { key: "research_agent", label: "Research" },
    { key: "data_agent", label: "Data" },
  ],
  [{ key: "financial_agent", label: "Financial" }],
  [{ key: "risk_agent", label: "Risk" }],
  [{ key: "solution_agent", label: "Solution" }],
  [{ key: "evaluator", label: "Evaluation" }],
  [{ key: "guardian", label: "Guardian" }],
  [{ key: "approval", label: "Approval" }],
  [{ key: "report_agent", label: "Report" }],
];

export const STEP_KEYS = DEFS.flat().map((d) => d.key);

interface Track {
  attempts: number;
  running: boolean;
  lastStatus?: string;
  latencyMs?: number;
}

/** Fold the event history into a state for each step. Pure: the same events always give the same view. */
export function derivePipeline(events: EngagementEvent[], status: EngagementStatus | undefined): PipelineGroup[] {
  const tracks = new Map<string, Track>();
  let approvalRequested = false;
  let approvalDecision: string | undefined;
  for (const e of events) {
    if (e.type === "step_started" && e.name) {
      const t = tracks.get(e.name) ?? { attempts: 0, running: false };
      tracks.set(e.name, { ...t, attempts: t.attempts + 1, running: true });
    } else if (e.type === "step_finished" && e.name) {
      const t = tracks.get(e.name) ?? { attempts: 1, running: false };
      tracks.set(e.name, {
        ...t,
        running: false,
        ...(e.status ? { lastStatus: e.status } : {}),
        ...(e.latency_ms !== undefined ? { latencyMs: e.latency_ms } : {}),
      });
    } else if (e.type === "approval_requested") {
      approvalRequested = true;
    } else if (e.type === "approval_decided") {
      approvalDecision = e.decision ?? "decided";
    }
  }

  const ended = status === "escalated" || status === "failed" || status === "rejected" || status === "completed";
  const stopped = status === "escalated" || status === "failed";

  return DEFS.map((group) =>
    group.map((def): PipelineStep => {
      if (def.key === "approval") return approvalStep(def, approvalRequested, approvalDecision, status);
      const t = tracks.get(def.key);
      if (!t) {
        // never started: it is still ahead, unless the run ended without reaching it
        const skipped = stopped || status === "rejected" || (status === "completed" && ended);
        return { ...def, state: skipped ? "skipped" : "pending", attempts: 0 };
      }
      let state: StepState;
      if (t.running) state = status === "failed" ? "error" : "running";
      else state = t.lastStatus === "error" ? "error" : "done";
      return {
        ...def,
        state,
        attempts: t.attempts,
        ...(t.latencyMs !== undefined ? { latencyMs: t.latencyMs } : {}),
        ...(t.attempts > 1 ? { note: `ran ${t.attempts} times` } : {}),
      };
    }),
  );
}

function approvalStep(
  def: StepDef,
  requested: boolean,
  decision: string | undefined,
  status: EngagementStatus | undefined,
): PipelineStep {
  const base = { ...def, attempts: requested ? 1 : 0 };
  if (decision) return { ...base, state: "done", note: decision === "approve" ? "approved" : decision === "modify" ? "modified" : "rejected" };
  if (requested) return { ...base, state: "paused", note: "waiting for a partner" };
  if (status === "completed") return { ...base, state: "skipped", note: "not required" };
  if (status === "escalated" || status === "failed" || status === "rejected") return { ...base, state: "skipped" };
  return { ...base, state: "pending" };
}

/** One-line description of where the run is, for screen readers and the page header. */
export function describeProgress(groups: PipelineGroup[]): string {
  const steps = groups.flat();
  const running = steps.filter((s) => s.state === "running").map((s) => s.label);
  if (running.length) return `Running: ${running.join(" and ")}`;
  const paused = steps.find((s) => s.state === "paused");
  if (paused) return `${paused.label}: ${paused.note ?? "waiting"}`;
  const failed = steps.find((s) => s.state === "error");
  if (failed) return `${failed.label} failed`;
  const done = steps.filter((s) => s.state === "done").length;
  return `${done} of ${steps.length} steps finished`;
}

/**
 * Rebuild step events from a trace. Used when the live stream is unavailable and we poll instead:
 * the trace holds the same agent/evaluator/guardian spans (finished ones; a missing finish means running).
 */
export function eventsFromTrace(trace: TraceOut, status: EngagementStatus | undefined): EngagementEvent[] {
  const events: EngagementEvent[] = [];
  const spans = trace.spans.filter((s) => ["agent", "evaluator", "guardian"].includes(s.kind));
  for (const s of spans) {
    events.push({ id: events.length + 1, type: "step_started", name: s.name, kind: s.kind });
    // spans only land in the trace store when they start; latency stays 0 until they finish
    const finished = s.latency_ms > 0 || status !== "running";
    if (finished) events.push({ id: events.length + 1, type: "step_finished", name: s.name, kind: s.kind, status: s.status, latency_ms: s.latency_ms });
  }
  if (status === "awaiting_approval") events.push({ id: events.length + 1, type: "approval_requested" });
  return events;
}
