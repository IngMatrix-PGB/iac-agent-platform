import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { ApiClient } from "../api/client";
import type { RequestListItem } from "../api/types";
import { App } from "../app";

const EMPTY_COPY =
  "No indexed requests. A checkpoint created before the durable index can still be opened by request id.";

const LISTED: RequestListItem = {
  request_id: "req-listed",
  created_at: "2026-09-29T00:00:02.000000Z",
  workflow_status: "awaiting_approval",
  approval_available: true,
  security_status: "pass",
  name: "orders",
};

const HIDDEN = [
  'resource "aws_sqs_queue"',
  "module.queue.aws_sqs_queue.this",
  "arn:aws:sqs:us-east-1:123456789012:hidden",
  "HIDDEN_FINDING_MESSAGE",
  "HIDDEN_WORKFLOW_ERROR_MESSAGE",
  "/var/lib/iac-agent/workspaces/secret",
  "HIDDEN_CHECKPOINT_SENTINEL",
  "example-owner",
  "example-repository",
  "ghp_exampleTokenShouldNeverRender",
];

function clientWith(listRequests: ApiClient["listRequests"], submit = vi.fn()): ApiClient {
  return {
    health: vi.fn().mockResolvedValue({ kind: "success", httpStatus: 200, status: "ok" }),
    ready: vi.fn().mockResolvedValue({ kind: "success", httpStatus: 200, status: "ready" }),
    submit,
    getRequest: vi.fn(),
    decide: vi.fn(),
    listRequests,
  } as unknown as ApiClient;
}

async function continueAsOperator(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Operator secret"), "test-operator-secret");
  await user.click(screen.getByRole("button", { name: "Continue" }));
}

describe("recent requests", () => {
  it("renders one indexed row and links to the encoded request route", async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn();
    vi.stubGlobal("fetch", fetchImpl);
    const listRequests = vi.fn().mockResolvedValue({
      kind: "success",
      status: 200,
      body: {
        requests: [
          LISTED,
          {
            request_id: "req/a b",
            created_at: "2026-09-29T00:00:01.000000Z",
            workflow_status: "pr_created",
            approval_available: false,
            security_status: null,
            name: null,
            resource: "arn:aws:sqs:us-east-1:123456789012:hidden",
            message: "HIDDEN_FINDING_MESSAGE",
            terraform: 'resource "aws_sqs_queue"',
            address: "module.queue.aws_sqs_queue.this",
            error: "HIDDEN_WORKFLOW_ERROR_MESSAGE",
            workspace: "/var/lib/iac-agent/workspaces/secret",
            checkpoint: "HIDDEN_CHECKPOINT_SENTINEL",
            owner: "example-owner",
            repository: "example-repository",
            token: "ghp_exampleTokenShouldNeverRender",
          },
        ],
      },
    });
    const navigate = vi.fn();
    render(<App client={clientWith(listRequests)} navigate={navigate} pathname="/" />);
    await continueAsOperator(user);

    expect(screen.getByRole("heading", { name: "New request" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recent requests" })).toBeInTheDocument();
    expect(document.getElementById("compose")).toHaveAttribute("tabindex", "-1");
    expect(document.getElementById("requests")).toHaveAttribute("tabindex", "-1");
    const named = await screen.findByRole("link", { name: "orders" });
    expect(named).toHaveAttribute("href", "/requests/req-listed");
    expect(listRequests).toHaveBeenCalledTimes(1);
    expect(listRequests).toHaveBeenCalledWith();
    expect(screen.getByText("req-listed").className).toContain("meta");
    expect(screen.getAllByText("Awaiting approval")).toHaveLength(1);
    expect(screen.getAllByText("Pass")).toHaveLength(1);
    expect(screen.queryByText("awaiting_approval")).not.toBeInTheDocument();
    expect(screen.queryByText("pass")).not.toBeInTheDocument();
    expect(screen.queryByText("Approval available")).not.toBeInTheDocument();
    expect(screen.queryByText("Approval not available")).not.toBeInTheDocument();
    expect(screen.queryByText("2026-09-29T00:00:02.000000Z")).not.toBeInTheDocument();
    expect(named.closest("li")).toHaveAttribute("title", "2026-09-29T00:00:02.000000Z");
    expect(named.closest("li")).toHaveClass("catalog-row");
    expect(screen.getByRole("link", { name: "req/a b" })).toBeInTheDocument();
    expect(screen.getByText("Pull request created")).toBeInTheDocument();
    expect(screen.queryByText("Security status")).not.toBeInTheDocument();
    expect(screen.queryByText("Workflow status")).not.toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
    expect(screen.queryByText("unknown")).not.toBeInTheDocument();
    const openRow = screen.getByRole("link", { name: "req/a b" }).closest("li");
    expect(openRow?.querySelector(".meta")).toBeNull();
    expect(openRow?.textContent).not.toMatch(/Security status|Name|Approval not available/);
    for (const sentinel of HIDDEN) {
      expect(document.body.textContent).not.toContain(sentinel);
    }
    expect(fetchImpl).not.toHaveBeenCalled();

    await user.click(screen.getByRole("link", { name: "orders" }));
    expect(navigate).toHaveBeenCalledWith("/requests/req-listed");
    await user.click(screen.getByRole("link", { name: "req/a b" }));
    expect(navigate).toHaveBeenCalledWith("/requests/req%2Fa%20b");
    vi.unstubAllGlobals();
  });

  it("explains an empty index without hiding the typed opener", async () => {
    const user = userEvent.setup();
    const listRequests = vi.fn().mockResolvedValue({
      kind: "success",
      status: 200,
      body: { requests: [] },
    });
    const submit = vi.fn();
    const navigate = vi.fn();
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    render(<App client={clientWith(listRequests, submit)} navigate={navigate} pathname="/" />);
    await continueAsOperator(user);
    expect(await screen.findByText(EMPTY_COPY)).toBeInTheDocument();
    expect(listRequests).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("heading", { name: "New request" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Open a saved request" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit request" })).toHaveClass("button-primary");
    expect(screen.getByRole("button", { name: "Open request" })).toHaveClass("button-secondary");
    await user.type(screen.getByRole("textbox", { name: "Request id" }), "req-9");
    await user.click(screen.getByRole("button", { name: "Open request" }));
    expect(navigate).toHaveBeenCalledWith("/requests/req-9");
    expect(submit).not.toHaveBeenCalled();
    expect(setItem).not.toHaveBeenCalled();
    const sources = import.meta.glob("./compose-page.tsx", {
      eager: true,
      query: "?raw",
      import: "default",
    });
    expect(JSON.stringify(sources)).not.toMatch(/localStorage|sessionStorage|indexedDB/);
    setItem.mockRestore();
  });

  it("keeps the composer usable when the list cannot load", async () => {
    const user = userEvent.setup();
    const listRequests = vi.fn().mockResolvedValue({
      kind: "network",
      message: "The API could not be reached.",
    });
    render(<App client={clientWith(listRequests)} navigate={vi.fn()} pathname="/" />);
    await continueAsOperator(user);
    expect(await screen.findByRole("alert")).toHaveTextContent("The API could not be reached.");
    expect(screen.getByRole("heading", { name: "New request" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Open a saved request" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Infrastructure request" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Request id" })).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_COPY)).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("secret-host");
  });

  it("returns to the credential field when the list is unauthenticated", async () => {
    const user = userEvent.setup();
    const secret = "operator-secret-should-not-leak";
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const listRequests = vi.fn().mockResolvedValue({
      kind: "http",
      status: 401,
      error: "unauthenticated",
      message: "Authentication is required.",
    });
    render(<App client={clientWith(listRequests)} navigate={vi.fn()} pathname="/" />);
    await user.type(screen.getByLabelText("Operator secret"), secret);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(listRequests).toHaveBeenCalledWith();
    expect(await screen.findByLabelText("Operator secret")).toHaveValue("");
    expect(screen.queryByText(secret)).not.toBeInTheDocument();
    expect(screen.queryByText("Request not found.")).not.toBeInTheDocument();
    expect(screen.queryByText(EMPTY_COPY)).not.toBeInTheDocument();
    expect(screen.queryByText("awaiting_approval")).not.toBeInTheDocument();
    expect(setItem).not.toHaveBeenCalled();
    setItem.mockRestore();
  });

  it("does not refresh the list after submit", async () => {
    const user = userEvent.setup();
    const listRequests = vi.fn().mockResolvedValue({
      kind: "success",
      status: 200,
      body: { requests: [] },
    });
    const submit = vi.fn().mockResolvedValue({
      kind: "http",
      status: 400,
      error: "invalid_request",
      message: "Invalid request.",
    });
    render(<App client={clientWith(listRequests, submit)} navigate={vi.fn()} pathname="/" />);
    await continueAsOperator(user);
    await screen.findByText(EMPTY_COPY);
    await user.type(screen.getByRole("textbox", { name: "Infrastructure request" }), "build a queue");
    await user.click(screen.getByRole("button", { name: "Submit request" }));
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(listRequests).toHaveBeenCalledTimes(1);
  });
});
