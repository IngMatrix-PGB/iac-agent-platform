import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ClientResult } from "./api/client";
import { ApiClient } from "./api/client";
import type { RequestResponse } from "./api/types";
import { App } from "./app";

function awaiting(requestId = "req-1"): RequestResponse {
  return {
    request_id: requestId,
    outcome: "awaiting_approval",
    approval_available: true,
    terraform_apply: "not_executed",
    intent: null,
    resolution: { outcome: "resolved", name: "order-events" },
    workflow: {
      workflow_status: "awaiting_approval",
      current_stage: "approval",
      security_status: "pass",
      plan: null,
      findings: [],
      approval_decision: null,
      error: null,
      pull_request: null,
    },
  };
}

function clientWith(submit: ApiClient["submit"]): ApiClient {
  return {
    health: vi.fn().mockResolvedValue({ kind: "success", httpStatus: 200, status: "ok" }),
    ready: vi.fn().mockResolvedValue({ kind: "success", httpStatus: 200, status: "ready" }),
    submit,
    getRequest: vi.fn(),
    decide: vi.fn(),
  } as unknown as ApiClient;
}

describe("operator shell", () => {
  it("uses a page heading for an unknown route", () => {
    render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/missing" />);
    expect(screen.getByRole("heading", { level: 1, name: "IaC Agent Platform" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Page not found." })).toBeInTheDocument();
    expect(screen.getByText("Local operator console. Review the server response before approving a request.")).toBeInTheDocument();
  });

  it("shows process health and an empty composer", async () => {
    const submit = vi.fn();
    render(<App client={clientWith(submit)} navigate={vi.fn()} pathname="/" />);
    expect(screen.getByRole("heading", { name: "IaC Agent Platform" })).toBeInTheDocument();
    expect(await screen.findByText("API process responded.")).toBeInTheDocument();
    expect(screen.getByText("Application process is ready to accept requests.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Infrastructure request" })).toBeInTheDocument();
  });

  it("does not submit a blank description", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<App client={clientWith(submit)} navigate={vi.fn()} pathname="/" />);
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByText("Describe the infrastructure before submitting.")).toBeInTheDocument();
  });

  it("disables submit and navigates after a durable workflow", async () => {
    const user = userEvent.setup();
    let resolveSubmit: (value: ClientResult) => void = () => {};
    const pending = new Promise<ClientResult>((resolve) => {
      resolveSubmit = resolve;
    });
    const submit = vi.fn().mockReturnValue(pending);
    const navigate = vi.fn();
    render(<App client={clientWith(submit)} navigate={navigate} pathname="/" />);
    await user.type(screen.getByRole("textbox", { name: "Infrastructure request" }), "build a queue");
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(screen.getByRole("button", { name: "Submit request" })).toBeDisabled();
    resolveSubmit({ kind: "success", status: 201, body: awaiting() });
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/requests/req-1"));
  });

  it("keeps clarification on the composer", async () => {
    const user = userEvent.setup();
    const body: RequestResponse = {
      ...awaiting("req-clarify"),
      outcome: "clarification_required",
      approval_available: false,
      workflow: null,
      resolution: {
        outcome: "clarification_required",
        field: "workload_type",
        reason: "workload_type_required",
        allowed_values: ["api", "worker", "storage"],
      },
    };
    const submit = vi.fn().mockResolvedValue({ kind: "success", status: 200, body });
    const navigate = vi.fn();
    render(<App client={clientWith(submit)} navigate={navigate} pathname="/" />);
    await user.type(screen.getByRole("textbox", { name: "Infrastructure request" }), "hello");
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByText("workload_type")).toBeInTheDocument();
    expect(screen.getByText("workload_type_required")).toBeInTheDocument();
    expect(screen.getByText("api")).toBeInTheDocument();
    expect(screen.getByText("worker")).toBeInTheDocument();
    expect(screen.getByText("storage")).toBeInTheDocument();
    expect(screen.getByText("This result is not saved. Refreshing clears it.")).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("keeps an unsupported intent on the composer", async () => {
    const user = userEvent.setup();
    const body: RequestResponse = {
      ...awaiting("req-nope"),
      outcome: "unsupported",
      approval_available: false,
      workflow: null,
      resolution: {
        outcome: "unsupported",
        reason: "unsupported_capability",
        detail: "no matching architecture",
      },
    };
    const submit = vi.fn().mockResolvedValue({ kind: "success", status: 200, body });
    const navigate = vi.fn();
    render(<App client={clientWith(submit)} navigate={navigate} pathname="/" />);
    await user.type(screen.getByRole("textbox", { name: "Infrastructure request" }), "build a database");
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByText("no matching architecture")).toBeInTheDocument();
    expect(screen.getByText("unsupported_capability")).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("shows a stable validation message and keeps the draft", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue({
      kind: "http",
      status: 400,
      error: "invalid_request",
      message: "Invalid request.",
    });
    render(<App client={clientWith(submit)} navigate={vi.fn()} pathname="/" />);
    await user.type(screen.getByRole("textbox", { name: "Infrastructure request" }), "build a queue");
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/^Invalid request\.$/);
    expect(screen.getByRole("textbox", { name: "Infrastructure request" })).toHaveValue("build a queue");
  });

  it("distinguishes a network failure from an API error", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue({
      kind: "network",
      message: "The API could not be reached.",
    });
    render(<App client={clientWith(submit)} navigate={vi.fn()} pathname="/" />);
    await user.type(screen.getByRole("textbox", { name: "Infrastructure request" }), "build a queue");
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The API could not be reached.");
  });

  it("says an interpreter failure was not saved", async () => {
    const user = userEvent.setup();
    const submit = vi.fn().mockResolvedValue({
      kind: "http",
      status: 502,
      error: "intent_provider_refusal",
      message: "Intent provider declined to produce structured output.",
    });
    const navigate = vi.fn();
    render(<App client={clientWith(submit)} navigate={navigate} pathname="/" />);
    await user.type(screen.getByRole("textbox", { name: "Infrastructure request" }), "build a queue");
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Intent provider declined to produce structured output.",
    );
    expect(screen.getByText("This request was not saved.")).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("opens a known request id without submitting", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    const navigate = vi.fn();
    render(<App client={clientWith(submit)} navigate={navigate} pathname="/" />);
    await user.type(screen.getByRole("textbox", { name: "Request id" }), "req-9");
    await user.click(screen.getByRole("button", { name: "Open request" }));
    expect(navigate).toHaveBeenCalledWith("/requests/req-9");
    expect(submit).not.toHaveBeenCalled();
  });
});
