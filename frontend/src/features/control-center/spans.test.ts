import { describe, expect, it } from "vitest";
import type { SpanOut } from "@/api/types";
import trace from "@/mocks/fixtures/trace.json";
import { MAX_VISIBLE_GAP_MS, buildWaterfall, isRedacted, kindOf, toolOutcome, toolSpans } from "./spans";

let n = 0;
const span = (over: Partial<SpanOut> = {}): SpanOut => ({
  span_id: `s${++n}`, parent_id: null, name: "x", kind: "agent", attributes: {}, start: 1000, latency_ms: 100,
  status: "ok", error: null, ...over,
});

describe("buildWaterfall", () => {
  it("nests children under parents, earliest first, with offsets relative to the first span", () => {
    const root = span({ span_id: "r", start: 1000, latency_ms: 500 });
    const late = span({ span_id: "c2", parent_id: "r", start: 1000.3, latency_ms: 100, name: "late" });
    const early = span({ span_id: "c1", parent_id: "r", start: 1000.1, latency_ms: 100, name: "early" });
    const grand = span({ span_id: "g", parent_id: "c1", start: 1000.12, latency_ms: 10 });
    const w = buildWaterfall([late, grand, root, early]);
    expect(w.order).toEqual(["r", "c1", "g", "c2"]);
    expect(w.rows.map((r) => r.depth)).toEqual([0, 1, 2, 1]);
    expect(w.rows[1]?.offsetMs).toBeCloseTo(100, 3);
    expect(w.rows[0]?.hasChildren).toBe(true);
    expect(w.rows[2]?.hasChildren).toBe(false);
    expect(w.totalMs).toBeCloseTo(500, 3);
  });

  it("keeps a span whose parent is missing, as a root, instead of dropping it", () => {
    const w = buildWaterfall([span({ span_id: "a" }), span({ span_id: "b", parent_id: "gone" })]);
    expect(w.order.sort()).toEqual(["a", "b"]);
    expect(w.rows.every((r) => r.depth === 0)).toBe(true);
  });

  it("handles no spans", () => {
    expect(buildWaterfall([])).toEqual({ rows: [], totalMs: 0, order: [] });
  });

  it("collapses a long idle wait, such as time spent waiting for a partner, so later bars stay visible", () => {
    const before = span({ span_id: "a", start: 1000, latency_ms: 1000 });
    const afterHours = span({ span_id: "b", start: 1000 + 3 * 3600, latency_ms: 1000 });
    const w = buildWaterfall([before, afterHours]);
    const b = w.rows.find((r) => r.span.span_id === "b")!;
    expect(b.idleBeforeMs).toBeGreaterThan(MAX_VISIBLE_GAP_MS);
    expect(b.offsetMs).toBeLessThan(2_500); // right after the first span, not three hours later
    expect(w.totalMs).toBeLessThan(5_000);
    expect(w.rows.find((r) => r.span.span_id === "a")?.idleBeforeMs).toBeUndefined();
  });

  it("does not collapse small gaps, and children follow their root's shift", () => {
    const a = span({ span_id: "a", start: 1000, latency_ms: 500 });
    const b = span({ span_id: "b", start: 1000.9, latency_ms: 100 });
    const child = span({ span_id: "c", parent_id: "b", start: 1000.95, latency_ms: 10 });
    const w = buildWaterfall([a, b, child]);
    expect(w.rows.find((r) => r.span.span_id === "b")?.offsetMs).toBeCloseTo(900, 3);
    expect(w.rows.find((r) => r.span.span_id === "c")?.offsetMs).toBeCloseTo(950, 3);
  });

  it("lays out the real recorded trace: every span appears once, none starts before the run", () => {
    const spans = trace.spans as unknown as SpanOut[];
    const w = buildWaterfall(spans);
    expect(w.rows).toHaveLength(spans.length);
    expect(new Set(w.order).size).toBe(spans.length);
    expect(w.rows.every((r) => r.offsetMs >= 0 && r.durationMs >= 0)).toBe(true);
    const agent = w.rows.find((r) => r.span.name === "financial_agent")!;
    const children = w.rows.filter((r) => r.depth === 1 && w.rows.indexOf(r) > w.rows.indexOf(agent));
    expect(agent.hasChildren && children.length > 0).toBe(true);
  });
});

describe("kinds and tool outcomes", () => {
  it("falls back to a neutral kind for unknown values", () => {
    expect(kindOf({ kind: "tool" })).toBe("tool");
    expect(kindOf({ kind: "something-new" })).toBe("workflow");
  });

  it("classifies tool calls by what happened", () => {
    expect(toolOutcome(span({ attributes: { "consultai.outcome": "blocked" }, status: "error" }))).toBe("blocked");
    expect(toolOutcome(span({ attributes: { "consultai.outcome": "invalid_arguments" }, status: "error" }))).toBe("invalid_arguments");
    expect(toolOutcome(span({ status: "error" }))).toBe("error");
    expect(toolOutcome(span({ attributes: { "consultai.outcome": "ok" } }))).toBe("ok");
  });

  it("finds the tool spans in the real trace, with the Guardian decision on each", () => {
    const tools = toolSpans(trace.spans as unknown as SpanOut[]);
    expect(tools.length).toBeGreaterThan(5);
    const executor = tools.filter((t) => t.attributes["consultai.guardian"]);
    expect(executor.length).toBeGreaterThan(0);
    expect(executor.every((t) => (t.attributes["consultai.guardian"] as { policy_version: string }).policy_version)).toBe(true);
  });

  it("recognises the redaction marker", () => {
    expect(isRedacted("[redacted: needs the owner, Partner or Admin role]")).toBe(true);
    expect(isRedacted({ a: 1 })).toBe(false);
    expect(isRedacted("plain")).toBe(false);
  });
});
