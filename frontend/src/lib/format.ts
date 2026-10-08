const NO_VALUE = "n/a";

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

export function formatUsd(value: number | null | undefined, compact = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE;
  return (compact ? usdCompact : usd).format(value);
}

/** 0.1234 -> "12%". Pass digits for finer values (probabilities, margins). */
export function formatPct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE;
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE;
  return value.toFixed(2);
}

export function formatYears(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "no payback";
  return `${value.toFixed(1)} yr`;
}

export function formatMonths(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return NO_VALUE;
  return `${Number.isInteger(value) ? value : value.toFixed(1)} mo`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return NO_VALUE;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} m ${Math.round(s % 60)} s`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return NO_VALUE;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return NO_VALUE;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** snake_case or kebab-case -> "Sentence case". */
export function humanize(key: string): string {
  const text = key.replace(/[_-]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** Risk label from a probability x impact score; thresholds match the backend (0.5 high, 0.25 medium). */
export function riskLevel(score: number): "High" | "Medium" | "Low" {
  return score >= 0.5 ? "High" : score >= 0.25 ? "Medium" : "Low";
}
