import { http, HttpResponse } from "msw";

export const API = "http://localhost:8000";

/** Mirrors the backend contract for the endpoints F0 uses. Later stages add their own handlers. */
export const handlers = [
  http.get(`${API}/health`, () => HttpResponse.json({ status: "ok", llm_provider: "stub" })),
  http.get(`${API}/me`, ({ request }) => {
    const user = request.headers.get("x-dev-user") ?? "anonymous";
    const roles = (request.headers.get("x-dev-roles") ?? "").split(",").filter(Boolean);
    return HttpResponse.json({ user_id: user, name: user, roles, can_approve: roles.includes("Partner") });
  }),
];
