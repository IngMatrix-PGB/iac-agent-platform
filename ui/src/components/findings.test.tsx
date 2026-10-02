import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Findings } from "./findings";

describe("findings", () => {
  it("keeps a table and a stacked list with the same caption", () => {
    render(
      <Findings
        workflowStatus="awaiting_approval"
        findings={[{ policy_id: "SQS_ENCRYPTION", status: "pass", severity: "high" }]}
      />,
    );
    expect(screen.getByRole("table", { name: "Security findings" })).toHaveClass("findings-table");
    const list = screen.getByRole("list", { name: "Security findings" });
    expect(list).toHaveClass("finding-stack");
    expect(screen.getAllByText("Pass").length).toBeGreaterThan(0);
    expect(screen.getAllByText("High").length).toBeGreaterThan(0);
    expect(screen.getAllByTitle("pass").length).toBeGreaterThan(0);
    expect(screen.queryByText("pass")).not.toBeInTheDocument();
  });

  it("hides an empty in-progress gate and reports an empty reviewed gate", () => {
    const { rerender } = render(<Findings findings={[]} workflowStatus="pending" />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByText("No findings were returned.")).not.toBeInTheDocument();
    rerender(<Findings findings={[]} workflowStatus="blocked" />);
    expect(screen.getByText("No findings were returned.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
