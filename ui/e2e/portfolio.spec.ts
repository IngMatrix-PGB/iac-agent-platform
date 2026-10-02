import { expect, test, type Page } from "@playwright/test";
import { continueAsOperator } from "./operator";

const INTENT =
  "Intent interpretation is not configured. Set IAC_AGENT_LLM_PROVIDER, IAC_AGENT_LLM_MODEL, and OPENAI_API_KEY.";

const CREATED = "2026-10-01T18:00:00Z";

function detail(
  requestId: string,
  name: string,
  approvalAvailable: boolean,
  workflow: Record<string, unknown>,
) {
  return {
    request_id: requestId,
    outcome: workflow.workflow_status,
    approval_available: approvalAvailable,
    terraform_apply: "not_executed",
    intent: null,
    resolution: { outcome: "resolved", name, components: [] },
    workflow: {
      approval_decision: null,
      error: null,
      pull_request: null,
      ...workflow,
    },
  };
}

const catalog = {
  requests: [
    {
      request_id: "req-order-events",
      created_at: CREATED,
      name: "order-events",
      workflow_status: "awaiting_approval",
      security_status: "pass",
      approval_available: true,
    },
    {
      request_id: "req-public-bucket",
      created_at: CREATED,
      name: "public-uploads",
      workflow_status: "blocked",
      security_status: "block",
      approval_available: false,
    },
    {
      request_id: "req-billing-export",
      created_at: CREATED,
      name: "billing-export",
      workflow_status: "pr_created",
      security_status: "warn",
      approval_available: false,
    },
  ],
};

const details: Record<string, ReturnType<typeof detail>> = {
  "req-order-events": detail("req-order-events", "order-events", true, {
    workflow_status: "awaiting_approval",
    current_stage: "approval",
    security_status: "pass",
    plan: { add: 4, change: 0, destroy: 0, destructive_change_detected: false },
    findings: [
      { policy_id: "SQS_ENCRYPTION", status: "pass", severity: "high" },
      { policy_id: "SQS_QUEUE_VISIBILITY", status: "pass", severity: "medium" },
    ],
  }),
  "req-public-bucket": detail("req-public-bucket", "public-uploads", false, {
    workflow_status: "blocked",
    current_stage: "security_gate",
    security_status: "block",
    plan: { add: 4, change: 0, destroy: 1, destructive_change_detected: true },
    findings: [{ policy_id: "S3_PUBLIC_ACCESS", status: "block", severity: "critical" }],
  }),
  "req-billing-export": detail("req-billing-export", "billing-export", false, {
    workflow_status: "pr_created",
    current_stage: "publish",
    security_status: "pass",
    plan: { add: 4, change: 0, destroy: 0, destructive_change_detected: false },
    findings: [{ policy_id: "S3_ENCRYPTION", status: "pass", severity: "high" }],
    pull_request: { url: "https://github.com/example/platform/pull/7" },
  }),
  "req-lambda-runtime": detail("req-lambda-runtime", "invoice-worker", true, {
    workflow_status: "awaiting_approval",
    current_stage: "approval",
    security_status: "warn",
    plan: { add: 4, change: 0, destroy: 0, destructive_change_detected: false },
    findings: [{ policy_id: "LAMBDA_RUNTIME", status: "warn", severity: "medium" }],
  }),
  "req-retention": detail("req-retention", "retention-archive", true, {
    workflow_status: "awaiting_approval",
    current_stage: "approval",
    security_status: "pass",
    plan: { add: 1, change: 0, destroy: 2, destructive_change_detected: true },
    findings: [{ policy_id: "S3_ENCRYPTION", status: "pass", severity: "high" }],
  }),
  "req-workflow-error": detail("req-workflow-error", "order-events", false, {
    workflow_status: "error",
    current_stage: "terraform_plan",
    security_status: null,
    plan: null,
    findings: [],
    error: { stage: "terraform_plan", error_type: "terraform_failed" },
  }),
};

async function installFixtures(page: Page) {
  await page.route(/^http:\/\/127\.0\.0\.1:5173\/(?:health|ready|api\/)/, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (path === "/health") {
      await route.fulfill({ json: { status: "ok" } });
      return;
    }
    if (path === "/ready") {
      await route.fulfill({ json: { status: "ready" } });
      return;
    }
    if (path === "/api/v1/requests" && method === "GET") {
      await route.fulfill({ json: catalog });
      return;
    }
    if (path === "/api/v1/requests" && method === "POST") {
      await route.fulfill({
        status: 503,
        json: { error: "capability_unavailable", message: INTENT },
      });
      return;
    }
    const match = /^\/api\/v1\/requests\/([^/]+)$/.exec(path);
    if (match && method === "GET") {
      const body = details[decodeURIComponent(match[1])];
      if (!body) {
        await route.fulfill({
          status: 404,
          json: { error: "request_not_found", message: "Request not found." },
        });
        return;
      }
      await route.fulfill({ json: body });
      return;
    }
    await route.continue();
  });
}

async function openCatalog(page: Page) {
  await page.goto("/");
  await continueAsOperator(page);
  await expect(page.getByRole("link", { name: "order-events" })).toBeVisible();
}

async function shot(page: Page, name: string) {
  await page.screenshot({
    path: `test-results/portfolio/${name}.png`,
    animations: "disabled",
  });
}

async function overflow(page: Page) {
  return page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
}

test.beforeEach(async ({ page }) => {
  await installFixtures(page);
});

test("catalog shows resource names ahead of three different gates", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCatalog(page);
  await expect(page.getByRole("heading", { level: 1, name: "IaC Agent" })).toBeVisible();
  await expect(page.getByText("Infrastructure control plane")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Compose" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("Runtime ready")).toBeVisible();
  for (const label of ["Awaiting approval", "Pass", "Blocked", "Block", "Pull request created", "Warn"]) {
    await expect(page.getByText(label).first()).toBeVisible();
  }
  await expect(page.getByText("req-order-events")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Open a saved request" })).toBeVisible();
  await expect(page.getByText("awaiting_approval")).toHaveCount(0);
  expect(await overflow(page)).toBe(false);
  await shot(page, "desktop-catalog");
});

test("pass awaiting approval puts the human boundary on the first screen", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCatalog(page);
  await page.getByRole("link", { name: "order-events" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "order-events" })).toBeVisible();
  await expect(page.getByText("Pass").first()).toBeVisible();
  await expect(page.getByText("Terraform apply was not executed.")).toBeVisible();
  await expect(page.getByText("Add", { exact: true })).toBeVisible();
  await expect(page.getByText("4", { exact: true })).toBeVisible();
  await expect(page.getByText("SQS_ENCRYPTION").first()).toBeVisible();
  await expect(page.getByText("SQS_QUEUE_VISIBILITY").first()).toBeVisible();
  const approve = page.getByRole("button", { name: "Approve" });
  const reject = page.getByRole("button", { name: "Reject request" });
  await expect(approve).toBeVisible();
  await expect(reject).toBeVisible();
  await expect(approve).toHaveClass(/button-primary/);
  await expect(reject).toHaveClass(/button-secondary/);
  await expect(page.getByRole("table", { name: "Security findings" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Security findings" })).toHaveCount(0);
  await expect(page.getByText("awaiting_approval")).toHaveCount(0);
  await expect(page.getByText("pass", { exact: true })).toHaveCount(0);
  expect(await overflow(page)).toBe(false);
  await shot(page, "desktop-pass-awaiting");

  const measured = await page.evaluate(() => {
    function box(element: Element | null) {
      if (!element) {
        return null;
      }
      const rect = element.getBoundingClientRect();
      return {
        top: Math.round(rect.top),
        bottom: Math.round(rect.bottom),
        inFirstScreen: rect.top >= 0 && rect.bottom <= window.innerHeight,
      };
    }
    function text(value: string) {
      const found = [...document.querySelectorAll("body *")].find(
        (element) => element.childNodes.length === 1 && element.textContent === value,
      );
      return box(found ?? null);
    }
    return {
      scrollY: window.scrollY,
      viewport: { width: window.innerWidth, height: window.innerHeight },
      resource: box(document.querySelector("h2")),
      workflow: text("Awaiting approval"),
      security: text("Pass"),
      trust: text("Terraform apply was not executed."),
      plan: box(document.querySelector("#plan-summary-heading")),
      counts: box(document.querySelector(".plan-counts")),
      finding1: text("SQS_ENCRYPTION"),
      finding2: text("SQS_QUEUE_VISIBILITY"),
      approval: box(document.querySelector("#approval-heading")),
      actions: box(document.querySelector(".approval-actions")),
    };
  });
  console.log(`PASS1440 ${JSON.stringify(measured)}`);
  expect(measured.scrollY).toBe(0);
  const box = await page.locator("#approval-heading").boundingBox();
  expect(box).not.toBeNull();
  expect(box!.y + box!.height).toBeLessThanOrEqual(900);

  await approve.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(
    "Approval resumes the workflow and publication may create a pull request. Terraform apply will not run.",
  );
  await expect(page.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
});

test("warn still offers human review", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/requests/req-lambda-runtime");
  await continueAsOperator(page);
  await expect(page.getByRole("heading", { level: 2, name: "invoice-worker" })).toBeVisible();
  await expect(page.getByText("Warn").first()).toBeVisible();
  await expect(page.getByText("Warnings still go to human review.")).toBeVisible();
  await expect(page.getByText("LAMBDA_RUNTIME").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reject request" })).toBeVisible();
  await expect(page.getByText("Approval is closed.")).toHaveCount(0);
  expect(await overflow(page)).toBe(false);
  await shot(page, "desktop-warn-awaiting");
});

test("blocked change closes approval", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCatalog(page);
  await page.getByRole("link", { name: "public-uploads" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "public-uploads" })).toBeVisible();
  await expect(page.getByText("Destructive change detected.")).toBeVisible();
  await expect(page.getByText("Block").first()).toBeVisible();
  await expect(page.getByText("Approval is closed.")).toBeVisible();
  await expect(page.getByText("S3_PUBLIC_ACCESS").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Reject request" })).toHaveCount(0);
  expect(await overflow(page)).toBe(false);
  await shot(page, "desktop-blocked");
});

test("a destructive plan stays open for review when security passed", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/requests/req-retention");
  await continueAsOperator(page);
  await expect(page.getByRole("heading", { level: 2, name: "retention-archive" })).toBeVisible();
  await expect(page.getByText("Destructive change detected.")).toBeVisible();
  await expect(page.getByText("Pass").first()).toBeVisible();
  await expect(page.getByText("Approval is closed.")).toHaveCount(0);
  await expect(page.getByText("Block", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reject request" })).toBeVisible();
  expect(await overflow(page)).toBe(false);
  await shot(page, "desktop-destructive");
});

test("pull request created does not claim an apply", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCatalog(page);
  await page.getByRole("link", { name: "billing-export" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "billing-export" })).toBeVisible();
  await expect(page.getByText("Pull request created").first()).toBeVisible();
  const link = page.getByRole("link", { name: "https://github.com/example/platform/pull/7" });
  await expect(link).toBeVisible();
  await expect(link).toHaveAttribute("href", "https://github.com/example/platform/pull/7");
  await expect(page.getByText("Terraform apply was not executed.")).toBeVisible();
  await expect(page.getByText("deployed", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  expect(await overflow(page)).toBe(false);
  await shot(page, "desktop-pr-created");
});

test("narrow reviews keep stacked findings and wrapped outcomes", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/requests/req-order-events");
  await continueAsOperator(page);
  await expect(page.getByRole("heading", { level: 2, name: "order-events" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Security findings" })).toHaveCount(0);
  const list = page.getByRole("list", { name: "Security findings" });
  await expect(list).toBeVisible();
  await expect(list.getByText("SQS_ENCRYPTION")).toBeVisible();
  await expect(list.getByText("SQS_QUEUE_VISIBILITY")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reject request" })).toBeVisible();
  expect(await overflow(page)).toBe(false);
  await shot(page, "mobile-pass-awaiting");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator("table.findings-table")).toBeHidden();
  await expect(page.getByRole("list", { name: "Security findings" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/requests/req-public-bucket");
  await continueAsOperator(page);
  await expect(page.getByText("Approval is closed.")).toBeVisible();
  await expect(page.getByRole("list", { name: "Security findings" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  expect(await overflow(page)).toBe(false);
  await shot(page, "mobile-blocked");

  await page.goto("/requests/req-billing-export");
  await continueAsOperator(page);
  const link = page.getByRole("link", { name: "https://github.com/example/platform/pull/7" });
  await expect(link).toBeVisible();
  await expect(page.getByText("Terraform apply was not executed.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  const published = await page.evaluate(() => {
    const anchor = document.querySelector("a[href='https://github.com/example/platform/pull/7']");
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
  await shot(page, "mobile-pr-created");
});

test("a fresh tab explains that the secret stays in memory", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await expect(
    page.getByText("This secret stays in this tab's memory. Reloading the page clears it."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible();
  await expect(page.getByLabel("Operator secret")).toHaveValue("");
});

test("a missing interpreter is configuration, not a workflow error", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCatalog(page);
  await page.getByRole("textbox", { name: "Infrastructure request" }).fill("build a worker");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("heading", { name: "Not configured" })).toBeVisible();
  await expect(page.getByText(INTENT)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Workflow error" })).toHaveCount(0);
});

test("a failed plan is a workflow error without approval", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/requests/req-workflow-error");
  await continueAsOperator(page);
  await expect(page.getByRole("heading", { name: "Workflow error" })).toBeVisible();
  await expect(page.getByText("Terraform failed")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  await expect(page.getByRole("table", { name: "Security findings" })).toHaveCount(0);
});
