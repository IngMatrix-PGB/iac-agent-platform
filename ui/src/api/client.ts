import type { RequestListItem, RequestListResponse, RequestResponse } from "./types";

export type ClientSuccess = { kind: "success"; status: number; body: RequestResponse };
export type ClientHttpError = {
  kind: "http";
  status: number;
  error: string;
  message: string;
  requestId?: string;
  request?: RequestResponse;
};
export type ClientNetworkError = { kind: "network"; message: "The API could not be reached." };
export type ClientResult = ClientSuccess | ClientHttpError | ClientNetworkError;
export type RequestListResult =
  | { kind: "success"; status: number; body: RequestListResponse }
  | ClientHttpError
  | ClientNetworkError;
export function isUnauthenticated(result: { kind: string; status?: number }): boolean {
  return result.kind === "http" && result.status === 401;
}

export type ProbeResult =
  | { kind: "success"; httpStatus: number; status: string }
  | ClientNetworkError
  | { kind: "http"; status: number; message: string };

const NETWORK: ClientNetworkError = {
  kind: "network",
  message: "The API could not be reached.",
};
const UNEXPECTED = "The API returned an unexpected response.";

export class ApiClient {
  private readonly fetchImpl: typeof fetch;
  private readonly operatorSecret: string;

  constructor(fetchImpl: typeof fetch = globalThis.fetch, options?: { operatorSecret?: string }) {
    this.fetchImpl = fetchImpl.bind(globalThis);
    this.operatorSecret = options?.operatorSecret ?? "";
  }

  submit(naturalLanguageRequest: string): Promise<ClientResult> {
    return this.request("/api/v1/requests", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ natural_language_request: naturalLanguageRequest }),
    });
  }

  getRequest(requestId: string): Promise<ClientResult> {
    return this.request(requestPath(requestId), { method: "GET" });
  }

  decide(requestId: string, decision: "approve" | "reject"): Promise<ClientResult> {
    return this.request(`${requestPath(requestId)}/approval`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ decision }),
    });
  }

  listRequests(): Promise<RequestListResult> {
    return this.list("/api/v1/requests");
  }

  health(): Promise<ProbeResult> {
    return this.probe("/health");
  }

  ready(): Promise<ProbeResult> {
    return this.probe("/ready");
  }

  private async request(url: string, init: RequestInit): Promise<ClientResult> {
    let response: Response;
    try {
      response = await this.fetchImpl(url, this.withOperatorSecret(init));
    } catch {
      return NETWORK;
    }
    const parsed = await readJson(response);
    if ((response.status === 200 || response.status === 201) && isRequestResponse(parsed)) {
      return { kind: "success", status: response.status, body: parsed };
    }
    return httpError(response.status, parsed);
  }

  private async list(url: string): Promise<RequestListResult> {
    let response: Response;
    try {
      response = await this.fetchImpl(url, this.withOperatorSecret({ method: "GET" }));
    } catch {
      return NETWORK;
    }
    const parsed = await readJson(response);
    const body = requestListResponse(parsed);
    if (response.status === 200 && body) {
      return { kind: "success", status: response.status, body };
    }
    return httpError(response.status, parsed);
  }

  private async probe(url: string): Promise<ProbeResult> {
    let response: Response;
    try {
      response = await this.fetchImpl(url, { method: "GET" });
    } catch {
      return NETWORK;
    }
    const parsed = await readJson(response);
    if (isRecord(parsed) && typeof parsed.status === "string") {
      return { kind: "success", httpStatus: response.status, status: parsed.status };
    }
    return { kind: "http", status: response.status, message: UNEXPECTED };
  }

  private withOperatorSecret(init: RequestInit): RequestInit {
    if (!this.operatorSecret) {
      return init;
    }
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.operatorSecret}`);
    return { ...init, headers };
  }
}

function requestPath(requestId: string): string {
  return `/api/v1/requests/${encodeURIComponent(requestId)}`;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return undefined;
  }
}

function httpError(status: number, parsed: unknown): ClientHttpError {
  if (!isRecord(parsed) || typeof parsed.error !== "string" || typeof parsed.message !== "string") {
    return { kind: "http", status, error: "unexpected_response", message: UNEXPECTED };
  }
  const result: ClientHttpError = {
    kind: "http",
    status,
    error: parsed.error,
    message: parsed.message,
  };
  if (typeof parsed.request_id === "string") {
    result.requestId = parsed.request_id;
  }
  if (isRequestResponse(parsed.request)) {
    result.request = parsed.request;
  }
  return result;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requestListResponse(value: unknown): RequestListResponse | undefined {
  if (!isRecord(value) || !Array.isArray(value.requests)) {
    return undefined;
  }
  const requests: RequestListItem[] = [];
  for (const item of value.requests) {
    const row = requestListItem(item);
    if (!row) {
      return undefined;
    }
    requests.push(row);
  }
  return { requests };
}

function requestListItem(value: unknown): RequestListItem | undefined {
  if (
    !isRecord(value) ||
    typeof value.request_id !== "string" ||
    typeof value.created_at !== "string" ||
    typeof value.workflow_status !== "string" ||
    typeof value.approval_available !== "boolean" ||
    (typeof value.security_status !== "string" && value.security_status !== null) ||
    (typeof value.name !== "string" && value.name !== null)
  ) {
    return undefined;
  }
  return {
    request_id: value.request_id,
    created_at: value.created_at,
    workflow_status: value.workflow_status,
    approval_available: value.approval_available,
    security_status: value.security_status,
    name: value.name,
  };
}

function isRequestResponse(value: unknown): value is RequestResponse {
  return isRecord(value) && typeof value.request_id === "string" && typeof value.outcome === "string";
}
