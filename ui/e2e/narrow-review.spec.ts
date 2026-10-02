import { expect, test, type Page } from "@playwright/test";
import { continueAsOperator } from "./operator";

function reviewBody(overrides: Record<string, unknown>) {
  return {
    request_id: "req-review",
    outcome: "awaiting_approval",
    approval_available: true,
    terraform_apply: "not_executed",
    intent: null,
    resolution: { outcome: "resolved", name: "order-events", components: [] },
    workflow: {
      workflow_status: "awaiting_approval",
      current_stage: "approval",
      security_status: "pass",
      plan: { add: 1, change: 0, destroy: 0, destructive_change_detected: false },
      findings: [{ policy_id: "SQS_ENCRYPTION", status: "pass", severity: "high" }],
      approval_decision: null,
      error: null,
      pull_request: null,
    },
    ...overrides,
  };
}

async function openReview(page: Page, requestId: string, body: unknown) {
  await page.route(`**/api/v1/requests/${requestId}`, async (route) => {
    if (route.request().method() !== "GET") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await page.goto(`/requests/${requestId}`);
  await continueAsOperator(page);
}

async function boxes(page: Page) {
  return page.evaluate(() => {
    function box(selector: string) {
      const element = document.querySelector(selector);
      if (!element) {
        return null;
      }
      const rect = element.getBoundingClientRect();
      return { top: Math.round(rect.top), bottom: Math.round(rect.bottom) };
    }
    return {
      viewport: { width: window.innerWidth, height: window.innerHeight },
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      resource: box("h2"),
      workflow: box("#workflow-heading"),
      trust: box("[data-sanity=trust]"),
      plan: box("#plan-summary-heading"),
      counts: box(".plan-counts"),
      findings: box("[data-sanity=findings]"),
      approval: box("#approval-heading"),
      actions: box(".approval-actions"),
    };
  });
}

test("wide and narrow findings stay mutually exclusive", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await continueAsOperator(page);
  await page.getByRole("textbox", { name: "Infrastructure request" }).fill("build a worker");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "order-events" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Security findings" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Security findings" })).toHaveCount(0);
  await page.getByText("Terraform apply was not executed.").evaluate((element) => {
    element.setAttribute("data-sanity", "trust");
  });
  await page.locator("text=SQS_ENCRYPTION").evaluateAll((elements) => {
    const visible = elements.find((element) => element.getBoundingClientRect().height > 0);
    visible?.setAttribute("data-sanity", "findings");
  });
  const wide = await boxes(page);
  console.log(`PASS1440 ${JSON.stringify(wide)}`);
  expect(wide.overflow).toBe(false);

  await page.setViewportSize({ width: 700, height: 900 });
  await expect(page.getByRole("table", { name: "Security findings" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Security findings" })).toHaveCount(0);

  await page.setViewportSize({ width: 600, height: 900 });
  await expect(page.getByRole("table", { name: "Security findings" })).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Security findings" })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 800 });
  await expect(page.getByRole("table", { name: "Security findings" })).toHaveCount(0);
  const list = page.getByRole("list", { name: "Security findings" });
  await expect(list).toBeVisible();
  await expect(list.getByText("SQS_ENCRYPTION")).toBeVisible();
  await expect(list.getByText("Pass")).toBeVisible();
  await expect(list.getByText("High")).toBeVisible();
  await expect(list.getByText("Policy")).toBeVisible();
  await expect(list.getByText("Status")).toBeVisible();
  await expect(list.getByText("Severity")).toBeVisible();
  const approve = page.getByRole("button", { name: "Approve" });
  const reject = page.getByRole("button", { name: "Reject request" });
  await expect(approve).toBeVisible();
  await expect(reject).toBeVisible();
  const approveBox = await approve.boundingBox();
  const rejectBox = await reject.boundingBox();
  expect(approveBox && approveBox.width).toBeGreaterThan(200);
  expect(rejectBox && rejectBox.width).toBeGreaterThan(200);
  expect((await boxes(page)).overflow).toBe(false);

  await approve.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Terraform apply will not run");
  await page.getByRole("button", { name: "Confirm approval" }).click();
  const link = page.getByRole("link", { name: "https://example.invalid/pull/7" });
  await expect(link).toBeVisible();
  await expect(page.getByText("Terraform apply was not executed.")).toBeVisible();
  const published = await page.evaluate(() => {
    const anchor = document.querySelector("a[href='https://example.invalid/pull/7']");
    const rect = anchor?.getBoundingClientRect();
    return {
      overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
      prWidth: rect ? Math.round(rect.width) : null,
      clientWidth: document.documentElement.clientWidth,
    };
  });
  console.log(`PR390 ${JSON.stringify(published)}`);
  expect(published.overflow).toBe(false);
  expect(published.prWidth).toBeLessThan(published.clientWidth);
});

test("a destructive plan and a workflow error stay readable at 390", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const longPolicy = "SQS_ENCRYPTION_POLICY_IDENTIFIER_THAT_HAS_TO_WRAP_INSIDE_A_NARROW_REVIEW";
  await openReview(
    page,
    "req-destructive",
    reviewBody({
      workflow: {
        workflow_status: "awaiting_approval",
        current_stage: "approval",
        security_status: "pass",
        plan: { add: 1, change: 0, destroy: 1, destructive_change_detected: true },
        findings: [{ policy_id: longPolicy, status: "warn", severity: "high" }],
        approval_decision: null,
        error: null,
        pull_request: null,
      },
    }),
  );
  const warning = page.getByText("Destructive change detected.");
  await expect(warning).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
  await expect(page.getByText("Approval is closed.")).toHaveCount(0);
  await expect(page.getByRole("list", { name: "Security findings" }).getByText(longPolicy)).toBeVisible();
  await expect(page.getByText("Block", { exact: true })).toHaveCount(0);
  const destructive = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  }));
  console.log(`DESTRUCTIVE390 ${JSON.stringify(destructive)}`);
  expect(destructive.overflow).toBe(false);

  await openReview(
    page,
    "req-failed",
    reviewBody({
      request_id: "req-failed",
      outcome: "error",
      approval_available: false,
      workflow: {
        workflow_status: "error",
        current_stage: "terraform",
        security_status: null,
        plan: null,
        findings: [],
        approval_decision: null,
        error: { stage: "terraform", error_type: "terraform_failed" },
        pull_request: null,
      },
    }),
  );
  await expect(page.getByRole("heading", { name: "Workflow error" })).toBeVisible();
  await expect(page.getByText("Terraform failed")).toBeVisible();
  await expect(page.getByText("Error", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expect(page.getByRole("table", { name: "Security findings" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Not configured" })).toHaveCount(0);
  const failed = await page.evaluate(() => ({
    overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth,
  }));
  console.log(`ERROR390 ${JSON.stringify(failed)}`);
  expect(failed.overflow).toBe(false);
});
