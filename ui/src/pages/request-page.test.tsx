import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../api/client";
import type { RequestResponse } from "../api/types";
import { RequestPage } from "./request-page";

const reloaded: RequestResponse = {
  request_id: "req-1",
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
};

function clientReturning(getRequest: ApiClient["getRequest"]): ApiClient {
  return {
    health: vi.fn(),
    ready: vi.fn(),
    submit: vi.fn(),
    getRequest,
    decide: vi.fn(),
  } as unknown as ApiClient;
}

describe("request page", () => {
  it("loads a reconstructed request and does not offer approval actions", async () => {
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: reloaded });
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
    expect(await screen.findByText("Unavailable after reload.")).toBeInTheDocument();
    expect(screen.getAllByText("awaiting_approval").length).toBeGreaterThan(0);
    expect(screen.getByText("order-events")).toBeInTheDocument();
    expect(screen.getByText("SQS_ENCRYPTION")).toBeInTheDocument();
    expect(screen.getByText("Approval available")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject request" })).not.toBeInTheDocument();
    expect(getRequest).toHaveBeenCalledWith("req-1");
  });

  it("shows the API not-found message without inventing a pending request", async () => {
    const getRequest = vi.fn().mockResolvedValue({
      kind: "http",
      status: 404,
      error: "request_not_found",
      message: "Request not found.",
    });
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-missing" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Request not found.");
    expect(screen.queryByText("pending")).not.toBeInTheDocument();
    expect(screen.queryByText("awaiting_approval")).not.toBeInTheDocument();
  });

  it("shows a network failure without a stack", async () => {
    const getRequest = vi.fn().mockResolvedValue({
      kind: "network",
      message: "The API could not be reached.",
    });
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The API could not be reached.");
    expect(screen.queryByText(/ECONNREFUSED/)).not.toBeInTheDocument();
  });
});
