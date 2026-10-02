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
    listRequests: vi.fn().mockResolvedValue({ kind: "success", status: 200, body: { requests: [] } }),
  } as unknown as ApiClient;
}

async function continueAsOperator(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Operator secret"), "test-operator-secret");
  await user.click(screen.getByRole("button", { name: "Continue" }));
}

describe("operator shell", () => {
  it("groups the composer and the open-request control", async () => {
    const user = userEvent.setup();
    render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/" />);
    await continueAsOperator(user);
    expect(screen.getByRole("heading", { level: 2, name: "New request" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Open a saved request" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Infrastructure request" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Request id" })).toBeInTheDocument();
  });

  it("uses a page heading for an unknown route", () => {
    render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/missing" />);
    expect(screen.getByRole("heading", { level: 1, name: "IaC Agent Platform" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Page not found." })).toBeInTheDocument();
    expect(screen.getByText("Local operator console. Review the server response before approving a request.")).toBeInTheDocument();
  });

  it("labels health and readiness without changing the sentences", async () => {
    render(<App client={clientWith(vi.fn())} navigate={vi.fn()} pathname="/" />);
    expect(await screen.findByRole("region", { name: "Process status" })).toBeInTheDocument();
    expect(screen.getAllByRole("term").map((term) => term.textContent)).toEqual(["API", "Readiness"]);
    expect(screen.getByText("API process responded.")).toBeInTheDocument();
    expect(screen.getByText("Application process is ready to accept requests.")).toBeInTheDocument();
  });

  it("shows process health and an empty composer", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<App client={clientWith(submit)} navigate={vi.fn()} pathname="/" />);
    expect(screen.getByRole("heading", { name: "IaC Agent Platform" })).toBeInTheDocument();
    await continueAsOperator(user);
    expect(await screen.findByText("API process responded.")).toBeInTheDocument();
    expect(screen.getByText("Application process is ready to accept requests.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Infrastructure request" })).toBeInTheDocument();
  });

  it("does not submit a blank description", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<App client={clientWith(submit)} navigate={vi.fn()} pathname="/" />);
    await continueAsOperator(user);
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
    await continueAsOperator(user);
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
    await continueAsOperator(user);
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
    await continueAsOperator(user);
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
    await continueAsOperator(user);
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
    await continueAsOperator(user);
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
    await continueAsOperator(user);
    await user.type(screen.getByRole("textbox", { name: "Infrastructure request" }), "build a queue");
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Intent provider declined to produce structured output.",
    );
    expect(screen.getByText("This request was not saved.")).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("keeps the operator secret in memory and gates protected pages", async () => {
    const user = userEvent.setup();
    const secret = "operator-secret-should-not-leak";
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const getItem = vi.spyOn(Storage.prototype, "getItem");
    const idbOpen = vi.fn();
    const idbDelete = vi.fn();
    vi.stubGlobal("indexedDB", { open: idbOpen, deleteDatabase: idbDelete });
    const listRequests = vi.fn().mockResolvedValue({
      kind: "success",
      status: 200,
      body: {
        requests: [
          {
            request_id: "req-listed",
            created_at: "2026-09-29T00:00:02.000000Z",
            workflow_status: "awaiting_approval",
            approval_available: true,
            security_status: "pass",
            name: "orders",
          },
        ],
      },
    });
    const getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: awaiting("req-saved") });
    const operator = clientWith(vi.fn());
    operator.listRequests = listRequests;
    operator.getRequest = getRequest;
    const createClient = vi.fn(() => operator);
    const probe = clientWith(vi.fn());
    probe.getRequest = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: awaiting("req-saved") });
    probe.listRequests = vi.fn().mockResolvedValue({ kind: "success", status: 200, body: { requests: [] } });

    const view = render(
      <App
        client={probe}
        createClient={createClient}
        navigate={vi.fn()}
        pathname="/requests/req-saved"
      />,
    );

    expect(screen.getByRole("heading", { name: "IaC Agent Platform" })).toBeInTheDocument();
    expect(await screen.findByText("API process responded.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Recent requests" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Request review" })).not.toBeInTheDocument();
    expect(screen.queryByText("Loading request.")).not.toBeInTheDocument();
    expect(screen.queryByText("Request not found.")).not.toBeInTheDocument();
    expect(listRequests).not.toHaveBeenCalled();
    expect(getRequest).not.toHaveBeenCalled();
    const field = screen.getByLabelText("Operator secret");
    expect(field).toHaveAttribute("type", "password");
    await user.type(field, secret);
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
    expect(createClient).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(createClient).toHaveBeenCalledWith(secret);
    expect(getRequest).toHaveBeenCalledWith("req-saved");
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toMatch(/\b(profile|role|tenant)\b/i);
    view.unmount();

    listRequests.mockClear();
    getRequest.mockClear();
    createClient.mockClear();
    const recent = render(
      <App client={probe} createClient={createClient} navigate={vi.fn()} pathname="/" />,
    );
    expect(screen.getByLabelText("Operator secret")).toHaveValue("");
    expect(listRequests).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Recent requests" })).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Operator secret"), secret);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(listRequests).toHaveBeenCalledOnce();
    expect(await screen.findByRole("link", { name: "req-listed" })).toHaveAttribute(
      "href",
      "/requests/req-listed",
    );
    expect(screen.getByText("Awaiting approval")).toBeInTheDocument();
    expect(screen.getByText("Pass")).toBeInTheDocument();
    expect(screen.getByText("Approval available")).toBeInTheDocument();
    expect(screen.getByText("orders")).toBeInTheDocument();
    expect(screen.getByText("2026-09-29T00:00:02.000000Z")).toBeInTheDocument();
    expect(screen.queryByText(secret)).not.toBeInTheDocument();

    listRequests.mockResolvedValue({
      kind: "http",
      status: 401,
      error: "unauthenticated",
      message: "Authentication is required.",
    });
    recent.unmount();
    render(<App client={probe} createClient={createClient} navigate={vi.fn()} pathname="/" />);
    await user.type(screen.getByLabelText("Operator secret"), secret);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByLabelText("Operator secret")).toHaveValue("");
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
    expect(screen.queryByText("Request not found.")).not.toBeInTheDocument();
    expect(setItem).not.toHaveBeenCalled();
    expect(getItem).not.toHaveBeenCalled();
    expect(idbOpen).not.toHaveBeenCalled();
    expect(idbDelete).not.toHaveBeenCalled();
    setItem.mockRestore();
    getItem.mockRestore();
    vi.unstubAllGlobals();
  });

  it("opens a known request id without submitting", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    const navigate = vi.fn();
    render(<App client={clientWith(submit)} navigate={navigate} pathname="/" />);
    await continueAsOperator(user);
    await user.type(screen.getByRole("textbox", { name: "Request id" }), "req-9");
    await user.click(screen.getByRole("button", { name: "Open request" }));
    expect(navigate).toHaveBeenCalledWith("/requests/req-9");
    expect(submit).not.toHaveBeenCalled();
  });
});
