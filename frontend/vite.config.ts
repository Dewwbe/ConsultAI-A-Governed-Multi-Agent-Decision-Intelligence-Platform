import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "src") } },
  server: { port: 5173 },
  envDir: process.env.VITEST ? false : ".",
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // Hermetic: never read a developer's local .env (their API port, auth mode...) in tests.
    env: { VITE_API_BASE_URL: "http://localhost:8000", VITE_AUTH_MODE: "dev" },
    exclude: ["e2e/**", "node_modules/**"],
    css: false,
    restoreMocks: true,
    testTimeout: 20_000, // the first test to open a lazily loaded page pays for compiling it
  },
});
