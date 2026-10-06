import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { WorkflowDTO } from "../api/types";
import { Pipeline } from "./pipeline";

function workflow(overrides: Partial<WorkflowDTO>): WorkflowDTO {
  return { workflow_status: "running", findings: [], ...overrides };
}

function states(): Record<string, string | null> {
  const steps = screen.getByRole("list", { name: "Workflow pipeline" }).querySelectorAll("li");
  return Object.fromEntries(
    Array.from(steps).map((step) => [step.firstChild?.textContent ?? "", step.getAttribute("data-state")]),
  );
}

describe("pipeline", () => {
  it("renders nothing without a workflow", () => {
    const { container } = render(<Pipeline workflow={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("marks the human step current and keeps a gate warning visible while awaiting approval", () => {
    render(
      <Pipeline
        workflow={workflow({
          workflow_status: "awaiting_approval",
          current_stage: "approval",
          security_status: "warn",
        })}
      />,
    );
    expect(states()).toEqual({
      intent: "done",
      resolve: "done",
      render: "done",
      plan: "done",
      policy: "done",
      gate: "warn",
      human: "current",
      pr: "todo",
    });
    expect(screen.getByText("human").closest("li")).toHaveAttribute("aria-current", "step");
  });

  it("stops at the gate when the security gate blocks", () => {
    render(<Pipeline workflow={workflow({ workflow_status: "blocked", security_status: "block" })} />);
    expect(states().gate).toBe("stopped");
    expect(states().human).toBe("todo");
  });

  it("stops at the failing stage on error", () => {
    render(
      <Pipeline
        workflow={workflow({
          workflow_status: "error",
          error: { stage: "terraform", error_type: "TerraformError" },
        })}
      />,
    );
    expect(states().plan).toBe("stopped");
    expect(states().policy).toBe("todo");
  });

  it("completes every step once the pull request exists", () => {
    render(<Pipeline workflow={workflow({ workflow_status: "pr_created", security_status: "pass" })} />);
    expect(new Set(Object.values(states()))).toEqual(new Set(["done"]));
  });
});
