import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AuthoritativeValue, enumCaption } from "./authoritative-value";

describe("authoritative value", () => {
  it("spaces an enum and keeps the server value", () => {
    expect(enumCaption("awaiting_approval")).toBe("Awaiting approval");
    render(
      <dl>
        <AuthoritativeValue label="Workflow status" value="awaiting_approval" />
      </dl>,
    );
    expect(screen.getByRole("term", { name: "Workflow status" })).toBeInTheDocument();
    expect(screen.getByText("Awaiting approval")).toBeInTheDocument();
    expect(screen.getByText("awaiting_approval")).toBeInTheDocument();
  });

  it("does not invent a word that is not in the enum", () => {
    expect(enumCaption("pr_created")).toBe("Pr created");
    expect(enumCaption("warn")).toBe("Warn");
  });
});
