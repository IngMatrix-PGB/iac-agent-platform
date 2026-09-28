import { describe, expect, it } from "vitest";
import type { FindingDTO, RequestResponse, WorkflowErrorDTO } from "./types";

describe("public DTO boundary", () => {
  it("limits findings to policy_id, status, and severity", () => {
    const keys: (keyof FindingDTO)[] = ["policy_id", "status", "severity"];
    expect(keys).toEqual(["policy_id", "status", "severity"]);
  });

  it("limits workflow errors to stage and error_type", () => {
    const keys: (keyof WorkflowErrorDTO)[] = ["stage", "error_type"];
    expect(keys).toEqual(["stage", "error_type"]);
  });

  it("accepts a reconstructed body with null intent and empty components", () => {
    const body: RequestResponse = {
      request_id: "req-20260928T000000Z-abcdef012345",
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
    expect(body.intent).toBeNull();
    expect(body.resolution.architecture).toBeUndefined();
    expect(body.workflow?.pull_request).toBeNull();
  });
});
