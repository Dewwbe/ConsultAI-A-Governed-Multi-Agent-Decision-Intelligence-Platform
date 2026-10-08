import { describe, expect, it } from "vitest";
import { formatDuration, formatMonths, formatPct, formatScore, formatUsd, formatYears, humanize, riskLevel } from "./format";

describe("format", () => {
  it("formats money, compact and full", () => {
    expect(formatUsd(8_000_000)).toBe("$8,000,000");
    expect(formatUsd(8_000_000, true)).toBe("$8M");
    expect(formatUsd(693_876.4)).toBe("$693,876");
    expect(formatUsd(null)).toBe("n/a");
    expect(formatUsd(Number.NaN)).toBe("n/a");
  });

  it("formats percentages and scores", () => {
    expect(formatPct(0.1632)).toBe("16%");
    expect(formatPct(0.1632, 1)).toBe("16.3%");
    expect(formatPct(-0.01)).toBe("-1%");
    expect(formatPct(undefined)).toBe("n/a");
    expect(formatScore(0.5)).toBe("0.50");
  });

  it("formats payback, launch time and durations", () => {
    expect(formatYears(2.857)).toBe("2.9 yr");
    expect(formatYears(null)).toBe("no payback");
    expect(formatMonths(9)).toBe("9 mo");
    expect(formatMonths(7.5)).toBe("7.5 mo");
    expect(formatDuration(250)).toBe("250 ms");
    expect(formatDuration(12_340)).toBe("12.3 s");
    expect(formatDuration(95_000)).toBe("1 m 35 s");
  });

  it("humanizes keys and labels risk by score like the backend", () => {
    expect(humanize("constraint_satisfaction")).toBe("Constraint satisfaction");
    expect(humanize("")).toBe("");
    expect(riskLevel(0.52)).toBe("High");
    expect(riskLevel(0.3)).toBe("Medium");
    expect(riskLevel(0.1)).toBe("Low");
  });
});
