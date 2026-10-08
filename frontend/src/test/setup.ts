import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "@/mocks/server";

// Unhandled requests fail the test: a component must never call an endpoint nobody mocked.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
  window.localStorage.clear();
  document.documentElement.classList.remove("dark");
});
afterAll(() => server.close());
