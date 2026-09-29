import { expect, test } from "@playwright/test";

test("a recent request opens the authoritative review", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "New request" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Open a saved request" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Recent requests" })).toBeVisible();
  await expect(page.getByRole("link", { name: "req-indexed" })).toBeVisible();
  await expect(page.getByText("awaiting_approval").first()).toBeVisible();
  await expect(page.getByText("pass").first()).toBeVisible();
  await expect(page.getByText("orders")).toBeVisible();
  await expect(page.getByText("2026-09-29T00:00:00.000000Z")).toBeVisible();
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
  }));
  expect(storage).toEqual({ local: 0, session: 0 });
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  );
  expect(fits).toBe(true);

  await page.getByRole("link", { name: "req-indexed" }).click();
  await expect(page).toHaveURL(/\/requests\/req-indexed$/);
  await expect(page.getByRole("heading", { name: "Request review" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Terraform plan summary" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Security findings" })).toBeVisible();
  await expect(page.getByText("arn:aws:sqs:us-east-1:123456789012:hidden")).toHaveCount(0);
  await expect(page.getByText("HIDDEN_FINDING_MESSAGE")).toHaveCount(0);
  await expect(page.getByText("aws_sqs_queue.hidden_address")).toHaveCount(0);
});
