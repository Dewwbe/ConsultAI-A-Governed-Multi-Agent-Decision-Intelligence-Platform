import "@testing-library/jest-dom/vitest";
import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "@/mocks/server";

// A busy machine can take over a second to render a large page; this is a ceiling, not a delay.
configure({ asyncUtilTimeout: 8000 });

// Unhandled requests fail the test: a component must never call an endpoint nobody mocked.
beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  cleanup();
  window.localStorage.clear();
  document.documentElement.classList.remove("dark");
});
afterAll(() => server.close());
