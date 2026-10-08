import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { createApi } from "./client";
import {
  ApiError,
  ConflictError,
  ForbiddenError,
  NetworkError,
  NotFoundError,
  ServerError,
  UnauthorizedError,
  ValidationError,
  apiErrorFrom,
  describeError,
  isRetryable,
  unwrap,
} from "./errors";

describe("apiErrorFrom", () => {
  it.each([
    [401, UnauthorizedError],
    [403, ForbiddenError],
    [404, NotFoundError],
    [409, ConflictError],
    [422, ValidationError],
    [500, ServerError],
    [503, ServerError],
    [418, ApiError],
  ])("maps %i to the right class", (status, cls) => {
    const err = apiErrorFrom(status, { detail: "nope" });
    expect(err).toBeInstanceOf(cls);
    expect(err.status).toBe(status);
    expect(err.detail).toBe("nope");
  });

  it("only the specific class matches, so callers can branch safely", () => {
    const err = apiErrorFrom(409, { detail: "engagement is completed, not awaiting approval" });
    expect(err).toBeInstanceOf(ConflictError);
    expect(err).not.toBeInstanceOf(NotFoundError);
    expect(err.name).toBe("ConflictError");
  });

  it("reads FastAPI validation arrays", () => {
    const err = apiErrorFrom(422, {
      detail: [
        { loc: ["body", "business_problem"], msg: "String should have at least 5 characters" },
        { loc: ["body", "industry"], msg: "too long" },
      ],
    }) as ValidationError;
    expect(err.fields).toEqual(["business_problem", "industry"]);
    expect(err.detail).toContain("at least 5 characters");
  });

  it("falls back to a generic message when the body has no detail", () => {
    expect(apiErrorFrom(500, undefined).detail).toBe("Request failed (500)");
  });
});

describe("unwrap against a real client", () => {
  const api = createApi({ baseUrl: API });

  it("returns data on success", async () => {
    await expect(unwrap(api.GET("/health"))).resolves.toEqual({ status: "ok", llm_provider: "stub" });
  });

  it("throws NotFoundError for 404", async () => {
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json({ detail: "engagement not found" }, { status: 404 })));
    const call = unwrap(api.GET("/engagements/{workflow_id}", { params: { path: { workflow_id: "wf_x" } } }));
    await expect(call).rejects.toBeInstanceOf(NotFoundError);
  });

  it("throws ConflictError for 409 with the server's explanation", async () => {
    server.use(
      http.post(`${API}/engagements/:id/approval`, () =>
        HttpResponse.json({ detail: "engagement is completed, not awaiting approval" }, { status: 409 }),
      ),
    );
    const call = unwrap(
      api.POST("/engagements/{workflow_id}/approval", {
        params: { path: { workflow_id: "wf_x" } },
        body: { decision: "approve", changes: {}, reason: "" },
      }),
    );
    await expect(call).rejects.toMatchObject({ status: 409, detail: "engagement is completed, not awaiting approval" });
    await expect(call).rejects.toBeInstanceOf(ConflictError);
  });

  it("throws ForbiddenError for 403", async () => {
    server.use(http.post(`${API}/engagements/:id/approval`, () => HttpResponse.json({ detail: "needs Partner" }, { status: 403 })));
    const call = unwrap(
      api.POST("/engagements/{workflow_id}/approval", {
        params: { path: { workflow_id: "wf_x" } },
        body: { decision: "approve", changes: {}, reason: "" },
      }),
    );
    await expect(call).rejects.toBeInstanceOf(ForbiddenError);
  });

  it("wraps a dead connection in NetworkError", async () => {
    server.use(http.get(`${API}/health`, () => HttpResponse.error()));
    await expect(unwrap(api.GET("/health"))).rejects.toBeInstanceOf(NetworkError);
  });
});

describe("retry policy and wording", () => {
  it("retries transient failures only", () => {
    expect(isRetryable(new NetworkError())).toBe(true);
    expect(isRetryable(apiErrorFrom(503, {}))).toBe(true);
    for (const status of [401, 403, 404, 409, 422]) expect(isRetryable(apiErrorFrom(status, {}))).toBe(false);
    expect(isRetryable(new Error("x"))).toBe(false);
  });

  it("describes each failure in plain words", () => {
    expect(describeError(apiErrorFrom(404, {})).title).toBe("Not found");
    expect(describeError(apiErrorFrom(409, {})).title).toBe("Not awaiting approval");
    expect(describeError(apiErrorFrom(403, { detail: "approving requires the 'Partner' role" })).message).toContain("Partner");
    expect(describeError(apiErrorFrom(401, {})).title).toBe("Sign-in required");
    expect(describeError(new NetworkError()).title).toBe("Cannot reach the API");
    expect(describeError("weird").title).toBe("Something went wrong");
  });
});
