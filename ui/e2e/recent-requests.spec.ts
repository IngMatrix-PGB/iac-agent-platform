import { expect, test } from "@playwright/test";
import { continueAsOperator, OPERATOR_SECRET } from "./operator";

test("a recent request opens the authoritative review", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "IaC Agent" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Process status" })).toBeVisible();
  await expect(page.getByLabel("Operator secret")).toBeVisible();
  await expect(page.getByLabel("Operator secret")).toHaveAttribute("type", "password");
  await expect(page.getByRole("heading", { name: "Recent requests" })).toHaveCount(0);
  await expect(page.getByText("req-indexed")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Request review" })).toHaveCount(0);
  const anonymousFits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(anonymousFits).toBe(true);

  await continueAsOperator(page);
  await expect(page.getByRole("heading", { name: "New request" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Open a saved request" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recent requests" })).toBeVisible();
  await expect(page.getByRole("link", { name: "req-indexed" })).toBeVisible();
  await expect(page.getByText("Awaiting approval").first()).toBeVisible();
  await expect(page.getByText("Pass").first()).toBeVisible();
  await expect(page.getByText("orders")).toBeVisible();
  await expect(page.getByText("2026-09-29T00:00:00.000000Z")).toBeVisible();
  await expect(page.getByText("Approval available")).toBeVisible();
  await expect(page.getByText(OPERATOR_SECRET)).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Terraform plan summary" })).toHaveCount(0);
  await expect(page.getByRole("table", { name: "Security findings" })).toHaveCount(0);
  await expect(page.getByText("arn:aws:sqs:us-east-1:123456789012:hidden")).toHaveCount(0);
  await expect(page.getByText("HIDDEN_FINDING_MESSAGE")).toHaveCount(0);
  await expect(page.getByText("aws_sqs_queue.hidden_address")).toHaveCount(0);
  await expect(page.getByText("example-owner")).toHaveCount(0);
  await expect(page.getByText("example-repository")).toHaveCount(0);
  await expect(page.getByText("ghp_exampleTokenShouldNeverRender")).toHaveCount(0);
  const storage = await page.evaluate(() => ({
    local: window.localStorage.length,
    session: window.sessionStorage.length,
    cookie: document.cookie,
  }));
  expect(storage).toEqual({ local: 0, session: 0, cookie: "" });
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(fits).toBe(true);

  const detail = page.waitForRequest(
    (request) =>
      request.method() === "GET" && request.url().endsWith("/api/v1/requests/req-indexed"),
  );
  await page.getByRole("link", { name: "req-indexed" }).click();
  const detailRequest = await detail;
  expect(detailRequest.headers().authorization).toBe(`Bearer ${OPERATOR_SECRET}`);
  expect(detailRequest.url()).not.toContain(OPERATOR_SECRET);
  await expect(page).toHaveURL(/\/requests\/req-indexed$/);
  expect(page.url()).not.toContain(OPERATOR_SECRET);
  await expect(page.getByRole("heading", { name: "Request review" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Terraform plan summary" })).toBeVisible();
  await expect(page.locator("table.findings-table")).toBeHidden();
  await expect(page.locator(".finding-stack")).toBeVisible();
  await expect(page.getByText("arn:aws:sqs:us-east-1:123456789012:hidden")).toHaveCount(0);
  await expect(page.getByText("HIDDEN_FINDING_MESSAGE")).toHaveCount(0);
  await expect(page.getByText("aws_sqs_queue.hidden_address")).toHaveCount(0);
  await expect(page.getByText(OPERATOR_SECRET)).toHaveCount(0);
});

test("an invalid operator secret returns to the credential field", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  const wrong = "wrong-operator-secret";
  await continueAsOperator(page, wrong);
  await expect(page.getByLabel("Operator secret")).toHaveValue("");
  await expect(page.getByText(wrong)).toHaveCount(0);
  await expect(page.getByText(OPERATOR_SECRET)).toHaveCount(0);
  await expect(page.getByText("Request not found.")).toHaveCount(0);
  await expect(page.getByText("awaiting_approval")).toHaveCount(0);
  await expect(page.getByText("rejected")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Recent requests" })).toHaveCount(0);
});

test("reloading a request url drops the credential until it is entered again", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const detailGets: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "GET" && request.url().includes("/api/v1/requests/req-indexed")) {
      detailGets.push(request.headers().authorization ?? "");
    }
  });
  await page.goto("/requests/req-indexed");
  await expect(page.getByLabel("Operator secret")).toHaveValue("");
  await expect(page.getByRole("heading", { name: "Request review" })).toHaveCount(0);
  await expect(page.getByText("Request not found.")).toHaveCount(0);
  await expect(page.getByText("Loading request.")).toHaveCount(0);
  expect(detailGets).toEqual([]);

  await page.reload();
  await expect(page.getByLabel("Operator secret")).toHaveValue("");
  expect(detailGets).toEqual([]);
  await expect(page.getByText("req-indexed")).toHaveCount(0);

  await continueAsOperator(page);
  await expect(page.getByText("orders")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Request review" })).toBeVisible();
  expect(detailGets.length).toBeGreaterThan(0);
  expect(detailGets.every((authorization) => authorization === `Bearer ${OPERATOR_SECRET}`)).toBe(
    true,
  );
  expect(page.url()).not.toContain(OPERATOR_SECRET);
  await expect(page.getByText(OPERATOR_SECRET)).toHaveCount(0);
});
