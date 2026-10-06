import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { RequestResponse } from "../api/types";
import { RequestSummary } from "./request-summary";

const body = {
  request_id: "req-1",
  outcome: "awaiting_approval",
  approval_available: true,
  terraform_apply: "not_executed",
  intent: null,
  resolution: {
    outcome: "resolved",
    matched_pattern: null,
    architecture: "API Gateway + Lambda + DynamoDB",
    name: "customer-orders-api",
    components: [],
    field: null,
    reason: null,
    allowed_values: null,
    detail: null,
  },
  workflow: null,
} as unknown as RequestResponse;

describe("request summary", () => {
  it("shows the architecture as a flow under the name", () => {
    render(<RequestSummary body={body} />);
    expect(screen.getByRole("heading", { level: 2, name: "customer-orders-api" })).toBeInTheDocument();
    expect(screen.getByText("API Gateway → Lambda → DynamoDB")).toHaveAttribute(
      "title",
      "API Gateway + Lambda + DynamoDB",
    );
  });

  it("copies the request id", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<RequestSummary body={body} />);
    await user.click(screen.getByRole("button", { name: "Copy request id" }));
    expect(writeText).toHaveBeenCalledWith("req-1");
    expect(await screen.findByRole("status")).toHaveTextContent("copied");
  });
});
