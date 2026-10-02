import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { FindingDTO, RequestResponse } from "../api/types";
import { ApprovalPanel } from "./approval-panel";
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
      <Findings
        findings={body.workflow?.findings ?? []}
        workflowStatus={body.workflow?.workflow_status}
      />
    </>
  );
}

describe("request projection", () => {
  it("names the findings table and keeps only public columns", () => {
    render(<Projection body={posted} />);
    const table = screen.getByRole("table", { name: "Security findings" });
    expect(table).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Policy" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Severity" })).toBeInTheDocument();
    expect(screen.getAllByText("SQS_ENCRYPTION").length).toBeGreaterThan(0);
    expect(screen.queryByRole("columnheader", { name: "Resource" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Message" })).not.toBeInTheDocument();
  });

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
    expect(screen.getAllByText("Awaiting approval").length).toBeGreaterThan(0);
    expect(screen.queryByText("awaiting_approval")).not.toBeInTheDocument();
    expect(screen.getByText("Approval", { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText("Warn").length).toBeGreaterThan(0);
    expect(screen.queryByText("warn")).not.toBeInTheDocument();
    expect(screen.getByText("Terraform apply was not executed.")).toBeInTheDocument();
    expect(screen.queryByText("Approval available")).not.toBeInTheDocument();
  });

  it("labels the request id under the resource heading", () => {
    render(<Projection body={posted} />);
    expect(screen.getByRole("heading", { level: 2, name: "order-events" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Request" })).not.toBeInTheDocument();
    expect(screen.getByText("req-1").className).toContain("meta");
    expect(screen.queryByRole("term", { name: "Outcome" })).not.toBeInTheDocument();
    expect(screen.queryByText("Approval available")).not.toBeInTheDocument();
  });

  it("renders the public submission fields", () => {
    render(<Projection body={posted} />);
    expect(screen.getByText("req-1")).toBeInTheDocument();
    expect(screen.getAllByText("Awaiting approval").length).toBeGreaterThan(0);
    expect(screen.queryByText("awaiting_approval")).not.toBeInTheDocument();
    expect(screen.getByText("Approval", { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText("Warn").length).toBeGreaterThan(0);
    expect(screen.queryByText("warn")).not.toBeInTheDocument();
    expect(screen.getByText("Serverless worker")).toHaveAttribute("title", "serverless_worker");
    expect(screen.queryByText("serverless_worker")).not.toBeInTheDocument();
    expect(screen.getAllByText("order-events").length).toBeGreaterThan(0);
    expect(screen.getByText("queue")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.getByText("Destructive change detected.")).toBeInTheDocument();
    expect(screen.getAllByText("SQS_ENCRYPTION").length).toBeGreaterThan(0);
    expect(screen.getByText("Terraform apply was not executed.")).toBeInTheDocument();
    expect(screen.queryByText("Approval available")).not.toBeInTheDocument();
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
    expect(screen.queryByText("Unavailable after reload.")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "order-events" })).toBeInTheDocument();
    expect(screen.queryByText("serverless_worker")).not.toBeInTheDocument();
    expect(screen.queryByText("queue_processing")).not.toBeInTheDocument();
    expect(screen.queryByText("worker+asynchronous+queue_processing")).not.toBeInTheDocument();
  });

  it("omits checkpoint fields the GET does not know", () => {
    const reloaded: RequestResponse = {
      ...posted,
      intent: null,
      resolution: { outcome: "resolved", name: "order-events", components: [] },
    };
    render(<Projection body={reloaded} />);
    expect(screen.queryByText("Unavailable after reload.")).not.toBeInTheDocument();
    expect(screen.queryByText("serverless_worker")).not.toBeInTheDocument();
    expect(screen.queryByText("queue_processing")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "order-events" })).toBeInTheDocument();
  });

  it("does not warn about destruction when the server flag is false", () => {
    render(
      <PlanSummary
        plan={{ add: 1, change: 0, destroy: 1, destructive_change_detected: false }}
      />,
    );
    expect(screen.getAllByText("1")).toHaveLength(2);
    expect(screen.queryByText("Destructive change detected.")).not.toBeInTheDocument();
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
    expect(screen.getAllByText("SQS_ENCRYPTION").length).toBeGreaterThan(0);
    expect(screen.queryByText("arn:aws:sqs:us-east-1:123456789012:hidden")).not.toBeInTheDocument();
    expect(screen.queryByText("HIDDEN_FINDING_MESSAGE")).not.toBeInTheDocument();
    expect(screen.queryByText("123456789012")).not.toBeInTheDocument();
  });

  it("heads a durable workflow error once", () => {
    const body: RequestResponse = {
      ...posted,
      outcome: "error",
      approval_available: false,
      workflow: {
        ...posted.workflow!,
        workflow_status: "error",
        current_stage: "terraform",
        security_status: null,
        plan: null,
        findings: [],
        error: { stage: "terraform", error_type: "terraform_failed" },
      },
    };
    render(<WorkflowStatus body={body} />);
    expect(screen.getByRole("heading", { name: "Workflow error" })).toBeInTheDocument();
    expect(screen.getAllByText("Terraform")).toHaveLength(1);
    expect(screen.getByText("Terraform failed")).toBeInTheDocument();
    expect(screen.getByTitle("terraform_failed")).toBeInTheDocument();
    expect(screen.queryByText("terraform_failed")).not.toBeInTheDocument();
    expect(screen.queryByText("Error")).not.toBeInTheDocument();
    expect(screen.queryByText("ERROR")).not.toBeInTheDocument();
    expect(screen.queryByText(/Traceback|Exception|checkpoint/)).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Not configured" })).not.toBeInTheDocument();
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
    expect(screen.getByText("Terraform", { exact: true })).toBeInTheDocument();
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

  it("says a warning can still reach a person", () => {
    render(<WorkflowStatus body={posted} />);
    expect(screen.getByText("Warn")).toBeInTheDocument();
    expect(screen.getByText("Warnings still go to human review.")).toBeInTheDocument();
    expect(screen.queryByText("Approval is closed.")).not.toBeInTheDocument();
    expect(screen.queryByText("Pass")).not.toBeInTheDocument();
  });

  it("keeps a pass open for a person without calling it published", () => {
    const passed: RequestResponse = {
      ...posted,
      workflow: { ...posted.workflow!, security_status: "pass" },
    };
    render(
      <>
        <WorkflowStatus body={passed} />
        <ApprovalPanel body={passed} client={{} as never} onResult={vi.fn()} />
      </>,
    );
    expect(screen.getByText("Pass")).toBeInTheDocument();
    expect(screen.getByText("Awaiting approval")).toBeInTheDocument();
    expect(screen.queryByText("Warnings still go to human review.")).not.toBeInTheDocument();
    expect(screen.queryByText("Approval is closed.")).not.toBeInTheDocument();
    expect(screen.getAllByText("Terraform apply was not executed.")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject request" })).toBeInTheDocument();
  });

  it("closes approval on a block without offering a decision", () => {
    const blocked: RequestResponse = {
      ...posted,
      outcome: "blocked",
      approval_available: false,
      workflow: {
        ...posted.workflow!,
        workflow_status: "blocked",
        security_status: "block",
      },
    };
    render(
      <>
        <WorkflowStatus body={blocked} />
        <ApprovalPanel body={blocked} client={{} as never} onResult={vi.fn()} />
      </>,
    );
    expect(screen.getByText("Block")).toBeInTheDocument();
    expect(screen.getByText("Approval is closed.")).toBeInTheDocument();
    expect(screen.queryByText("Warnings still go to human review.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject request" })).not.toBeInTheDocument();
  });

  it("shows a rejection as a completed decision, not a block", () => {
    const rejected: RequestResponse = {
      ...posted,
      outcome: "rejected",
      approval_available: false,
      workflow: {
        ...posted.workflow!,
        workflow_status: "rejected",
        security_status: "pass",
        approval_decision: "reject",
      },
    };
    render(
      <>
        <WorkflowStatus body={rejected} />
        <ApprovalPanel body={rejected} client={{} as never} onResult={vi.fn()} />
      </>,
    );
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("Pass")).toBeInTheDocument();
    expect(screen.queryByText("Approval is closed.")).not.toBeInTheDocument();
    expect(screen.queryByText("Block")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Workflow error" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Not configured" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("keeps a destructive plan separate from a security block", () => {
    render(
      <>
        <PlanSummary plan={posted.workflow?.plan ?? null} />
        <ApprovalPanel body={posted} client={{} as never} onResult={vi.fn()} />
      </>,
    );
    expect(screen.getByText("Destructive change detected.")).toBeInTheDocument();
    expect(screen.queryByText("Approval is closed.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("places the pull request with the no-apply sentence", () => {
    const published: RequestResponse = {
      ...posted,
      approval_available: false,
      workflow: {
        ...posted.workflow!,
        workflow_status: "pr_created",
        security_status: "pass",
        pull_request: { url: "https://example.invalid/pull/7" },
      },
    };
    render(<WorkflowStatus body={published} />);
    expect(screen.getByText("Pull request created")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "https://example.invalid/pull/7" })).toBeInTheDocument();
    expect(screen.getAllByText("Terraform apply was not executed.")).toHaveLength(1);
    expect(screen.queryByText("Warnings still go to human review.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
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
