import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

describe("findings summary", () => {
  const many = [
    { policy_id: "A_PASS", status: "pass", severity: "medium" },
    { policy_id: "B_PASS", status: "pass", severity: "critical" },
    { policy_id: "C_WARN", status: "warn", severity: "medium" },
    { policy_id: "D_PASS", status: "pass", severity: "high" },
    { policy_id: "E_PASS", status: "pass", severity: "low" },
  ];

  it("leads with non-passing findings and collapses extra passes behind a toggle", async () => {
    const user = userEvent.setup();
    render(<Findings findings={many} workflowStatus="awaiting_approval" securityStatus="warn" />);
    const table = screen.getByRole("table", { name: "Security findings" });
    const firstCells = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) => within(row).getByText(/_(PASS|WARN)$/).textContent);
    expect(firstCells).toEqual(["C_WARN", "B_PASS"]);
    expect(screen.getByText("WARN")).toHaveClass("gate-badge-warn");

    await user.click(screen.getByRole("button", { name: "+ 3 more passing" }));
    expect(within(table).getAllByRole("row")).toHaveLength(6);
    expect(screen.getByRole("button", { name: "Show fewer" })).toHaveAttribute("aria-expanded", "true");
  });

  it("does not collapse a short list", () => {
    render(<Findings findings={many.slice(0, 3)} workflowStatus="awaiting_approval" />);
    expect(screen.queryByRole("button", { name: /more passing/ })).not.toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "Security findings" })).getAllByRole("row")).toHaveLength(4);
  });
});
