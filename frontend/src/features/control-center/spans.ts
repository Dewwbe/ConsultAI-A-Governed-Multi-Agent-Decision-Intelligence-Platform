import type { SpanOut } from "@/api/types";

export type SpanKind = "agent" | "llm" | "tool" | "retrieval" | "guardian" | "evaluator" | "approval" | "workflow";

/** One categorical colour per span kind, in the validated palette's fixed order. Approval/workflow stay neutral. */
export const KIND_META: Record<SpanKind, { label: string; color: string }> = {
  agent: { label: "Agent", color: "var(--series-1)" },
  llm: { label: "Model call", color: "var(--series-2)" },
  tool: { label: "Tool call", color: "var(--series-3)" },
  retrieval: { label: "Retrieval", color: "var(--series-4)" },
  evaluator: { label: "Evaluator", color: "var(--series-5)" },
  guardian: { label: "Guardian", color: "var(--series-6)" },
  approval: { label: "Approval", color: "var(--chart-muted)" },
  workflow: { label: "Workflow", color: "var(--chart-muted)" },
};

export const kindOf = (span: Pick<SpanOut, "kind">): SpanKind => (span.kind in KIND_META ? (span.kind as SpanKind) : "workflow");

/** An idle gap (a run waiting for a partner) longer than this is collapsed so bars stay readable. */
export const MAX_VISIBLE_GAP_MS = 2_000;

export interface SpanRow {
  span: SpanOut;
  depth: number;
  /** Milliseconds from the start of the run's active time, with long idle gaps collapsed. */
  offsetMs: number;
  durationMs: number;
  hasChildren: boolean;
  /** Set on a top-level span that follows a collapsed idle gap: how long the run was idle. */
  idleBeforeMs?: number;
}

export interface Waterfall {
  rows: SpanRow[];
  totalMs: number;
  /** Span ids in the order they should be listed. */
  order: string[];
}

/** Build the tree from parent ids and lay it out as waterfall rows (depth-first, earliest child first). */
export function buildWaterfall(spans: SpanOut[]): Waterfall {
  if (spans.length === 0) return { rows: [], totalMs: 0, order: [] };
  const byParent = new Map<string | null, SpanOut[]>();
  const ids = new Set(spans.map((s) => s.span_id));
  for (const s of spans) {
    // a span whose parent is missing (for example truncated) is treated as a root rather than lost
    const parent = s.parent_id && ids.has(s.parent_id) ? s.parent_id : null;
    byParent.set(parent, [...(byParent.get(parent) ?? []), s]);
  }
  for (const list of byParent.values()) list.sort((a, b) => a.start - b.start);

  // collapse long idle gaps between top-level spans; children inherit their root's shift
  const roots = byParent.get(null) ?? [];
  const shiftOf = new Map<string, number>();
  const idleOf = new Map<string, number>();
  let shift = 0;
  let coveredUntil = roots[0] ? roots[0].start : 0;
  for (const root of roots) {
    const gapMs = (root.start - coveredUntil) * 1000;
    if (gapMs > MAX_VISIBLE_GAP_MS) {
      shift += gapMs - 0;
      idleOf.set(root.span_id, gapMs);
    }
    shiftOf.set(root.span_id, shift);
    coveredUntil = Math.max(coveredUntil, root.start + root.latency_ms / 1000);
  }

  const t0 = roots[0]?.start ?? spans[0]!.start;
  const rows: SpanRow[] = [];
  const walk = (span: SpanOut, depth: number, rootShift: number, idle?: number) => {
    const kids = byParent.get(span.span_id) ?? [];
    rows.push({
      span, depth, hasChildren: kids.length > 0, durationMs: span.latency_ms,
      offsetMs: Math.max(0, (span.start - t0) * 1000 - rootShift),
      ...(idle ? { idleBeforeMs: idle } : {}),
    });
    for (const k of kids) walk(k, depth + 1, rootShift);
  };
  for (const root of roots) walk(root, 0, shiftOf.get(root.span_id) ?? 0, idleOf.get(root.span_id));

  const totalMs = Math.max(1, ...rows.map((r) => r.offsetMs + r.durationMs));
  return { rows, totalMs, order: rows.map((r) => r.span.span_id) };
}

export type ToolOutcome = "ok" | "blocked" | "invalid_arguments" | "timeout" | "error";

export function toolOutcome(span: SpanOut): ToolOutcome {
  const outcome = span.attributes["consultai.outcome"];
  if (outcome === "blocked" || outcome === "invalid_arguments" || outcome === "timeout") return outcome;
  if (span.status === "error") return "error";
  return "ok";
}

export const toolSpans = (spans: SpanOut[]) => spans.filter((s) => s.kind === "tool");
export const retrievalSpans = (spans: SpanOut[]) => spans.filter((s) => s.kind === "retrieval");

export function attr<T = unknown>(span: SpanOut, key: string): T | undefined {
  return span.attributes[key] as T | undefined;
}

/** Marker the API puts where a payload was withheld from this user. */
export const isRedacted = (value: unknown): boolean => typeof value === "string" && value.startsWith("[redacted");
