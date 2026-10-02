import { expect, test } from "@playwright/test";
import { continueAsOperator, OPERATOR_SECRET } from "./operator";

test("approval conflict replaces the view", async ({ page }) => {
  const approvals: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/approval")) {
      approvals.push(request.postData() ?? "");
      expect(request.headers().authorization).toBe(`Bearer ${OPERATOR_SECRET}`);
      expect(request.url()).not.toContain(OPERATOR_SECRET);
    }
  });
  await page.goto("/");
  await continueAsOperator(page);
  await page.getByRole("textbox", { name: "Infrastructure request" }).fill("conflict please");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByText("Awaiting approval").first()).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await page.getByRole("button", { name: "Confirm approval" }).click();
  await expect(page.getByText("This request cannot accept that decision.")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Request review" })).toBeVisible();
  await expect(page.getByText("Rejected").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
  expect(approvals).toEqual([JSON.stringify({ decision: "approve" })]);
  await expect(page.getByText(OPERATOR_SECRET)).toHaveCount(0);
});
