import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AuthoritativeValue } from "./authoritative-value";
import { enumCaption } from "./status-label";

describe("authoritative value", () => {
  it("shows the human label once and keeps the enum on the title", () => {
    render(
      <dl>
        <AuthoritativeValue label="Workflow status" value="awaiting_approval" />
      </dl>,
    );
    const label = screen.getByText("Awaiting approval");
    expect(screen.getByRole("term", { name: "Workflow status" })).toBeInTheDocument();
    expect(label).toHaveAttribute("title", "awaiting_approval");
    expect(label).toHaveClass("chip", "chip-attention");
    expect(screen.queryByText("awaiting_approval")).not.toBeInTheDocument();
  });

  it("uses the publication label rather than the mechanical caption", () => {
    expect(enumCaption("pr_created")).toBe("Pr created");
    render(
      <dl>
        <AuthoritativeValue label="Workflow status" value="pr_created" />
      </dl>,
    );
    expect(screen.getByText("Pull request created")).toHaveAttribute("title", "pr_created");
    expect(screen.queryByText("pr_created")).not.toBeInTheDocument();
    expect(screen.queryByText("Pr created")).not.toBeInTheDocument();
  });

  it.each([
    ["pass", "Pass", "chip-pass"],
    ["warn", "Warn", "chip-warn"],
    ["block", "Block", "chip-block"],
  ])("shows %s once as %s", (value, label, chip) => {
    render(
      <dl>
        <AuthoritativeValue label="Security status" value={value} />
      </dl>,
    );
    const node = screen.getByText(label);
    expect(node).toHaveClass("chip", chip);
    expect(node).toHaveAttribute("title", value);
    expect(screen.queryByText(value)).not.toBeInTheDocument();
  });

  it("labels a stage by the whole value", () => {
    render(
      <dl>
        <AuthoritativeValue label="Stage" value="approval" />
      </dl>,
    );
    const stage = screen.getByText("Approval", { exact: true });
    expect(stage).toHaveAttribute("title", "approval");
    expect(screen.queryByText("approval")).not.toBeInTheDocument();
    expect(screen.queryByText("Approval available")).not.toBeInTheDocument();
  });
});
