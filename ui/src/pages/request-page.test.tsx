import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient, ClientResult } from "../api/client";
import { ApiClient as LiveApiClient } from "../api/client";
import type { RequestResponse } from "../api/types";
import { App } from "../app";
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
    const user = userEvent.setup();
    const onBack = vi.fn();
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: reloaded });
    render(
      <RequestPage client={clientReturning(getRequest)} requestId="req-1" onBack={onBack} />,
    );
    expect(await screen.findByRole("heading", { level: 2, name: "order-events" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Request review" })).not.toBeInTheDocument();
    expect(screen.getByText("req-1").className).toContain("meta");
    const back = screen.getByRole("link", { name: "Requests" });
    expect(back).toHaveAttribute("href", "/#requests");
    await user.click(back);
    expect(onBack).toHaveBeenCalledOnce();
    const workflow = screen.getByRole("region", { name: "Workflow" });
    expect(within(workflow).getAllByText("Awaiting approval")).toHaveLength(1);
    expect(within(workflow).getAllByText("Pass")).toHaveLength(1);
    expect(screen.queryByText("awaiting_approval")).not.toBeInTheDocument();
    expect(screen.queryByText("pass")).not.toBeInTheDocument();
    expect(screen.getByText("Terraform apply was not executed.")).toBeInTheDocument();
    const plan = screen.getByRole("heading", { name: "Terraform plan summary" });
    const findings = screen.getByRole("table", { name: "Security findings" });
    const approval = screen.getByRole("heading", { name: "Approval decision" });
    expect(plan.compareDocumentPosition(findings) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(findings.compareDocumentPosition(approval) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("Unavailable after reload.")).not.toBeInTheDocument();
    expect(screen.queryByText("Outcome")).not.toBeInTheDocument();
    expect(screen.queryByText("Approval available")).not.toBeInTheDocument();
    expect(screen.queryByText("serverless_worker")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject request" })).toBeInTheDocument();
    expect(getRequest).toHaveBeenCalledWith("req-1");
  });

  it("uses the request id as the heading when the projection has no name", async () => {
    const unnamed: RequestResponse = {
      ...reloaded,
      resolution: { outcome: "resolved", name: null, components: [] },
    };
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: unnamed });
    render(<RequestPage client={clientReturning(getRequest)} requestId="req-1" />);
    expect(await screen.findByRole("heading", { level: 2, name: "req-1" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Request review" })).not.toBeInTheDocument();
    expect(document.querySelector(".meta")).toBeNull();
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
    expect(screen.getAllByText("Pull request created").length).toBeGreaterThan(0);
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
    expect(screen.getAllByText("Rejected").length).toBeGreaterThan(0);
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

  it("clears the in-memory secret when approval is unauthenticated", async () => {
    const user = userEvent.setup();
    const secret = "operator-secret-should-not-leak";
    const decide = vi.fn().mockResolvedValue({
      kind: "http",
      status: 401,
      error: "unauthenticated",
      message: "Authentication is required.",
    } satisfies ClientResult);
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: reloaded });
    const client = clientReturning(getRequest, decide);
    client.health = vi.fn().mockResolvedValue({ kind: "success", httpStatus: 200, status: "ok" });
    client.ready = vi.fn().mockResolvedValue({ kind: "success", httpStatus: 200, status: "ready" });
    client.listRequests = vi.fn();
    render(<App client={client} navigate={vi.fn()} pathname="/requests/req-1" />);
    expect(getRequest).not.toHaveBeenCalled();
    await user.type(screen.getByLabelText("Operator secret"), secret);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(await screen.findByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(decide).toHaveBeenCalledTimes(1);
    expect(decide).toHaveBeenCalledWith("req-1", "approve");
    expect(await screen.findByLabelText("Operator secret")).toHaveValue("");
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
    expect(screen.queryByText("Request not found.")).not.toBeInTheDocument();
    expect(screen.queryByText("rejected")).not.toBeInTheDocument();
    expect(screen.queryByText("pr_created")).not.toBeInTheDocument();
  });

  it("sends the same bearer on the mount read and later polls", async () => {
    vi.useFakeTimers();
    const secret = "operator-secret-should-not-leak";
    const pending: RequestResponse = {
      ...reloaded,
      outcome: "pending",
      approval_available: false,
      workflow: { ...reloaded.workflow!, workflow_status: "pending" },
    };
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pending), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    const client = new LiveApiClient(fetchImpl, { operatorSecret: secret });
    render(<RequestPage client={client} requestId="req-1" />);
    await act(async () => {
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    for (const [url, init] of fetchImpl.mock.calls) {
      expect(String(url)).toBe("/api/v1/requests/req-1");
      expect(String(url)).not.toContain(secret);
      expect(new Headers(init?.headers).get("Authorization")).toBe(`Bearer ${secret}`);
      expect(String(init?.body ?? "")).not.toContain(secret);
    }
    vi.useRealTimers();
  });

  it("stops polling when a poll is unauthenticated", async () => {
    vi.useFakeTimers();
    const pending: RequestResponse = {
      ...reloaded,
      outcome: "pending",
      approval_available: false,
      workflow: { ...reloaded.workflow!, workflow_status: "pending" },
    };
    const getRequest = vi
      .fn()
      .mockResolvedValueOnce({ kind: "success", status: 200, body: pending })
      .mockResolvedValue({
        kind: "http",
        status: 401,
        error: "unauthenticated",
        message: "Authentication is required.",
      });
    const onUnauthenticated = vi.fn();
    render(
      <RequestPage
        client={clientReturning(getRequest)}
        requestId="req-1"
        onUnauthenticated={onUnauthenticated}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(getRequest).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(getRequest).toHaveBeenCalledTimes(2);
    expect(onUnauthenticated).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000 * 3);
    });
    expect(getRequest).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("rejected")).not.toBeInTheDocument();
    expect(screen.queryByText("Request not found.")).not.toBeInTheDocument();
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
    expect(screen.queryByRole("heading", { name: "Request review" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Requests" })).toHaveAttribute("href", "/#requests");
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
