import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { FindingDTO, RequestResponse } from "../api/types";
import { Findings } from "./findings";
import { PlanSummary } from "./plan-summary";
import { RequestSummary } from "./request-summary";
import { WorkflowStatus } from "./workflow-status";

const posted: RequestResponse = {
  request_id: "req-1",
  outcome: "awaiting_approval",
  approval_available: true,
  terraform_apply: "not_executed",
  intent: {
    workload_type: "worker",
    interaction_pattern: "asynchronous",
    capabilities: ["queue_processing"],
  },
  resolution: {
    outcome: "resolved",
    architecture: "serverless_worker",
    name: "order-events",
    matched_pattern: "worker+asynchronous+queue_processing",
    components: [
      { role: "queue", name: "order-events" },
      { role: "function", name: "order-events-fn" },
    ],
  },
  workflow: {
    workflow_status: "awaiting_approval",
    current_stage: "approval",
    security_status: "warn",
    plan: { add: 2, change: 1, destroy: 0, destructive_change_detected: true },
    findings: [{ policy_id: "SQS_ENCRYPTION", status: "warn", severity: "high" }],
    approval_decision: null,
    error: null,
    pull_request: null,
  },
};

function Projection({ body }: { body: RequestResponse }) {
  return (
    <>
      <RequestSummary body={body} />
      <WorkflowStatus body={body} />
      <PlanSummary plan={body.workflow?.plan ?? null} />
      <Findings findings={body.workflow?.findings ?? []} />
    </>
  );
}

describe("request projection", () => {
  it("labels add, change, and destroy and keeps the destructive sentence", () => {
    render(<Projection body={posted} />);
    expect(screen.getByRole("heading", { level: 3, name: "Terraform plan summary" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Add" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Change" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Destroy" })).toBeInTheDocument();
    expect(screen.getByText("Destructive change detected.")).toBeInTheDocument();
    expect(screen.queryByText("aws_sqs_queue.hidden_address")).not.toBeInTheDocument();
  });

  it("shows workflow labels beside the server enums", () => {
    render(<Projection body={posted} />);
    expect(screen.getByRole("heading", { level: 3, name: "Workflow" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Workflow status" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Stage" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Security status" })).toBeInTheDocument();
    expect(screen.getAllByText("awaiting_approval").length).toBeGreaterThan(0);
    expect(screen.getByText("approval")).toBeInTheDocument();
    expect(screen.getAllByText("warn").length).toBeGreaterThan(0);
    expect(screen.getByText("Terraform apply was not executed.")).toBeInTheDocument();
    expect(screen.getByText("Approval available")).toBeInTheDocument();
  });

  it("labels the request id and outcome and still shows the server outcome", () => {
    render(<Projection body={posted} />);
    expect(screen.getByRole("heading", { level: 3, name: "Request" })).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Request id" })).toBeInTheDocument();
    expect(screen.getByText("req-1")).toBeInTheDocument();
    expect(screen.getByRole("term", { name: "Outcome" })).toBeInTheDocument();
    expect(screen.getAllByText("awaiting_approval").length).toBeGreaterThan(0);
  });

  it("renders the public submission fields", () => {
    render(<Projection body={posted} />);
    expect(screen.getByText("req-1")).toBeInTheDocument();
    expect(screen.getAllByText("awaiting_approval").length).toBeGreaterThan(0);
    expect(screen.getByText("approval")).toBeInTheDocument();
    expect(screen.getAllByText("warn").length).toBeGreaterThan(0);
    expect(screen.getByText("serverless_worker")).toBeInTheDocument();
    expect(screen.getAllByText("order-events").length).toBeGreaterThan(0);
    expect(screen.getByText("queue")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("Destructive change detected.")).toBeInTheDocument();
    expect(screen.getByText("SQS_ENCRYPTION")).toBeInTheDocument();
    expect(screen.getByText("Terraform apply was not executed.")).toBeInTheDocument();
    expect(screen.getByText("Approval available")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject request" })).not.toBeInTheDocument();
  });

  it("does not invent fields missing from a reconstructed GET", () => {
    const reloaded: RequestResponse = {
      ...posted,
      intent: null,
      resolution: { outcome: "resolved", name: "order-events", components: [] },
    };
    render(<Projection body={reloaded} />);
    expect(screen.getByText("Unavailable after reload.")).toBeInTheDocument();
    expect(screen.getByText("order-events")).toBeInTheDocument();
    expect(screen.queryByText("serverless_worker")).not.toBeInTheDocument();
    expect(screen.queryByText("queue_processing")).not.toBeInTheDocument();
    expect(screen.queryByText("worker+asynchronous+queue_processing")).not.toBeInTheDocument();
  });

  it("does not render finding resource or message", () => {
    const dirty = [
      {
        policy_id: "SQS_ENCRYPTION",
        status: "pass",
        severity: "low",
        resource: "arn:aws:sqs:us-east-1:123456789012:hidden",
        message: "HIDDEN_FINDING_MESSAGE",
      },
    ] as unknown as FindingDTO[];
    render(<Findings findings={dirty} />);
    expect(screen.getByText("SQS_ENCRYPTION")).toBeInTheDocument();
    expect(screen.queryByText("arn:aws:sqs:us-east-1:123456789012:hidden")).not.toBeInTheDocument();
    expect(screen.queryByText("HIDDEN_FINDING_MESSAGE")).not.toBeInTheDocument();
    expect(screen.queryByText("123456789012")).not.toBeInTheDocument();
  });

  it("renders error stage and type without an error message", () => {
    const body: RequestResponse = {
      ...posted,
      outcome: "error",
      approval_available: false,
      workflow: {
        ...posted.workflow!,
        workflow_status: "error",
        error: {
          stage: "terraform",
          error_type: "RuntimeError",
          message: "HIDDEN_WORKFLOW_ERROR_MESSAGE",
        } as RequestResponse["workflow"] extends infer W
          ? W extends { error: infer E }
            ? E
            : never
          : never,
      },
    };
    render(<WorkflowStatus body={body} />);
    expect(screen.getByText("terraform")).toBeInTheDocument();
    expect(screen.getAllByText("RuntimeError").length).toBeGreaterThan(0);
    expect(screen.queryByText("HIDDEN_WORKFLOW_ERROR_MESSAGE")).not.toBeInTheDocument();
  });

  it("says when no plan summary was returned", () => {
    render(<PlanSummary plan={null} />);
    expect(screen.getByText("No plan summary was returned.")).toBeInTheDocument();
  });

  it("renders only the pull-request URL", () => {
    const body: RequestResponse = {
      ...posted,
      workflow: {
        ...posted.workflow!,
        pull_request: { url: "https://example.invalid/pull/7" },
      },
    };
    render(<WorkflowStatus body={body} />);
    const link = screen.getByRole("link", { name: "https://example.invalid/pull/7" });
    expect(link).toHaveAttribute("href", "https://example.invalid/pull/7");
    expect(screen.queryByText("branch")).not.toBeInTheDocument();
    expect(screen.queryByText("base_branch")).not.toBeInTheDocument();
  });

  it("does not render internal sentinels stuffed beside the public body", () => {
    const dirty = {
      ...posted,
      terraform_source: "module.queue.aws_sqs_queue.this",
      workspace: "/var/lib/iac-agent/workspaces/req-1",
      checkpoint: "checkpoint-body-sentinel",
      owner: "hidden-github-owner",
      repository: "hidden-github-repository",
      token: "ghp_hidden_token_value",
    } as RequestResponse;
    render(<Projection body={dirty} />);
    expect(screen.queryByText("module.queue.aws_sqs_queue.this")).not.toBeInTheDocument();
    expect(screen.queryByText("/var/lib/iac-agent/workspaces/req-1")).not.toBeInTheDocument();
    expect(screen.queryByText("checkpoint-body-sentinel")).not.toBeInTheDocument();
    expect(screen.queryByText("hidden-github-owner")).not.toBeInTheDocument();
    expect(screen.queryByText("hidden-github-repository")).not.toBeInTheDocument();
    expect(screen.queryByText("ghp_hidden_token_value")).not.toBeInTheDocument();
  });
});
