import type { Page } from "@playwright/test";

export const OPERATOR_SECRET = "test-operator-secret";

export async function continueAsOperator(page: Page, secret = OPERATOR_SECRET): Promise<void> {
  await page.getByLabel("Operator secret").fill(secret);
  await page.getByRole("button", { name: "Continue" }).click();
}
