import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// Regenerates docs/screenshots from the real UI. Skipped in normal runs:  npm run screenshots
test.skip(!process.env.SCREENSHOTS, "set SCREENSHOTS=1 (npm run screenshots) to regenerate the README images");

const OUT = path.resolve(import.meta.dirname, "../../docs/screenshots");

async function signInAs(page: Page, user: string, roles: string[]) {
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key as string, value as string),
    ["consultai.devIdentity", JSON.stringify({ user, roles })],
  );
}

const shot = (page: Page, name: string) => page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });

test("README screenshots", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await signInAs(page, "pat", ["Partner", "Admin"]);

  await page.goto("/engagements/new");
  await page.getByRole("button", { name: /use the uae example/i }).click();
  await shot(page, "01-new-engagement");
  await page.getByRole("button", { name: /start engagement/i }).click();
  await page.waitForURL(/\/engagements\/wf_/);
  await expect(page.getByText("Waiting for a partner's decision")).toBeVisible();
  const detail = new URL(page.url()).pathname;
  const id = detail.split("/").pop();
  await shot(page, "02-pipeline-awaiting-approval");

  await page.getByRole("tab", { name: /evidence/i }).click();
  await expect(page.getByRole("tabpanel")).toBeVisible();
  await shot(page, "03-evidence");

  await page.goto(`${detail}/review`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.getByRole("radio", { name: /^approve/i }).check();
  await shot(page, "04-partner-review");

  await page.goto(`/control-center/${id}`);
  await page.getByRole("tab", { name: /^trace/i }).click();
  await shot(page, "05-run-trace");
  await page.getByRole("tab", { name: /tool calls/i }).click();
  await shot(page, "06-tool-calls");

  await page.goto("/control-center");
  await expect(page.getByText("Cost per successful task")).toBeVisible();
  await shot(page, "07-control-center");

  await page.goto("/governance");
  await expect(page.getByRole("heading", { level: 1, name: "Governance" })).toBeVisible();
  await shot(page, "08-governance-policy");
  await page.getByRole("tab", { name: /^providers/i }).click();
  await expect(page.getByRole("table", { name: "Provider health and limits" })).toBeVisible();
  await shot(page, "09-governance-providers");

  await page.setViewportSize({ width: 820, height: 1100 });
  await page.goto("/control-center");
  await expect(page.getByText("Cost per successful task")).toBeVisible();
  await shot(page, "10-tablet-control-center");
});
