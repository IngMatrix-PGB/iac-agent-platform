import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorBanner, noticeTone } from "./error-banner";

const INTENT =
  "Intent interpretation is not configured. Set IAC_AGENT_LLM_PROVIDER, IAC_AGENT_LLM_MODEL, and OPENAI_API_KEY.";

describe("noticeTone", () => {
  it("separates configuration, conflict, missing, and other failures", () => {
    expect(noticeTone("capability_unavailable")).toBe("config");
    expect(noticeTone("approval_conflict")).toBe("conflict");
    expect(noticeTone("request_exists")).toBe("conflict");
    expect(noticeTone("request_not_found")).toBe("missing");
    expect(noticeTone("internal_error")).toBe("error");
    expect(noticeTone("invalid_request")).toBe("error");
    expect(noticeTone("network")).toBe("error");
  });
});

describe("ErrorBanner", () => {
  it("heads a missing capability without calling it a workflow error", () => {
    render(<ErrorBanner message={INTENT} tone="config" />);
    expect(screen.getByRole("heading", { name: "Not configured" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(INTENT);
    expect(screen.getByRole("alert")).toHaveClass("notice-config");
    expect(screen.queryByRole("heading", { name: "Workflow error" })).not.toBeInTheDocument();
  });

  it("heads an approval conflict and leaves a duplicate create untitled", () => {
    render(
      <ErrorBanner message="This request cannot accept that decision." tone="conflict" />,
    );
    expect(screen.getByRole("heading", { name: "Approval conflict" })).toBeInTheDocument();
    render(<ErrorBanner message="Request already exists." tone="conflict" />);
    expect(screen.getAllByRole("heading", { name: "Approval conflict" })).toHaveLength(1);
    expect(screen.getByText("Request already exists.")).toBeInTheDocument();
  });

  it("shows a network failure without a workflow-error heading", () => {
    render(<ErrorBanner message="The API could not be reached." tone="error" />);
    expect(screen.getByRole("alert")).toHaveClass("notice-error");
    expect(screen.queryByRole("heading", { name: "Workflow error" })).not.toBeInTheDocument();
  });
});
