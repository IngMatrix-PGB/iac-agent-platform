import { describe, expect, it } from "vitest";
import { chipClass, enumCaption, statusLabel } from "./status-label";

describe("statusLabel", () => {
  it("maps the design labels once", () => {
    expect(statusLabel("pass")).toBe("Pass");
    expect(statusLabel("warn")).toBe("Warn");
    expect(statusLabel("block")).toBe("Block");
    expect(statusLabel("awaiting_approval")).toBe("Awaiting approval");
    expect(statusLabel("pr_created")).toBe("Pull request created");
    expect(statusLabel("blocked")).toBe("Blocked");
    expect(statusLabel("error")).toBe("Error");
    expect(statusLabel("rejected")).toBe("Rejected");
    expect(statusLabel("pending")).toBe("Pending");
    expect(statusLabel("running")).toBe("Running");
    expect(statusLabel("approved")).toBe("Approved");
    expect(statusLabel("security_gate")).toBe("Security gate");
    expect(statusLabel("plan_analysis")).toBe("Plan analysis");
    expect(statusLabel("source_control")).toBe("Source control");
    expect(statusLabel("terraform_plan")).toBe("Terraform plan");
    expect(statusLabel("publish")).toBe("Publish");
    expect(statusLabel("high")).toBe("High");
    expect(statusLabel("critical")).toBe("Critical");
  });

  it("does not invent a word for an unknown enum", () => {
    expect(enumCaption("custom_stage")).toBe("Custom stage");
    expect(statusLabel("custom_stage")).toBe("Custom stage");
  });

  it("matches the whole value and leaves the raw string unchanged", () => {
    const raw = "pass";
    expect(statusLabel(raw)).toBe("Pass");
    expect(raw).toBe("pass");
    expect(statusLabel("Approval available")).toBe("Approval available");
    expect(statusLabel("awaiting_approval_extra")).toBe("Awaiting approval extra");
    expect(statusLabel("password")).toBe("Password");
    expect(statusLabel("password")).not.toBe(statusLabel("pass"));
  });

  it("assigns distinct chip classes to pass, warn, and block", () => {
    expect(chipClass("pass")).toBe("chip chip-pass");
    expect(chipClass("warn")).toBe("chip chip-warn");
    expect(chipClass("block")).toBe("chip chip-block");
    expect(chipClass("blocked")).toBe("chip chip-block");
    expect(chipClass("awaiting_approval")).toBe("chip chip-attention");
    expect(chipClass("pr_created")).toBe("chip chip-published");
    expect(chipClass("rejected")).toBe("chip chip-rejected");
    expect(chipClass("pending")).toBe("chip chip-neutral");
    expect(chipClass("running")).toBe("chip chip-neutral");
    expect(chipClass("approved")).toBe("chip chip-neutral");
    expect(chipClass("error")).toBe("chip chip-error");
    expect(chipClass("custom_stage")).toBe("chip");
    expect(chipClass("pass")).not.toBe(chipClass("warn"));
    expect(chipClass("warn")).not.toBe(chipClass("block"));
    expect(chipClass("pr_created")).not.toBe(chipClass("pass"));
  });
});
