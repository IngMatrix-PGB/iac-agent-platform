import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ClientResult } from "../api/client";
import { ApiClient } from "../api/client";
import type { RequestResponse } from "../api/types";
import { ApprovalPanel } from "./approval-panel";

function body(approvalAvailable: boolean): RequestResponse {
  return {
    request_id: "req-1",
    outcome: approvalAvailable ? "awaiting_approval" : "blocked",
    approval_available: approvalAvailable,
    terraform_apply: "not_executed",
    intent: null,
    resolution: { outcome: "resolved", name: "order-events" },
    workflow: {
      workflow_status: approvalAvailable ? "awaiting_approval" : "blocked",
      findings: [],
      plan: null,
      error: null,
      pull_request: null,
      approval_decision: null,
    },
  };
}

function clientWith(decide: ApiClient["decide"]): ApiClient {
  return {
    health: vi.fn(),
    ready: vi.fn(),
    submit: vi.fn(),
    getRequest: vi.fn(),
    decide,
  } as unknown as ApiClient;
}

describe("approval panel", () => {
  it("moves focus into the dialog and explains that reject is immediate", async () => {
    const user = userEvent.setup();
    const decide = vi.fn();
    render(<ApprovalPanel body={body(true)} client={clientWith(decide)} onResult={vi.fn()} />);
    expect(
      screen.getByText("Reject sends immediately and does not ask for confirmation."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toHaveClass("button-primary");
    expect(screen.getByRole("button", { name: "Reject request" })).toHaveClass("button-secondary");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", {
      name: "Approval resumes the workflow and publication may create a pull request. Terraform apply will not run.",
    });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Confirm approval" })).toHaveClass("button-primary");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass("button-secondary");
    expect(decide).not.toHaveBeenCalled();
  });

  it("hides controls when approval is not available", () => {
    render(
      <ApprovalPanel body={body(false)} client={clientWith(vi.fn())} onResult={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject request" })).not.toBeInTheDocument();
  });

  it("requires confirmation before approve and sends nothing on cancel", async () => {
    const user = userEvent.setup();
    const decide = vi.fn();
    render(<ApprovalPanel body={body(true)} client={clientWith(decide)} onResult={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(decide).not.toHaveBeenCalled();
    expect(
      screen.getByText(
        "Approval resumes the workflow and publication may create a pull request. Terraform apply will not run.",
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(decide).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Approve" })).toHaveFocus();
  });

  it("disables controls while approve is in flight and does not invent status", async () => {
    const user = userEvent.setup();
    let resolveDecide: (value: ClientResult) => void = () => {};
    const pending = new Promise<ClientResult>((resolve) => {
      resolveDecide = resolve;
    });
    const decide = vi.fn().mockReturnValue(pending);
    const onResult = vi.fn();
    render(<ApprovalPanel body={body(true)} client={clientWith(decide)} onResult={onResult} />);
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await user.click(screen.getByRole("button", { name: "Confirm approval" }));
    expect(decide).toHaveBeenCalledTimes(1);
    expect(decide).toHaveBeenCalledWith("req-1", "approve");
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject request" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Confirm approval" })).toBeDisabled();
    const created: RequestResponse = {
      ...body(false),
      outcome: "pr_created",
      workflow: {
        workflow_status: "pr_created",
        findings: [],
        plan: null,
        error: null,
        pull_request: { url: "https://example.invalid/pull/7" },
        approval_decision: "approve",
      },
    };
    resolveDecide({ kind: "success", status: 200, body: created });
    await waitFor(() => expect(onResult).toHaveBeenCalledWith({ kind: "success", status: 200, body: created }));
    expect(screen.queryByText("approved")).not.toBeInTheDocument();
    expect(screen.queryByText("pr_created")).not.toBeInTheDocument();
  });

  it("rejects immediately without a dialog", async () => {
    const user = userEvent.setup();
    const decide = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: body(false) });
    render(<ApprovalPanel body={body(true)} client={clientWith(decide)} onResult={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Reject request" }));
    expect(decide).toHaveBeenCalledWith("req-1", "reject");
    expect(
      screen.queryByText(
        "Approval resumes the workflow and publication may create a pull request. Terraform apply will not run.",
      ),
    ).not.toBeInTheDocument();
  });
});
