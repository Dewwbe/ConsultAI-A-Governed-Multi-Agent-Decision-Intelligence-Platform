import { describe, expect, it } from "vitest";
import { EMPTY_FORM, LIMITS, UAE_EXAMPLE, fieldErrorsFromServer, parseLines, validateEngagement } from "./validation";

const form = (over: Partial<typeof EMPTY_FORM>) => ({ ...EMPTY_FORM, ...over });

describe("parseLines", () => {
  it("trims, drops blanks and handles Windows newlines", () => {
    expect(parseLines("  a \r\n\r\n b\n   \nc")).toEqual(["a", "b", "c"]);
    expect(parseLines("")).toEqual([]);
  });
});

describe("validateEngagement (matches the API's limits)", () => {
  it("accepts the UAE example and builds the request payload", () => {
    const { errors, payload } = validateEngagement(UAE_EXAMPLE);
    expect(errors).toEqual({});
    expect(payload).toEqual({
      business_problem: "Should we expand into the UAE market?",
      industry: "Retail",
      objectives: ["Increase revenue"],
      constraints: ["Budget under $10M", "Launch within 18 months"],
      data_classification: "confidential",
    });
  });

  it("requires a business problem of at least 5 characters", () => {
    expect(validateEngagement(form({})).errors.business_problem).toMatch(/Describe/);
    expect(validateEngagement(form({ business_problem: "  abc " })).errors.business_problem).toMatch(/at least 5/);
    expect(validateEngagement(form({ business_problem: "abcde" })).errors.business_problem).toBeUndefined();
  });

  it("enforces the upper limits", () => {
    expect(validateEngagement(form({ business_problem: "x".repeat(LIMITS.problemMax + 1) })).errors.business_problem).toMatch(/at most 4000/);
    expect(validateEngagement(form({ business_problem: "valid text", industry: "i".repeat(201) })).errors.industry).toMatch(/at most 200/);
    const tooMany = Array.from({ length: 21 }, (_, i) => `item ${i}`).join("\n");
    const r = validateEngagement(form({ business_problem: "valid text", objectives: tooMany, constraints: tooMany }));
    expect(r.errors.objectives).toMatch(/at most 20 objectives \(you have 21\)/);
    expect(r.errors.constraints).toMatch(/at most 20 constraints/);
    expect(r.payload).toBeNull();
  });

  it("allows exactly 20 items and does not count blank lines", () => {
    const twenty = Array.from({ length: 20 }, (_, i) => `c${i}`).join("\n\n");
    expect(validateEngagement(form({ business_problem: "valid text", constraints: twenty })).errors).toEqual({});
  });

  it("returns no payload while any error remains", () => {
    expect(validateEngagement(form({ business_problem: "no" })).payload).toBeNull();
  });
});

describe("fieldErrorsFromServer", () => {
  it("puts the server's message next to the right field, including list items", () => {
    expect(fieldErrorsFromServer(["business_problem", "constraints.3", "unknown"], "too long")).toEqual({
      business_problem: "too long",
      constraints: "too long",
    });
  });
});
