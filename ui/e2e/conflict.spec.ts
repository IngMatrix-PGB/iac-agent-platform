import { expect, test } from "@playwright/test";

test("approval conflict replaces the view with the rejected request", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("textbox", { name: "Infrastructure request" }).fill("conflict please");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByText("awaiting_approval").first()).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByText("This request cannot accept that decision.")).toBeVisible();
  await expect(page.getByText("rejected").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
});
