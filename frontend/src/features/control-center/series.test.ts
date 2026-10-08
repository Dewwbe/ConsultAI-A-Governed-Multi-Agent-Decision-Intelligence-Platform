import { describe, expect, it } from "vitest";
import type { TimeseriesOut } from "@/api/types";
import { WINDOWS, labelFor, mergeSeries, sinceFor } from "./series";

const ts = (metric: TimeseriesOut["metric"], pts: [string, number | null, number?][]): TimeseriesOut => ({
  metric, bucket: "day", points: pts.map(([t, value, n]) => ({ t, value, n: n ?? 1 })),
});

describe("mergeSeries", () => {
  it("makes one row per bucket, in time order, across series", () => {
    const rows = mergeSeries(
      { groundedness: ts("groundedness", [["2026-10-02T00:00:00+00:00", 0.8], ["2026-10-01T00:00:00+00:00", 0.9]]), tool: ts("tool_call_accuracy", [["2026-10-01T00:00:00+00:00", 1]]) },
      "day",
    );
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({ groundedness: 0.9, tool: 1 });
    expect(rows[1]).toMatchObject({ groundedness: 0.8, tool: null }); // a missing value stays missing, not zero
  });

  it("keeps a null value null and copes with absent or empty series", () => {
    const rows = mergeSeries({ a: ts("quality", [["2026-10-01T00:00:00+00:00", null]]), b: undefined }, "day");
    expect(rows).toEqual([{ label: expect.any(String), a: null, b: null }]);
    expect(mergeSeries({}, "day")).toEqual([]);
  });
});

describe("windows", () => {
  it("computes the start of a window rounded down to the hour, and none for all time", () => {
    const now = Date.UTC(2026, 9, 8, 13, 47, 22);
    expect(sinceFor("24h", now)).toMatch(/^2026-10-07T\d\d:00:00\.000Z$/);
    expect(sinceFor("7d", now)).toMatch(/^2026-10-01T\d\d:00:00\.000Z$/);
    expect(sinceFor("all", now)).toBeUndefined();
    expect(WINDOWS.map((w) => w.id)).toEqual(["24h", "7d", "30d", "all"]);
  });

  it("is stable within the hour so the cache key does not change on every render", () => {
    const a = Date.UTC(2026, 9, 8, 13, 1, 0);
    const b = Date.UTC(2026, 9, 8, 13, 59, 0);
    expect(sinceFor("7d", a)).toBe(sinceFor("7d", b));
  });

  it("labels buckets and tolerates junk", () => {
    expect(labelFor("not a date", "day")).toBe("not a date");
    expect(labelFor("2026-10-08T00:00:00+00:00", "day")).toMatch(/Oct/);
  });
});
