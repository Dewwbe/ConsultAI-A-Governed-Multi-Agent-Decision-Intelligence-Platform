import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8011;
const UI_PORT = 5174;
const backend = path.resolve(import.meta.dirname, "../backend");

/**
 * End-to-end tests run the real API (offline stub models, a throwaway database) behind the real UI, so
 * they cover what the mocked unit tests cannot: the live stream, the pause and the approval round trip.
 */
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: { baseURL: `http://localhost:${UI_PORT}`, trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "tablet", use: { ...devices["iPad (gen 7)"], browserName: "chromium" }, grep: /@layout/ },
  ],
  webServer: [
    {
      command: `python -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: backend,
      url: `http://localhost:${API_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        LLM_PROVIDER: "stub",
        AUTH_MODE: "dev",
        ENVIRONMENT: "dev",
        DATABASE_URL: "sqlite:///./e2e.db",
        CORS_ORIGINS: `http://localhost:${UI_PORT}`,
      },
    },
    {
      command: `npm run dev -- --port ${UI_PORT} --strictPort`,
      url: `http://localhost:${UI_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: { VITE_API_BASE_URL: `http://localhost:${API_PORT}`, VITE_AUTH_MODE: "dev" },
    },
  ],
});
