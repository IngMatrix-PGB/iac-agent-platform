import type { RequestResponse } from "./types";

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

  constructor(fetchImpl: typeof fetch = globalThis.fetch) {
    this.fetchImpl = fetchImpl.bind(globalThis);
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

  health(): Promise<ProbeResult> {
    return this.probe("/health");
  }

  ready(): Promise<ProbeResult> {
    return this.probe("/ready");
  }

  private async request(url: string, init: RequestInit): Promise<ClientResult> {
    let response: Response;
    try {
      response = await this.fetchImpl(url, init);
    } catch {
      return NETWORK;
    }
    const parsed = await readJson(response);
    if ((response.status === 200 || response.status === 201) && isRequestResponse(parsed)) {
      return { kind: "success", status: response.status, body: parsed };
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

function isRequestResponse(value: unknown): value is RequestResponse {
  return isRecord(value) && typeof value.request_id === "string" && typeof value.outcome === "string";
}
