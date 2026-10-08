import type { TimeseriesOut } from "@/api/types";
import type { TrendPoint } from "@/components/charts/charts";

export const WINDOWS = [
  { id: "24h", label: "Last 24 hours", ms: 24 * 3600_000, bucket: "hour" as const },
  { id: "7d", label: "Last 7 days", ms: 7 * 24 * 3600_000, bucket: "day" as const },
  { id: "30d", label: "Last 30 days", ms: 30 * 24 * 3600_000, bucket: "day" as const },
  { id: "all", label: "All time", ms: null, bucket: "day" as const },
];
export type WindowId = (typeof WINDOWS)[number]["id"];

/** ISO start of a window, rounded down to the hour so the query key (and the cache) stays stable. */
export function sinceFor(id: WindowId, now = Date.now()): string | undefined {
  const w = WINDOWS.find((x) => x.id === id);
  if (!w || w.ms === null) return undefined;
  const t = new Date(now - w.ms);
  t.setUTCMinutes(0, 0, 0); // UTC, not local: a +5:30 timezone must not shift the boundary
  return t.toISOString();
}

export function labelFor(t: string, bucket: "hour" | "day"): string {
  const d = new Date(t);
  if (Number.isNaN(d.getTime())) return t;
  return bucket === "hour"
    ? d.toLocaleString(undefined, { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** Merge several single-metric series into one row per time bucket (missing values stay null, not zero). */
export function mergeSeries(series: Record<string, TimeseriesOut | undefined>, bucket: "hour" | "day"): TrendPoint[] {
  const times = new Set<string>();
  for (const s of Object.values(series)) for (const p of s?.points ?? []) times.add(p.t);
  return [...times].sort().map((t) => ({
    label: labelFor(t, bucket),
    ...Object.fromEntries(Object.entries(series).map(([key, s]) => [key, s?.points.find((p) => p.t === t)?.value ?? null])),
  }));
}
