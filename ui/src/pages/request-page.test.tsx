import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient, ClientResult } from "../api/client";
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

function clientReturning(
  getRequest: ApiClient["getRequest"],
  decide: ApiClient["decide"] = vi.fn(),
): ApiClient {
  return {
    health: vi.fn(),
    ready: vi.fn(),
    submit: vi.fn(),
    getRequest,
    decide,
  } as unknown as ApiClient;
}

describe("request page", () => {
  it("loads a reconstructed request and offers approval when the server allows it", async () => {
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: reloaded });
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
    expect(await screen.findByText("Unavailable after reload.")).toBeInTheDocument();
    expect(screen.getAllByText("awaiting_approval").length).toBeGreaterThan(0);
    expect(screen.getByText("order-events")).toBeInTheDocument();
    expect(screen.getByText("SQS_ENCRYPTION")).toBeInTheDocument();
    expect(screen.getByText("Approval available")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject request" })).toBeInTheDocument();
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

  it("renders the server body after approve and hides the panel", async () => {
    const user = userEvent.setup();
    const published: RequestResponse = {
      ...reloaded,
      outcome: "pr_created",
      approval_available: false,
      workflow: {
        ...reloaded.workflow!,
        workflow_status: "pr_created",
        approval_decision: "approve",
        pull_request: { url: "https://example.invalid/pull/7" },
      },
    };
    const decide = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: published });
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: reloaded });
    render(<RequestPage client={clientReturning(getRequest, decide)} requestId="req-1" />);
    await user.click(await screen.findByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(await screen.findByRole("link", { name: "https://example.invalid/pull/7" })).toHaveAttribute(
      "href",
      "https://example.invalid/pull/7",
    );
    expect(screen.getAllByText("pr_created").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("replaces the view with the conflict request", async () => {
    const user = userEvent.setup();
    const rejected: RequestResponse = {
      ...reloaded,
      outcome: "rejected",
      approval_available: false,
      workflow: {
        ...reloaded.workflow!,
        workflow_status: "rejected",
        approval_decision: "reject",
      },
    };
    const decide = vi.fn().mockResolvedValue({
      kind: "http",
      status: 409,
      error: "approval_conflict",
      message: "This request cannot accept that decision.",
      request: rejected,
    } satisfies ClientResult);
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: reloaded });
    render(<RequestPage client={clientReturning(getRequest, decide)} requestId="req-1" />);
    await user.click(await screen.findByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(await screen.findByText("This request cannot accept that decision.")).toBeInTheDocument();
    expect(screen.getAllByText("rejected").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("polls pending twelve times and then offers refresh", async () => {
    vi.useFakeTimers();
    const pending: RequestResponse = {
      ...reloaded,
      outcome: "pending",
      approval_available: false,
      workflow: { ...reloaded.workflow!, workflow_status: "pending" },
    };
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: pending });
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(getRequest).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(getRequest).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000 * 11);
    });
    expect(getRequest).toHaveBeenCalledTimes(13);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(getRequest).toHaveBeenCalledTimes(13);
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("does not poll awaiting approval", async () => {
    vi.useFakeTimers();
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: reloaded });
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(getRequest).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(getRequest).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("announces a loading status until the server body arrives", async () => {
    let resolveGet: (value: ClientResult) => void = () => {};
    const pending = new Promise<ClientResult>((resolve) => {
      resolveGet = resolve;
    });
    const getRequest = vi.fn().mockReturnValue(pending);
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
    expect(screen.getByRole("heading", { level: 2, name: "Request review" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading request.");
    resolveGet({ kind: "success", status: 200, body: reloaded });
    expect(await screen.findByText("req-1")).toBeInTheDocument();
    expect(screen.queryByText("Loading request.")).not.toBeInTheDocument();
    expect(screen.queryByText("Checking this request.")).not.toBeInTheDocument();
  });

  it("announces polling only for a pollable status and stops after the budget", async () => {
    vi.useFakeTimers();
    const pendingBody: RequestResponse = {
      ...reloaded,
      outcome: "pending",
      approval_available: false,
      workflow: { ...reloaded.workflow!, workflow_status: "pending" },
    };
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: pendingBody });
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByRole("status")).toHaveTextContent("Checking this request.");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000 * 13);
    });
    expect(getRequest).toHaveBeenCalledTimes(13);
    expect(screen.getByText("Automatic checks stopped.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
    expect(screen.queryByText("Checking this request.")).not.toBeInTheDocument();
    vi.useRealTimers();
  });
});
