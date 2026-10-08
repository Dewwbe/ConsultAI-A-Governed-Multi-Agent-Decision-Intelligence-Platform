import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { createApi } from "./client";

function captureHeaders() {
  const seen: Headers[] = [];
  server.use(
    http.get(`${API}/health`, ({ request }) => {
      seen.push(request.headers);
      return HttpResponse.json({ status: "ok", llm_provider: "stub" });
    }),
  );
  return seen;
}

describe("identity middleware", () => {
  it("sends the dev identity on every request", async () => {
    const seen = captureHeaders();
    const api = createApi({ baseUrl: API, getIdentity: () => ({ user: "pat", roles: ["Partner", "Admin"] }) });
    await api.GET("/health");
    expect(seen[0]?.get("x-dev-user")).toBe("pat");
    expect(seen[0]?.get("x-dev-roles")).toBe("Partner,Admin");
  });

  it("reads the identity per request, so switching needs no new client", async () => {
    const seen = captureHeaders();
    let who = { user: "ann", roles: ["Analyst"] };
    const api = createApi({ baseUrl: API, getIdentity: () => who });
    await api.GET("/health");
    who = { user: "pat", roles: ["Partner"] };
    await api.GET("/health");
    expect(seen.map((h) => h.get("x-dev-user"))).toEqual(["ann", "pat"]);
  });

  it("sends no identity headers when there is none", async () => {
    const seen = captureHeaders();
    await createApi({ baseUrl: API, getIdentity: () => null }).GET("/health");
    expect(seen[0]?.has("x-dev-user")).toBe(false);
  });
});
