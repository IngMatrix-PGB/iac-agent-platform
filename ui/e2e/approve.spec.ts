import { expect, test } from "@playwright/test";

test("approve publishes the pull request url", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "IaC Agent Platform" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "New request" })).toBeVisible();
  await page.getByRole("textbox", { name: "Infrastructure request" }).fill(
    "build a worker that processes a queue and stores results",
  );
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("heading", { name: "Request review" })).toBeVisible();
  await expect(page.getByText("req-browser")).toBeVisible();
  await expect(page.getByText("awaiting_approval").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "Terraform plan summary" })).toBeVisible();
  await expect(page.getByText("Add", { exact: true })).toBeVisible();
  await expect(page.getByText("1", { exact: true })).toBeVisible();
  await expect(page.getByText("Change", { exact: true })).toBeVisible();
  await expect(page.getByText("0", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Destroy", { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "Security findings" })).toBeVisible();
  await expect(page.getByText("SQS_ENCRYPTION")).toBeVisible();
  await expect(page.getByText("arn:aws:sqs:us-east-1:123456789012:hidden")).toHaveCount(0);
  await expect(page.getByText("HIDDEN_FINDING_MESSAGE")).toHaveCount(0);
  await expect(page.getByText("aws_sqs_queue.hidden_address")).toHaveCount(0);
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByText("pr_created").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "https://example.invalid/pull/7" })).toBeVisible();
});
