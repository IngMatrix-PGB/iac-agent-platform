import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "./client";
import type { RequestResponse } from "./types";

const created: RequestResponse = {
  request_id: "req-1",
  outcome: "awaiting_approval",
  approval_available: true,
  terraform_apply: "not_executed",
  intent: null,
  resolution: { outcome: "resolved", name: "order-events" },
  workflow: {
    workflow_status: "awaiting_approval",
    findings: [],
    plan: null,
    error: null,
    pull_request: null,
    approval_decision: null,
  },
};

const conflictRequest: RequestResponse = {
  ...created,
  outcome: "rejected",
  approval_available: false,
  workflow: {
    workflow_status: "rejected",
    findings: [],
    plan: null,
    error: null,
    pull_request: null,
    approval_decision: "reject",
  },
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("ApiClient", () => {
  it("posts a request without a client request id", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(201, created));
    const result = await new ApiClient(fetchImpl).submit("build a queue");
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/requests", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ natural_language_request: "build a queue" }),
    });
    expect(result).toEqual({ kind: "success", status: 201, body: created });
  });

  it("returns clarification without navigating data", async () => {
    const body: RequestResponse = {
      ...created,
      outcome: "clarification_required",
      approval_available: false,
      workflow: null,
    };
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, body));
    const result = await new ApiClient(fetchImpl).submit("hello");
    expect(result).toEqual({ kind: "success", status: 200, body });
  });

  it("gets a request by id", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, created));
    const result = await new ApiClient(fetchImpl).getRequest("req-1");
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/requests/req-1", { method: "GET" });
    expect(result).toEqual({ kind: "success", status: 200, body: created });
  });

  it.each(["approve", "reject"] as const)("posts %s", async (decision) => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, created));
    await new ApiClient(fetchImpl).decide("req-1", decision);
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/requests/req-1/approval", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision }),
    });
  });

  it.each([
    [400, "invalid_request", "Invalid request."],
    [404, "request_not_found", "Request not found."],
    [409, "request_exists", "Request already exists."],
    [500, "internal_error", "Internal error."],
    [502, "intent_provider_refusal", "Intent provider declined to produce structured output."],
    [503, "intent_provider_unavailable", "Intent provider unavailable."],
    [504, "intent_provider_timeout", "Intent provider timed out."],
  ] as const)("maps %s %s", async (status, error, message) => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(status, { error, message }));
    const result = await new ApiClient(fetchImpl).submit("build a queue");
    expect(result).toEqual({ kind: "http", status, error, message });
  });

  it("keeps the embedded request on approval_conflict", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(409, {
        error: "approval_conflict",
        message: "This request cannot accept that decision.",
        request: conflictRequest,
      }),
    );
    const result = await new ApiClient(fetchImpl).decide("req-1", "approve");
    expect(result).toEqual({
      kind: "http",
      status: 409,
      error: "approval_conflict",
      message: "This request cannot accept that decision.",
      request: conflictRequest,
    });
  });

  it("maps fetch rejection to a fixed network message", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new Error("connect ECONNREFUSED secret-host"));
    const result = await new ApiClient(fetchImpl).getRequest("req-1");
    expect(result).toEqual({ kind: "network", message: "The API could not be reached." });
  });

  it("does not surface a raw non-envelope body", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response("Traceback most recent call", { status: 500 }),
    );
    const result = await new ApiClient(fetchImpl).submit("build a queue");
    expect(result).toEqual({
      kind: "http",
      status: 500,
      error: "unexpected_response",
      message: "The API returned an unexpected response.",
    });
  });

  it("reads health and ready status strings", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { status: "ok" }))
      .mockResolvedValueOnce(jsonResponse(503, { status: "not_ready" }));
    const client = new ApiClient(fetchImpl);
    await expect(client.health()).resolves.toEqual({
      kind: "success",
      httpStatus: 200,
      status: "ok",
    });
    await expect(client.ready()).resolves.toEqual({
      kind: "success",
      httpStatus: 503,
      status: "not_ready",
    });
    expect(fetchImpl).toHaveBeenNthCalledWith(1, "/health", { method: "GET" });
    expect(fetchImpl).toHaveBeenNthCalledWith(2, "/ready", { method: "GET" });
  });
});
