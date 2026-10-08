import { expect, test, type Page } from "@playwright/test";

type Role = "Partner" | "Analyst" | "Admin" | "Auditor";

async function signInAs(page: Page, user: string, roles: Role[]) {
  await page.addInitScript(
    ([key, value]) => window.localStorage.setItem(key as string, value as string),
    ["consultai.devIdentity", JSON.stringify({ user, roles })],
  );
}

/** Submit the UAE example and wait until the run pauses for a partner. Returns the engagement's address. */
async function startUaeEngagement(page: Page) {
  await page.goto("/engagements/new");
  await page.getByRole("button", { name: /use the uae example/i }).click();
  await page.getByRole("button", { name: /start engagement/i }).click();
  await page.waitForURL(/\/engagements\/wf_/);
  await expect(page.getByText("Waiting for a partner's decision")).toBeVisible();
  return new URL(page.url()).pathname;
}

async function decide(page: Page, path: string, decision: RegExp, reason: string, confirm: string) {
  await page.getByRole("link", { name: /review and decide/i }).click();
  await page.waitForURL(`**${path}/review`);
  await page.getByRole("radio", { name: decision }).check();
  if (reason) await page.getByLabel(/^reason/i).fill(reason);
  await page.getByRole("button", { name: /review decision/i }).click();
  await page.getByRole("dialog").getByRole("button", { name: confirm }).click();
  await expect(page.getByText("Decision recorded")).toBeVisible();
}

test.describe("submit, watch, decide", () => {
  test("a partner approves: the run completes and a report appears", async ({ page }) => {
    await signInAs(page, "pat", ["Partner"]);
    const path = await startUaeEngagement(page);

    // The pipeline shows the Guardian's reasons for pausing, and evidence is inspectable.
    await expect(page.getByRole("heading", { name: "Why this needs a partner" })).toHaveCount(0);
    await page.getByRole("tab", { name: /evidence/i }).click();
    await expect(page.getByRole("table").first()).toBeVisible();

    await decide(page, path, /^approve/i, "Sources check out.", "Approve");
    await expect(page.getByText("Completed", { exact: true }).first()).toBeVisible();
    await page.getByRole("tab", { name: /report/i }).click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  });

  test("a partner rejects: the run ends without a report", async ({ page }) => {
    await signInAs(page, "pat", ["Partner"]);
    const path = await startUaeEngagement(page);
    await decide(page, path, /^reject/i, "Payback is too long.", "Reject");
    await expect(page.getByText("Rejected by a partner")).toBeVisible();
  });

  test("a partner modifies the rationale and the change is recorded", async ({ page }) => {
    await signInAs(page, "pat", ["Partner"]);
    const path = await startUaeEngagement(page);
    await page.getByRole("link", { name: /review and decide/i }).click();
    await page.getByRole("radio", { name: /^modify/i }).check();
    await page.getByRole("textbox", { name: "Rationale" }).fill("Lower the growth assumption until diligence is done.");
    await page.getByLabel(/^reason/i).fill("Diligence is outstanding.");
    await page.getByRole("button", { name: /review decision/i }).click();
    await page.getByRole("dialog").getByRole("button", { name: "Approve with changes" }).click();
    await expect(page.getByText("Decision recorded")).toBeVisible();
    await page.goto(`${path}/review`);
    await expect(page.getByText(/diligence is outstanding/i).first()).toBeVisible();
  });

  test("an analyst can watch and read but cannot decide", async ({ browser, page }) => {
    await signInAs(page, "pat", ["Partner"]);
    const path = await startUaeEngagement(page);

    const ctx = await browser.newContext();
    const analyst = await ctx.newPage();
    await signInAs(analyst, "ann", ["Analyst"]);
    await analyst.goto(path);
    await expect(analyst.getByText("Waiting for a partner's decision")).toBeVisible();
    await analyst.goto(`${path}/review`);
    await expect(analyst.getByRole("radio", { name: /approve/i })).toHaveCount(0);
    await ctx.close();
  });
});

test.describe("control center and governance", () => {
  test("a finished run can be inspected: trace, tool calls, cost and scores", async ({ page }) => {
    await signInAs(page, "pat", ["Partner"]);
    const path = await startUaeEngagement(page);
    const id = path.split("/").pop();
    await page.goto(`/control-center/${id}`);
    for (const tab of [/^trace/i, /tool calls/i, /^guardian/i, /^cost/i, /^quality/i]) {
      await page.getByRole("tab", { name: tab }).click();
      await expect(page.getByRole("tabpanel")).toBeVisible();
    }
  });

  test("an admin sees governance; an analyst does not", async ({ browser, page }) => {
    await signInAs(page, "ada", ["Admin"]);
    await page.goto("/governance");
    await expect(page.getByRole("heading", { level: 1, name: "Governance" })).toBeVisible();
    await page.getByRole("tab", { name: /^tools/i }).click();
    await expect(page.getByRole("table", { name: "Tool registry" })).toBeVisible();

    const ctx = await browser.newContext();
    const analyst = await ctx.newPage();
    await signInAs(analyst, "ann", ["Analyst"]);
    await analyst.goto("/governance");
    await expect(analyst.getByText("You do not have access to this page")).toBeVisible();
    await ctx.close();
  });
});

test.describe("responsive layout @layout", () => {
  test("pages fit a tablet without sideways page scrolling", async ({ page }) => {
    await signInAs(page, "ada", ["Admin", "Partner"]);
    for (const route of ["/", "/engagements", "/engagements/new", "/control-center", "/governance"]) {
      await page.goto(route);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${route} scrolls sideways`).toBeLessThanOrEqual(0);
    }
  });
});
