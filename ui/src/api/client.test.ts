import { describe, expect, it, vi } from "vitest";
import { ApiClient } from "./client";
import type { RequestListItem, RequestResponse } from "./types";

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
    [503, "capability_unavailable", "Intent interpretation is not configured. Set IAC_AGENT_LLM_PROVIDER, IAC_AGENT_LLM_MODEL, and OPENAI_API_KEY."],
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

  it("lists durable requests without a limit", async () => {
    const row: RequestListItem = {
      request_id: "req-listed",
      created_at: "2026-09-29T00:00:02.000000Z",
      workflow_status: "awaiting_approval",
      approval_available: true,
      security_status: "pass",
      name: "orders",
    };
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(200, { requests: [row] }));
    const result = await new ApiClient(fetchImpl).listRequests();
    expect(fetchImpl).toHaveBeenCalledWith("/api/v1/requests", { method: "GET" });
    expect(result).toEqual({ kind: "success", status: 200, body: { requests: [row] } });
  });

  it("accepts an empty list and nullable catalog fields", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(200, { requests: [] }))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          requests: [
            {
              request_id: "req-open",
              created_at: "2026-09-29T00:00:01.000000Z",
              workflow_status: "blocked",
              approval_available: false,
              security_status: null,
              name: null,
            },
          ],
        }),
      );
    const client = new ApiClient(fetchImpl);
    await expect(client.listRequests()).resolves.toEqual({
      kind: "success",
      status: 200,
      body: { requests: [] },
    });
    await expect(client.listRequests()).resolves.toEqual({
      kind: "success",
      status: 200,
      body: {
        requests: [
          {
            request_id: "req-open",
            created_at: "2026-09-29T00:00:01.000000Z",
            workflow_status: "blocked",
            approval_available: false,
            security_status: null,
            name: null,
          },
        ],
      },
    });
  });

  it("keeps list failures on the existing error mapping", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(503, {
          error: "intent_provider_unavailable",
          message: "Intent provider unavailable.",
        }),
      )
      .mockResolvedValueOnce(jsonResponse(200, created))
      .mockRejectedValueOnce(new Error("connect ECONNREFUSED secret-host"));
    const client = new ApiClient(fetchImpl);
    await expect(client.listRequests()).resolves.toEqual({
      kind: "http",
      status: 503,
      error: "intent_provider_unavailable",
      message: "Intent provider unavailable.",
    });
    await expect(client.listRequests()).resolves.toEqual({
      kind: "http",
      status: 200,
      error: "unexpected_response",
      message: "The API returned an unexpected response.",
    });
    await expect(client.listRequests()).resolves.toEqual({
      kind: "network",
      message: "The API could not be reached.",
    });
  });

  it("does not call fetch outside the API client", () => {
    const sources = import.meta.glob(
      ["../components/**/*.{ts,tsx}", "../pages/**/*.{ts,tsx}", "../app.tsx"],
      { eager: true, query: "?raw", import: "default" },
    );
    const callers = Object.entries(sources).filter(([, source]) => /\bfetch\s*\(/.test(String(source)));
    expect(callers).toEqual([]);
  });

  it("sends the operator bearer on operator calls and not on probes", async () => {
    const secret = "operator-secret-should-not-leak";
    const fetchImpl = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
      const path = String(url);
      if (path === "/health" || path === "/ready") {
        return Promise.resolve(jsonResponse(200, { status: "ok" }));
      }
      if (path === "/api/v1/requests" && init?.method === "GET") {
        return Promise.resolve(jsonResponse(200, { requests: [] }));
      }
      return Promise.resolve(jsonResponse(201, created));
    });
    const client = new ApiClient(fetchImpl, { operatorSecret: secret });
    await client.submit("build a queue");
    await client.listRequests();
    await client.getRequest("req-1");
    await client.decide("req-1", "approve");
    await client.health();
    await client.ready();

    const calls = fetchImpl.mock.calls;
    for (const [url, init] of calls.slice(0, 4)) {
      expect(String(url)).not.toContain(secret);
      expect(new Headers(init?.headers).get("Authorization")).toBe(`Bearer ${secret}`);
      expect(String(init?.body ?? "")).not.toContain(secret);
    }
    expect(calls[0]?.[0]).toBe("/api/v1/requests");
    expect(JSON.parse(String(calls[0]?.[1]?.body))).toEqual({
      natural_language_request: "build a queue",
    });
    expect(calls[1]?.[0]).toBe("/api/v1/requests");
    expect(calls[1]?.[1]?.method).toBe("GET");
    expect(calls[1]?.[1]?.body).toBeUndefined();
    expect(calls[2]?.[0]).toBe("/api/v1/requests/req-1");
    expect(calls[3]?.[0]).toBe("/api/v1/requests/req-1/approval");
    expect(JSON.parse(String(calls[3]?.[1]?.body))).toEqual({ decision: "approve" });
    expect(new Headers(calls[4]?.[1]?.headers).get("Authorization")).toBeNull();
    expect(new Headers(calls[5]?.[1]?.headers).get("Authorization")).toBeNull();
    expect(calls[4]?.[0]).toBe("/health");
    expect(calls[5]?.[0]).toBe("/ready");
  });

  it("maps unauthenticated responses without copying the credential", async () => {
    const secret = "operator-secret-should-not-leak";
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse(401, { error: "unauthenticated", message: "Authentication is required." }),
    );
    const client = new ApiClient(fetchImpl, { operatorSecret: secret });
    const result = await client.listRequests();
    expect(result).toEqual({
      kind: "http",
      status: 401,
      error: "unauthenticated",
      message: "Authentication is required.",
    });
    expect(JSON.stringify(result)).not.toContain(secret);
  });

  it("invokes fetch with the global receiver", async () => {
    const fetchImpl = vi.fn(function (this: unknown) {
      if (this !== globalThis) {
        throw new TypeError("Illegal invocation");
      }
      return Promise.resolve(jsonResponse(200, { status: "ok" }));
    });
    const client = new ApiClient(fetchImpl);
    await expect(client.health()).resolves.toMatchObject({ kind: "success", status: "ok" });
  });
});
