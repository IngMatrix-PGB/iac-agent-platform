# Batch 31 Operator UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local operator console that submits natural-language requests and approves or rejects durable HITL pauses through the existing FastAPI API, then serve that console as static files from the current one-container runtime.

**Architecture:** A Vite-built React client talks only to the public HTTP API. The checkpoint stays authoritative. Production copies the static build into the existing Python image and FastAPI serves it on the same origin. Node is a build stage only. `create_app` mounts the UI only when `ui_dist` is passed or `IAC_AGENT_UI_DIST` points at a directory that contains `index.html`. The SPA fallback never answers `/api`, `/api/*`, `/health`, or `/ready`.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, React Testing Library, Playwright, FastAPI, the existing Python 3.12 image, Terraform 1.16.1, Checkov 3.3.13.

**Spec:** `docs/superpowers/specs/2026-09-28-operator-ui-design.md` (closed, commit `70cf75d55057114491c2006a642d12652bea258d`).

## Global Constraints

- Browser calls only `POST /api/v1/requests`, `GET /api/v1/requests/{request_id}`, `POST /api/v1/requests/{request_id}/approval`, `GET /health`, and `GET /ready`.
- No browser access to LangGraph, Terraform, Checkov, SQLite, OpenAI, Langfuse, or GitHub.
- No authentication, RBAC, public deployment, WebSockets, SSE, request-history endpoint, Terraform source, raw plan JSON, checkpoint viewer, or new AWS resources.
- No DTO expansion. Hand-written TypeScript types. No OpenAPI codegen.
- Public fields only. Pull-request URL is allowed. Do not render finding `resource` or `message`, `WorkflowError.message`, addresses, ARNs, account ids, workspace paths, tokens, or GitHub owner, repository, branch, or base branch.
- Durable request identity is the URL `/requests/{request_id}`. No `localStorage` or `sessionStorage`.
- No Redux, Zustand, XState, or TanStack Query.
- `POST` and approval stay synchronous. Poll `GET` only for `pending`, `running`, and `approved`, every 5000 ms, at most 12 times. Do not poll `awaiting_approval`, `rejected`, `blocked`, `error`, or `pr_created`.
- Approve requires a confirm dialog before the HTTP call. Reject does not. Disable both while the call is in flight. Render the returned body. HTTP 409 replaces the view with `request`. No optimistic status.
- Clarification and unsupported stay on `/` and are not recoverable.
- Reconstructed GET fields that are null or empty stay unavailable. Do not synthesize intent, architecture, `matched_pattern`, or components.
- `/health` copy: `API process responded.` or `API process did not respond.`
- `/ready` copy: `Application process is ready to accept requests.` or `Application process is not ready.`
- Compose publication stays `127.0.0.1:8000:8000`. `0.0.0.0` inside the container is only a bind. The UI does not make the API safe for public Internet exposure.
- Runtime user remains uid 10001. Node is not in the final image. No privileged mode, Docker socket, or host network.
- `create_app()` without `ui_dist` must keep current API tests working with no `ui/dist` present.
- CI keeps `pytest -m "not real_tool and not real_llm and not docker"` and `pytest -m real_tool`. Add one frontend job for `npm ci`, `npm test`, and `npm run build`. Do not publish an image. Playwright is not a required CI job.
- No attribution trailers. If `git commit` appends `Co-Authored-By`, `Generated-By`, `Made with Cursor`, `Cursor`, `Claude`, or `Anthropic`, create the commit with `git commit-tree` instead of amending.
- No `terraform apply` or `destroy`. No real AWS, OpenAI, GitHub, or Langfuse calls in tests.

---

## File map

| File | Responsibility |
|---|---|
| `ui/package.json`, `ui/package-lock.json`, `ui/tsconfig.json`, `ui/vite.config.ts`, `ui/index.html` | Toolchain. Dev server proxies `/api`, `/health`, `/ready` to `127.0.0.1:8000`. |
| `ui/src/api/types.ts` | Public JSON shapes only. |
| `ui/src/api/client.ts` | The only `fetch` wrapper. |
| `ui/src/api/polling.ts` | `shouldPoll`, `POLL_INTERVAL_MS`, `POLL_MAX_ATTEMPTS`. |
| `ui/src/router.ts` | `/` and `/requests/:requestId`. |
| `ui/src/app.tsx` | Shell, routes, health line. |
| `ui/src/pages/compose-page.tsx` | Composer, non-durable outcomes. |
| `ui/src/pages/request-page.tsx` | Durable GET, polling, approval. |
| `ui/src/components/*.tsx` | Form, summary, status, plan, findings, approval, pull request, errors. |
| `ui/src/styles.css` | One column, system font, text status badges. |
| `.gitignore`, `.dockerignore` | Ignore `ui/node_modules` and `ui/dist`. |
| `src/iac_agent/api/ui_static.py` | Mount assets and SPA fallback. |
| `src/iac_agent/api/app.py` | Optional `ui_dist`; `serve()` reads `IAC_AGENT_UI_DIST`. |
| `tests/unit/api/test_ui_static.py` | Fallback does not shadow backend routes. |
| `Dockerfile` | Node build stage, copy `dist` to `/opt/iac-agent/ui`. |
| `tests/docker/test_ui_runtime.py` | Image serves UI and still serves JSON API. |
| `tests/browser/serve_fake_ui.py` | `create_app(holder)` with fakes. No cloud calls. |
| `ui/playwright.config.ts`, `ui/e2e/*.spec.ts` | Approve path and 409 path. |
| `.github/workflows/ci.yml` | `frontend` job only. |
| `docs/api.md`, `docs/roadmap.md` | Local UI, same-origin package, no-auth boundary. |

---

## Task 1: Frontend toolchain

**Files:**
- Create: `ui/package.json`, `ui/tsconfig.json`, `ui/vite.config.ts`, `ui/index.html`, `ui/src/vite-env.d.ts`, `ui/src/smoke.test.ts`
- Modify: `.gitignore`
- Test: `ui/src/smoke.test.ts`

**Interfaces:**
- Consumes: nothing
- Produces: `npm test` and `npm run build` in `ui/`. Vite dev server on `127.0.0.1:5173`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/smoke.test.ts`:

```ts
import { describe, expect, it } from "vitest";

describe("toolchain", () => {
  it("runs vitest", () => {
    expect(1 + 1).toBe(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test --prefix ui`
Expected: FAIL because `ui/package.json` does not exist.

- [ ] **Step 3: Write minimal implementation**

`ui/package.json`:

```json
{
  "name": "iac-agent-ui",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5173",
    "build": "tsc --noEmit && vite build",
    "test": "vitest run"
  },
  "dependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.1.0",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.4",
    "jsdom": "^26.0.0",
    "typescript": "^5.6.3",
    "vite": "^6.0.0",
    "vitest": "^3.0.0"
  }
}
```

`ui/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals"]
  },
  "include": ["src", "vite.config.ts"]
}
```

`ui/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/ready": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: [],
  },
});
```

`ui/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>IaC Agent Platform</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`ui/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

Append to `.gitignore`:

```
ui/node_modules/
ui/dist/
```

Run `npm install --prefix ui` so `ui/package-lock.json` is created. Do not upgrade past the ranges above.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test --prefix ui`
Expected: PASS, 1 test.

`npm run build --prefix ui` may fail until Task 4 adds `ui/src/main.tsx`. That is expected. Do not add a stub page in this task.

- [ ] **Step 5: Commit**

```bash
git add .gitignore ui/package.json ui/package-lock.json ui/tsconfig.json ui/vite.config.ts ui/index.html ui/src/vite-env.d.ts ui/src/smoke.test.ts
```

Message: `build: add the operator UI test toolchain`

Commit `ui/package-lock.json`. Do not commit `ui/node_modules` or `ui/dist`.

---

## Task 2: Public DTO types

**Files:**
- Create: `ui/src/api/types.ts`, `ui/src/api/types.test.ts`
- Test: `ui/src/api/types.test.ts`

**Interfaces:**
- Consumes: `src/iac_agent/api/schemas.py`
- Produces: `RequestResponse`, `FindingDTO`, `PlanDTO`, `WorkflowDTO`, `WorkflowErrorDTO`, `PullRequestDTO`, `ApiErrorBody`

- [ ] **Step 1: Write the failing test**

`ui/src/api/types.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { FindingDTO, RequestResponse, WorkflowErrorDTO } from "./types";

describe("public DTO boundary", () => {
  it("limits findings to policy_id, status, and severity", () => {
    const keys: (keyof FindingDTO)[] = ["policy_id", "status", "severity"];
    expect(keys).toEqual(["policy_id", "status", "severity"]);
  });

  it("limits workflow errors to stage and error_type", () => {
    const keys: (keyof WorkflowErrorDTO)[] = ["stage", "error_type"];
    expect(keys).toEqual(["stage", "error_type"]);
  });

  it("accepts a reconstructed body with null intent and empty components", () => {
    const body: RequestResponse = {
      request_id: "req-20260928T000000Z-abcdef012345",
      outcome: "awaiting_approval",
      approval_available: true,
      terraform_apply: "not_executed",
      intent: null,
      resolution: { outcome: "resolved", name: "order-events", components: [] },
      workflow: {
        workflow_status: "awaiting_approval",
        current_stage: "approval",
        security_status: "pass",
        plan: { add: 1, change: 0, destroy: 0, destructive_change_detected: false },
        findings: [{ policy_id: "SQS_ENCRYPTION", status: "pass", severity: "high" }],
        approval_decision: null,
        error: null,
        pull_request: null,
      },
    };
    expect(body.intent).toBeNull();
    expect(body.resolution.architecture).toBeUndefined();
    expect(body.workflow?.pull_request).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test --prefix ui -- src/api/types.test.ts`
Expected: FAIL with cannot find module `./types`.

- [ ] **Step 3: Write minimal implementation**

`ui/src/api/types.ts` must match `schemas.py` and must not declare `resource`, `message`, `address`, `arn`, `account_id`, `workspace`, `token`, `owner`, `repository`, `branch`, or `base_branch` on these interfaces. `ApiErrorBody.message` is the stable API sentence and is allowed.

```ts
export interface FindingDTO {
  policy_id: string;
  status: string;
  severity: string;
}

export interface PlanDTO {
  add: number;
  change: number;
  destroy: number;
  destructive_change_detected: boolean;
}

export interface ComponentDTO {
  role: string;
  name: string;
  image_tag_mutability?: string | null;
  scan_on_push?: boolean | null;
}

export interface IntentDTO {
  workload_type: string;
  interaction_pattern: string;
  capabilities: string[];
}

export interface ResolutionDTO {
  outcome: string;
  matched_pattern?: string | null;
  architecture?: string | null;
  name?: string | null;
  components?: ComponentDTO[];
  field?: string | null;
  reason?: string | null;
  allowed_values?: string[] | null;
  detail?: string | null;
}

export interface WorkflowErrorDTO {
  stage: string;
  error_type: string;
}

export interface PullRequestDTO {
  url: string;
}

export interface WorkflowDTO {
  workflow_status: string;
  current_stage?: string | null;
  security_status?: string | null;
  plan?: PlanDTO | null;
  findings: FindingDTO[];
  approval_decision?: string | null;
  error?: WorkflowErrorDTO | null;
  pull_request?: PullRequestDTO | null;
}

export interface RequestResponse {
  request_id: string;
  outcome: string;
  approval_available: boolean;
  terraform_apply: "not_executed";
  intent: IntentDTO | null;
  resolution: ResolutionDTO;
  workflow: WorkflowDTO | null;
}

export interface ApiErrorBody {
  error: string;
  message: string;
  request_id?: string;
  request?: RequestResponse;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test --prefix ui -- src/api/types.test.ts`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

Message: `feat(ui): type the public request DTO`

---

## Task 3: Typed API client

**Files:**
- Create: `ui/src/api/client.ts`, `ui/src/api/client.test.ts`
- Test: `ui/src/api/client.test.ts`

**Interfaces:**
- Consumes: `RequestResponse`, `ApiErrorBody`
- Produces:

```ts
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

export class ApiClient {
  constructor(fetchImpl?: typeof fetch);
  submit(naturalLanguageRequest: string): Promise<ClientResult>;
  getRequest(requestId: string): Promise<ClientResult>;
  decide(requestId: string, decision: "approve" | "reject"): Promise<ClientResult>;
  health(): Promise<ProbeResult>;
  ready(): Promise<ProbeResult>;
}
```

Relative URLs only. Components must not call `fetch`.

- [ ] **Step 1: Write the failing test**

Create `ui/src/api/client.test.ts` with this exact file:

```ts
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test --prefix ui -- src/api/client.test.ts`
Expected: FAIL with cannot find module `./client`.

- [ ] **Step 3: Write minimal implementation**

Implement `ui/src/api/client.ts` so the test above passes. Use relative URLs. On `fetch` rejection return the fixed network message and do not interpolate `String(error)`. Parse JSON inside `try`. Treat only HTTP 200 and 201 as `kind: "success"` for `submit`, `getRequest`, and `decide`. A body that is not an object with string `error` and string `message` becomes `error: "unexpected_response"` and `message: "The API returned an unexpected response."`. Include `requestId` when `request_id` is a string, and `request` when `request` is an object. `health` calls `GET /health`. `ready` calls `GET /ready`. Probe success is a JSON object whose `status` is a string, including HTTP 503 `not_ready`. Do not log bodies.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test --prefix ui -- src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

Message: `feat(ui): add the typed FastAPI client`

---

## Task 4: Shell, composer, and error banner

**Files:**
- Create: `ui/src/main.tsx`, `ui/src/app.tsx`, `ui/src/router.ts`, `ui/src/styles.css`, `ui/src/components/error-banner.tsx`, `ui/src/components/health-indicator.tsx`, `ui/src/components/request-form.tsx`, `ui/src/components/open-request.tsx`, `ui/src/pages/compose-page.tsx`, `ui/src/app.test.tsx`
- Modify: `ui/src/vite-env.d.ts` if the test setup needs jest-dom (add `ui/src/test-setup.ts` and set `setupFiles` in `vite.config.ts` to `["./src/test-setup.ts"]`)
- Test: `ui/src/app.test.tsx`

**Interfaces:**
- Consumes: `ApiClient`, `ClientResult`
- Produces: `parseRoute(pathname: string): { name: "compose" } | { name: "request"; requestId: string } | { name: "unknown" }`

`parseRoute`:

- `/` -> compose
- `/requests/` + one segment that does not contain `/` -> request, `decodeURIComponent` of that segment
- anything else -> unknown

`ui/src/test-setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
```

- [ ] **Step 1: Write the failing test**

`ui/src/app.test.tsx`:

- Render the app at `/` with a fake client whose `health` and `ready` resolve to success `ok` and `ready`.
- Assert heading text `IaC Agent Platform`.
- Assert `API process responded.`
- Assert `Application process is ready to accept requests.`
- The description field has accessible name `Infrastructure request`.
- Click `Submit request` with an empty field. Assert the client `submit` was not called. Assert text `Describe the infrastructure before submitting.`
- Type `build a queue` and submit. The fake `submit` returns a 201 success body (minimal `RequestResponse` with `workflow_status: "awaiting_approval"`). Assert `window.location` was set by the app's navigation helper to `/requests/req-1`. Do not call `GET` in this test; the request page is Task 5 and Task 7. For this task, after 201, call the injected `navigate(path)` prop. Test that `navigate` received `/requests/req-1`.
- A second test: `submit` returns 200 `outcome: "clarification_required"` with `resolution.field = "workload_type"`, `reason = "workload_type_required"`, `allowed_values = ["api", "worker", "storage"]`, `workflow: null`. Assert those three values are visible, `navigate` was not called, and text `This result is not saved. Refreshing clears it.`
- A third test: `submit` returns 200 `outcome: "unsupported"`, `resolution.reason = "unsupported_capability"`, `resolution.detail = "no matching architecture"`. Assert that detail is visible and `navigate` was not called.
- A fourth test: `submit` returns `{ kind: "http", status: 400, error: "invalid_request", message: "Invalid request." }`. Assert the banner text is exactly `Invalid request.` and the textarea still contains the draft.
- A fifth test: `submit` returns network. Assert `The API could not be reached.`

Disable the submit button while the promise is pending. Hold the promise and assert the button is disabled, then resolve it.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test --prefix ui -- src/app.test.tsx`
Expected: FAIL with cannot find module `./app`.

- [ ] **Step 3: Write minimal implementation**

`main.tsx` renders `<App client={new ApiClient()} navigate={(path) => { window.location.assign(path); }} />`.

`compose-page.tsx` owns the draft and the in-flight flag. It does not write storage. Clarification and unsupported render on this page. `201` calls `navigate("/requests/" + encodeURIComponent(body.request_id))`.

Health indicator reads probes once on mount. Failed health shows `API process did not respond.` Ready HTTP status 503 or `status: "not_ready"` shows `Application process is not ready.`

`error-banner.tsx` renders `message` in a `role="alert"` element. Focus it when it appears (`useEffect` + `ref.focus()` with `tabIndex={-1}`).

Form label is a `<label htmlFor="infrastructure-request">`. Submit is `<button type="submit">`. Set `aria-busy` on the form while submitting.

`styles.css`: system-ui font, max-width 72rem, one column. No animation.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test --prefix ui`
Expected: PASS, including the smoke test and type tests.

Run: `npm run build --prefix ui`
Expected: PASS and `ui/dist/index.html` exists. Do not commit `ui/dist`.

- [ ] **Step 5: Commit**

Message: `feat(ui): add the request composer shell`

---

## Task 5: Read-only workflow projection

**Files:**
- Create: `ui/src/components/request-summary.tsx`, `ui/src/components/workflow-status.tsx`, `ui/src/components/plan-summary.tsx`, `ui/src/components/findings.tsx`, `ui/src/components/projection.test.tsx`
- Test: `ui/src/components/projection.test.tsx`

**Interfaces:**
- Consumes: `RequestResponse`
- Produces: presentational components with no `fetch`

- [ ] **Step 1: Write the failing test**

Render a resolved POST body:

```ts
const posted: RequestResponse = {
  request_id: "req-1",
  outcome: "awaiting_approval",
  approval_available: true,
  terraform_apply: "not_executed",
  intent: {
    workload_type: "worker",
    interaction_pattern: "asynchronous",
    capabilities: ["queue_processing"],
  },
  resolution: {
    outcome: "resolved",
    architecture: "serverless_worker",
    name: "order-events",
    matched_pattern: "worker+asynchronous+queue_processing",
    components: [
      { role: "queue", name: "order-events" },
      { role: "function", name: "order-events-fn" },
    ],
  },
  workflow: {
    workflow_status: "awaiting_approval",
    current_stage: "approval",
    security_status: "warn",
    plan: { add: 2, change: 1, destroy: 0, destructive_change_detected: true },
    findings: [{ policy_id: "SQS_ENCRYPTION", status: "warn", severity: "high" }],
    approval_decision: null,
    error: null,
    pull_request: null,
  },
};
```

Assert visible text: `req-1`, `awaiting_approval`, `approval`, `warn`, `serverless_worker`, `order-events`, `queue`, `2`, `1`, `0`, `Destructive change detected.`, `SQS_ENCRYPTION`, `Terraform apply was not executed.`

Render a reconstructed GET body: `intent: null`, `resolution: { outcome: "resolved", name: "order-events", components: [] }`, same workflow otherwise, `architecture` omitted. Assert `Unavailable after reload.` for architecture, components, and intent. Assert `order-events` is still visible. Assert `serverless_worker` is not visible.

Render findings JSON that includes extra runtime fields. Cast through `unknown` so TypeScript allows the extra keys at the test boundary:

```ts
const dirty = [
  {
    policy_id: "SQS_ENCRYPTION",
    status: "pass",
    severity: "low",
    resource: "arn:aws:sqs:us-east-1:123456789012:hidden",
    message: "HIDDEN_FINDING_MESSAGE",
  },
] as unknown as FindingDTO[];
```

Assert `SQS_ENCRYPTION` is visible and `arn:aws:sqs:us-east-1:123456789012:hidden` and `HIDDEN_FINDING_MESSAGE` are not.

Render `workflow.error = { stage: "terraform", error_type: "RuntimeError" }` and status `error`. Assert both strings. Assert there is no element that would require `message`.

Render `plan: null`. Assert `No plan summary was returned.`

Render `pull_request: { url: "https://example.invalid/pull/7" }`. Assert the link href is that URL and the visible text is that URL. Assert the words `branch` and `base_branch` are absent.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test --prefix ui -- src/components/projection.test.tsx`
Expected: FAIL with cannot find module.

- [ ] **Step 3: Write minimal implementation**

Findings table headers: `Policy`, `Status`, `Severity`. Read only `policy_id`, `status`, `severity`.

Plan renders three labeled numbers: `Add`, `Change`, `Destroy`.

Summary prints `Unavailable after reload.` when `intent` is null or `resolution.architecture` is null or undefined. Do not fall back to a cached value. Components are pure.

Status text is the server string, not color alone.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test --prefix ui`
Expected: PASS.

- [ ] **Step 5: Commit**

Message: `feat(ui): render the public workflow projection`

---

## Task 6: Approval panel

**Files:**
- Create: `ui/src/components/approval-panel.tsx`, `ui/src/components/approval-panel.test.tsx`
- Test: `ui/src/components/approval-panel.test.tsx`

**Interfaces:**
- Consumes: `RequestResponse`, `ApiClient.decide`
- Produces: `ApprovalPanel` props `{ body: RequestResponse; client: ApiClient; onResult: (result: ClientResult) => void }`

- [ ] **Step 1: Write the failing test**

- `approval_available: false` renders no `Approve` button and no `Reject request` button.
- `approval_available: true` renders both.
- Click `Approve`. Assert `decide` was not called. Assert dialog text `Approval resumes the workflow and publication may create a pull request. Terraform apply will not run.`
- Click `Cancel`. Assert `decide` was not called and focus returns to `Approve`.
- Click `Approve`, then `Confirm approval`. Assert `decide` was called once with `("req-1", "approve")`. While the promise is pending, both buttons and `Confirm approval` are disabled.
- Resolve with a success body whose `workflow_status` is `pr_created`. Assert `onResult` received that result and the component did not locally set status text other than what the parent renders. The panel itself does not invent `approved`.
- Click `Reject request`. Assert `decide` was called with `reject` and no dialog appeared.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test --prefix ui -- src/components/approval-panel.test.tsx`
Expected: FAIL with cannot find module.

- [ ] **Step 3: Write minimal implementation**

Use `<dialog>`. Approve opens it with `showModal()`. Confirm calls `decide`. Reject calls `decide` immediately. `aria-busy` while in flight. Do not change `body` inside the panel.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test --prefix ui`
Expected: PASS.

- [ ] **Step 5: Commit**

Message: `feat(ui): confirm approval before resuming the workflow`

---

## Task 7: Request page, conflicts, polling, and recovery

**Files:**
- Create: `ui/src/api/polling.ts`, `ui/src/api/polling.test.ts`, `ui/src/pages/request-page.tsx`, `ui/src/pages/request-page.test.tsx`
- Modify: `ui/src/app.tsx` so `/requests/:id` renders `RequestPage`
- Test: `ui/src/pages/request-page.test.tsx`, `ui/src/api/polling.test.ts`

**Interfaces:**
- Consumes: `ApiClient.getRequest`, `ApiClient.decide`, `shouldPoll`
- Produces:

```ts
export const POLL_INTERVAL_MS = 5000;
export const POLL_MAX_ATTEMPTS = 12;
export function shouldPoll(status: string | null | undefined): boolean;
```

`shouldPoll` is true only for `pending`, `running`, and `approved`.

- [ ] **Step 1: Write the failing test**

`polling.test.ts` asserts the three true statuses, and false for `awaiting_approval`, `rejected`, `blocked`, `error`, `pr_created`, null, and `clarification_required`.

`request-page.test.tsx`:

- Mount with id `req-1`. Fake `getRequest` returns reconstructed awaiting body (`intent: null`, no architecture). Assert `Unavailable after reload.` and status `awaiting_approval`.
- `getRequest` returns 404 `{ kind: "http", status: 404, error: "request_not_found", message: "Request not found." }`. Assert that message and no approval buttons.
- `getRequest` returns network. Assert `The API could not be reached.`
- Parent compose path is already tested. Here, a 502 result is not used on GET. Add a compose-page test in `app.test.tsx` if not already present: `submit` returns 502 `intent_provider_refusal` message `Intent provider declined to produce structured output.` Assert that message and `This request was not saved.`
- Approval success: panel confirm resolves to `pr_created` with `pull_request.url` `https://example.invalid/pull/7`. Assert the link and that `approval_available` false hides the buttons.
- Conflict: `decide` returns 409 `approval_conflict` whose `request.workflow.workflow_status` is `rejected` and `approval_available` is false. Assert the page now shows `rejected`, the message `This request cannot accept that decision.`, and no Approve button.
- Polling: fake `getRequest` returns `workflow_status: "pending"` forever. Use fake timers. Assert a second GET happens after 5000 ms. Advance 12 intervals and assert no 13th call. Assert a `Refresh` button is visible after the cap. `awaiting_approval` does not schedule a second GET.
- Open-request control: typing `req-9` and activating `Open request` calls `navigate("/requests/req-9")` and does not call `submit`.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test --prefix ui -- src/pages/request-page.test.tsx src/api/polling.test.ts`
Expected: FAIL with cannot find module.

- [ ] **Step 3: Write minimal implementation**

`RequestPage` loads with `getRequest` on mount and when `Refresh` is clicked. Store the last success body in React state. On 409, if `result.request` exists, replace the displayed body with it. On network failure during poll, stop the timer and keep the last body.

Interval id is cleared on unmount. Do not poll when `shouldPoll` is false.

`Open request` lives on the compose page and on the shell so a recovered id can be entered from `/`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm test --prefix ui && npm run build --prefix ui`
Expected: PASS. `ui/dist` stays untracked.

- [ ] **Step 5: Commit**

Message: `feat(ui): recover a request and reconcile approval conflicts`

---

## Task 8: Playwright acceptance

**Files:**
- Create: `tests/browser/serve_fake_ui.py`, `ui/playwright.config.ts`, `ui/e2e/approve.spec.ts`, `ui/e2e/conflict.spec.ts`
- Modify: `ui/package.json` devDependencies add `"@playwright/test": "^1.49.0"` and script `"e2e": "playwright test"`
- Test: the two spec files

**Interfaces:**
- Consumes: `create_app` from `iac_agent.api.app`, domain types `WorkflowView`, `PlanSummary`, `SecurityFinding`, `SecurityGateResult`, `PullRequestResult`, `ApprovalDecision`
- Produces: a localhost fake API on `127.0.0.1:8000` and Vite on `127.0.0.1:5173`

No AWS, OpenAI, GitHub, or Langfuse client is constructed.

- [ ] **Step 1: Write the failing test**

`ui/playwright.config.ts`:

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://127.0.0.1:5173" },
  webServer: [
    {
      command: ".venv/bin/python tests/browser/serve_fake_ui.py",
      cwd: "..",
      url: "http://127.0.0.1:8000/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev",
      url: "http://127.0.0.1:5173",
      reuseExistingServer: false,
    },
  ],
});
```

Playwright's config file lives in `ui/`. The API `webServer` uses `cwd: ".."`, so its command is `.venv/bin/python tests/browser/serve_fake_ui.py` from the repository root. The Vite `webServer` uses the config directory. Do not point Playwright at a real cloud API.

`ui/e2e/approve.spec.ts`:

- Goto `/`.
- Fill `Infrastructure request` with `build a worker that processes a queue and stores results`.
- Click `Submit request`.
- Expect `req-browser`.
- Expect `awaiting_approval`.
- Expect plan text `Add` `1`, `Change` `0`, `Destroy` `0`.
- Expect `SQS_ENCRYPTION`.
- Expect `arn:aws:sqs:us-east-1:123456789012:hidden` to be absent.
- Expect `HIDDEN_FINDING_MESSAGE` to be absent.
- Expect `aws_sqs_queue.hidden_address` to be absent.
- Click `Approve`, then `Confirm approval`.
- Expect `pr_created`.
- Expect link `https://example.invalid/pull/7`.

`ui/e2e/conflict.spec.ts`:

- Goto `/conflict` is not a route. The fake selects conflict mode when the prompt is exactly `conflict please`.
- Submit that prompt.
- Expect `awaiting_approval` and `Approve`.
- Click `Approve`, then `Confirm approval`.
- Expect `This request cannot accept that decision.`
- Expect `rejected`.
- Expect `Approve` to be gone.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm install --prefix ui && npx --prefix ui playwright install chromium && npm run e2e --prefix ui`
Expected: FAIL because `tests/browser/serve_fake_ui.py` does not exist. Installing Playwright browsers is part of this task's implementation session, not the planning commit.

- [ ] **Step 3: Write minimal implementation**

`tests/browser/serve_fake_ui.py` builds `create_app(holder)` and runs uvicorn on `127.0.0.1:8000`.

Holder shape matches `tests/unit/api/test_routes.py`: `application.read`, `application.resume`, `intent_service.submit`. Do not import the test module. Copy the small fake classes into this file.

`submit` stores an awaiting `WorkflowView` and returns `IntentSubmissionResult` with a resolved `SQSResourceSpec(name="order-events")`, intent worker/asynchronous/`QUEUE_PROCESSING`, and that view. Request id is always `req-browser`.

`PlanSummary` uses:

```python
PlanSummary(
    resource_changes=(),
    resources_to_add=("aws_sqs_queue.hidden_address",),
    resources_to_change=(),
    resources_to_destroy=(),
    destructive_change_detected=False,
)
```

`SecurityFinding` uses `policy_id="SQS_ENCRYPTION"`, `severity=SecuritySeverity.HIGH`, `status=PolicyStatus.PASS`, `resource="arn:aws:sqs:us-east-1:123456789012:hidden"`, `message="HIDDEN_FINDING_MESSAGE"`, `source=FindingSource.PLATFORM_POLICY`. Wrap it in `SecurityGateResult`.

`resume` on the happy path returns a view with `WorkflowStatus.PR_CREATED`, `approval_decision=ApprovalDecision.APPROVE`, and `PullRequestResult(number=7, url="https://example.invalid/pull/7", branch="iac-agent/req-browser", base_branch="main")`. The HTTP projection must still hide branch and base branch; the browser test asserts the URL and does not need to assert their absence beyond the approve spec's hidden strings.

Conflict mode: if the prompt is `conflict please`, `read` returns the awaiting view on the first call and a `REJECTED` view with `approval_decision=ApprovalDecision.REJECT` on later calls. `resume` raises `AssertionError` if called. The existing route then returns 409 `approval_conflict` with `request` set to the rejected projection. Do not change `routes.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run e2e --prefix ui`
Expected: PASS, 2 tests.

Run: `npm test --prefix ui`
Expected: PASS.

- [ ] **Step 5: Commit**

Message: `test(ui): prove approval through the browser client`

Do not commit Playwright browser binaries.

---

## Task 9: FastAPI static hosting

**Files:**
- Create: `src/iac_agent/api/ui_static.py`, `tests/unit/api/test_ui_static.py`
- Modify: `src/iac_agent/api/app.py`
- Test: `tests/unit/api/test_ui_static.py`

**Interfaces:**
- Consumes: `create_app(holder=None, *, ui_dist: Path | None = None)`
- Produces: `mount_operator_ui(app, dist: Path) -> None` and `load_ui_dist(env: Mapping[str, str]) -> Path | None`

`load_ui_dist`: blank or missing `IAC_AGENT_UI_DIST` returns `None`. A set value whose `index.html` is missing raises `FileNotFoundError`. `serve()` uses `create_app(ui_dist=load_ui_dist(os.environ))` inside the uvicorn factory.

- [ ] **Step 1: Write the failing test**

`tests/unit/api/test_ui_static.py` uses `tmp_path`:

```python
(dist / "index.html").write_text("<!doctype html><title>IaC Agent Platform</title>", encoding="utf-8")
(dist / "assets").mkdir()
(dist / "assets" / "app.css").write_text("body{margin:0}", encoding="utf-8")
```

Build the app with the `Holder` from a local fake that implements `read` returning `None` and `submit` unused. Call `create_app(holder, ui_dist=dist)`.

Assertions with `TestClient`:

- `GET /` is 200, `text/html`, body contains `IaC Agent Platform`.
- `GET /requests/req-example` is 200, `text/html`, same title.
- `GET /api/v1/requests/req-missing` is 404 JSON `error == "request_not_found"`, and `text/html` is not the content type.
- `GET /api/v1/nonexistent` is 404, content type JSON, body is `{"detail":"Not Found"}`, and the body does not contain `<title>`.
- `GET /health` is 200 JSON `{"status":"ok"}`.
- `GET /ready` with a holder is 200 JSON `{"status":"ready"}`.
- `GET /assets/app.css` is 200 and the body is `body{margin:0}`.
- `create_app(holder)` without `ui_dist`: `GET /` is not HTML (`<title>` absent).
- `load_ui_dist({})` is `None`.
- `load_ui_dist({"IAC_AGENT_UI_DIST": str(dist)})` equals that path.
- `load_ui_dist({"IAC_AGENT_UI_DIST": str(tmp_path / "missing")})` raises `FileNotFoundError`.
- `GET /assets/../index.html` does not escape the dist directory. Expect either the index file from the safe join or a JSON/HTML response that is still the app index, never a file outside `tmp_path`.

Also run one existing route test to prove the default factory is unchanged: `pytest tests/unit/api/test_routes.py::test_missing_natural_language_request_is_400`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/api/test_ui_static.py -q`
Expected: FAIL with `ImportError` or `TypeError` on `ui_dist`.

- [ ] **Step 3: Write minimal implementation**

Register health, ready, and API routes before `mount_operator_ui`. Mount only `/assets` when `dist/assets` is a directory. Add `GET /` and `GET /{full_path:path}` last.

```python
def _backend_path(full_path: str) -> bool:
    if full_path in {"health", "ready", "docs", "redoc", "openapi.json"}:
        return True
    return full_path == "api" or full_path.startswith("api/")
```

If `_backend_path`, return `JSONResponse({"detail": "Not Found"}, status_code=404)`. Else if the resolved candidate is a file inside `dist`, return `FileResponse`. Else return `FileResponse(index)`.

Do not add CORS. Do not change request or approval handlers.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/api/test_ui_static.py tests/unit/api/test_routes.py tests/unit/api/test_app.py -q`
Expected: PASS.

Run: `.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" -q`
Expected: PASS. Count will be higher than 1663 by the new tests. Record the new total in the task notes. Do not weaken markers.

Run: `.venv/bin/ruff check src/iac_agent/api/ui_static.py src/iac_agent/api/app.py tests/unit/api/test_ui_static.py`
Expected: PASS. Do not pass `Dockerfile` to ruff.

- [ ] **Step 5: Commit**

Message: `feat(api): serve the operator UI without shadowing the API`

---

## Task 10: Image build stage

**Files:**
- Modify: `Dockerfile`, `.dockerignore`
- Test: the static tests from Task 9 still pass; image proof is Task 11

**Interfaces:**
- Consumes: `ui/dist` produced by `npm run build` inside the image
- Produces: `/opt/iac-agent/ui/index.html` in the runtime stage and `ENV IAC_AGENT_UI_DIST=/opt/iac-agent/ui`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/docker/test_build_context.py` (or a new test in that file):

- `.dockerignore` contains `ui/node_modules` and `ui/dist`.
- `Dockerfile` contains `AS ui`, `npm run build`, `IAC_AGENT_UI_DIST=/opt/iac-agent/ui`, and `COPY --from=ui`.
- `Dockerfile` does not contain `npm` after the runtime `FROM python:3.12` stage. Assert the runtime stage text has no `npm` and no `apt-get install node`.
- `compose.yaml` still contains `127.0.0.1:8000:8000` and does not contain a second service.

This test fails before the Dockerfile edit.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/docker/test_build_context.py -q`
Expected: FAIL on the missing Dockerfile strings.

- [ ] **Step 3: Write minimal implementation**

Add a stage before the runtime stage:

```dockerfile
FROM node:22-bookworm-slim@sha256:DIGEST AS ui
WORKDIR /src/ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
RUN npm run build
```

Resolve `DIGEST` at implementation time with `docker pull node:22-bookworm-slim` and `docker image inspect --format '{{index .RepoDigests 0}}'`. Do not invent a digest. Both existing Python stages keep the current python digest.

Runtime stage, before `USER iac`:

```dockerfile
COPY --from=ui /src/ui/dist /opt/iac-agent/ui
```

Add to the runtime `ENV` block:

```
IAC_AGENT_UI_DIST=/opt/iac-agent/ui
```

Files stay root-owned and world-readable. Do not `chmod 777`. Do not install Node in the runtime stage.

Append to `.dockerignore`:

```
ui/node_modules
ui/dist
```

Do not change compose ports, the user id, or the Terraform/Checkov stages.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/docker/test_build_context.py -q`
Expected: PASS.

Do not build the image in this task if Docker is unavailable. Task 11 is the image proof. If Docker is available, a build is allowed only as evidence for Task 11.

- [ ] **Step 5: Commit**

Message: `build: compile the operator UI inside the image build`

---

## Task 11: Docker UI acceptance

**Files:**
- Create: `tests/docker/test_ui_runtime.py`
- Test: `tests/docker/test_ui_runtime.py`

**Interfaces:**
- Consumes: image tag `iac-agent-platform:batch31` built from the current Dockerfile. Do not retag or delete `iac-agent-platform:batch30` if a local copy exists. New tests use `batch31` only.
- Produces: proof that the runtime serves HTML and JSON and does not contain Node.

Preserve `tests/docker/test_volume_resume.py` and `tests/docker/test_image_runtime.py`. Do not edit them except if an import path breaks, which it should not.

- [ ] **Step 1: Write the failing test**

Mark the module `pytest.mark.docker`.

Build `iac-agent-platform:batch31`. Run a container with `--user 10001` already implied by the image, no privileged flag, no docker socket, no host network, and no extra published port beyond what the test needs. Prefer `docker exec` against a container published on `127.0.0.1` only if a port is required. HTTP checks can use `docker exec` and `urllib` to `http://127.0.0.1:8000` inside the container, matching Gate B's pattern, so the test does not publish `0.0.0.0`.

The production lifespan still requires GitHub and OpenAI env before `python -m iac_agent.api` serves. Pass placeholder env only: `GITHUB_OWNER=test`, `GITHUB_REPOSITORY=test`, `GITHUB_COMMIT_AUTHOR_NAME=test`, `GITHUB_COMMIT_AUTHOR_EMAIL=test@example.com`, `GITHUB_TOKEN=test`, `IAC_AGENT_LLM_PROVIDER=openai`, `IAC_AGENT_LLM_MODEL=test`, `OPENAI_API_KEY=test`. These are the same class of placeholders as the Batch 30 health test. Do not use real tokens. Do not print them.

Assertions:

- `id -u` is `10001`.
- `command -v node` exits non-zero.
- `command -v npm` exits non-zero.
- `test -f /opt/iac-agent/ui/index.html`.
- `GET /` body contains `IaC Agent Platform` and content type html.
- `GET /requests/req-example` is html.
- `GET /health` JSON status `ok`.
- `GET /ready` JSON status `ready` once the holder exists.
- `GET /api/v1/nonexistent` is JSON, status 404, body has no `<title>`.
- `GET /api/v1/requests/req-missing` JSON `request_not_found`.
- `docker image inspect` Config.Env and `docker history` do not contain `sk-`, `ghp_`, `github_pat_`, or `AKIA` other than the placeholder values already excluded by the Batch 30 secret test. Reuse that test's denylist. The literal placeholder `OPENAI_API_KEY=test` may appear in the process environment of the running container and must not be baked as a real key. Do not add `ENV OPENAI_API_KEY` to the Dockerfile.
- `compose.yaml` port remains `127.0.0.1:8000:8000` (already unit-tested; do not start compose against a real `.env` with secrets).

Cleanup: `docker rm -f` the container in `finally`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/docker/test_ui_runtime.py -q`
Expected: FAIL until the image contains `/opt/iac-agent/ui/index.html`.

- [ ] **Step 3: Write minimal implementation**

The Dockerfile from Task 10 is the implementation. Fix only image wiring if the test shows the UI path is wrong. Do not weaken uid, read-only trees, or the API fallback.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/docker/test_ui_runtime.py tests/docker/test_image_runtime.py tests/docker/test_volume_resume.py -q`
Expected: PASS. Existing Batch 30 docker tests still pass.

- [ ] **Step 5: Commit**

Message: `test(docker): serve the operator UI from the local runtime`

---

## Task 12: CI

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: workflow text assertion in `tests/unit/docker/test_build_context.py` or `tests/unit/ci/test_frontend_job.py`

**Interfaces:**
- Consumes: `ui/package-lock.json`
- Produces: job `frontend` named `Frontend`

- [ ] **Step 1: Write the failing test**

Parse `.github/workflows/ci.yml` with the same YAML loader the repo already uses in tests, or read the text.

Assert:

- A job has `name: Frontend`.
- That job runs `npm ci`, `npm test`, and `npm run build` with `working-directory: ui` or an equivalent `cd ui`.
- The deterministic test step is still exactly `pytest -m "not real_tool and not real_llm and not docker"`.
- The tool-validation step is still `pytest -m real_tool`.
- The file does not contain `docker push` or a registry publish step.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/ci/test_frontend_job.py -q`
Expected: FAIL because the job is absent.

- [ ] **Step 3: Write minimal implementation**

Add:

```yaml
  frontend:
    name: Frontend
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Node.js 22
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: ui/package-lock.json

      - name: Install, test, and build the operator UI
        working-directory: ui
        run: |
          npm ci
          npm test
          npm run build
```

Do not add Playwright browsers to this job. Do not change Python jobs.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/ci/test_frontend_job.py -q && .venv/bin/ruff check tests/unit/ci/test_frontend_job.py`
Expected: PASS.

- [ ] **Step 5: Commit**

Message: `ci: test and build the operator UI`

---

## Task 13: Documentation

**Files:**
- Modify: `docs/api.md`, `docs/roadmap.md`
- Test: extend `tests/unit/docker/test_build_context.py` test `test_api_doc_states_container_bind_is_not_authorization` only if a new exact sentence is required. Add assertions in that file or in `tests/unit/docs/test_operator_ui_docs.py`.

**Interfaces:**
- Consumes: the shipped behavior from Tasks 4–11
- Produces: operator-facing description of the local UI

- [ ] **Step 1: Write the failing test**

Assert `docs/api.md` contains all of:

- `npm run dev` is the local UI and proxies to `127.0.0.1:8000`.
- Production UI is same-origin static files from FastAPI.
- `IAC_AGENT_UI_DIST`
- `/requests/{request_id}`
- The existing sentence `0.0.0.0 inside the container is network binding, not authentication or authorization.`
- `The operator UI does not add authentication.`
- `The operator UI does not make this API safe for public Internet exposure.`
- `GET /health` and `GET /ready` do not prove AWS, OpenAI, GitHub, Langfuse, or Terraform Registry connectivity.

Assert `docs/roadmap.md` contains `Batch 31 — operator UI (complete)` and says authentication and public deployment are not started.

Assert the docs do not contain `Co-Authored-By` or `Made with Cursor`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/docs/test_operator_ui_docs.py -q`
Expected: FAIL on missing sentences.

- [ ] **Step 3: Write minimal implementation**

Update `docs/api.md` local Docker section and add a short "Operator UI" section with development (`ui/` Vite proxy), packaged serving, deep links, approval confirmation, and the no-auth boundary.

Update `docs/roadmap.md`: mark Batch 31 complete and point at the spec and `docs/api.md`. Leave authentication, public deployment, and request history under not started.

Do not document apply, destroy, or a public URL.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/docs/test_operator_ui_docs.py tests/unit/docker/test_build_context.py -q`
Expected: PASS.

Run: `git diff --check`
Expected: no whitespace errors.

Run: `npm test --prefix ui && npm run build --prefix ui`
Expected: PASS.

Run: `.venv/bin/python -m pytest -m "not real_tool and not real_llm and not docker" -q`
Expected: PASS.

- [ ] **Step 5: Commit**

Message: `docs: document the local operator UI`

---

## Spec coverage

| Spec requirement | Task |
|---|---|
| Vite React client | 1, 4 |
| Public DTO only, thin GET fields | 2, 5 |
| Typed client for all five endpoints and status codes | 3 |
| Composer, clarification, unsupported | 4 |
| Plan, findings, forbidden extra fields | 5 |
| Approve confirm, Reject, in-flight disable | 6 |
| 409, deep link, polling, 404, network | 7 |
| Playwright approve and conflict, fake backend | 8 |
| SPA fallback does not shadow `/api`, `/health`, `/ready` | 9 |
| Node build stage, uid 10001, loopback compose | 10, 11 |
| CI install, unit test, build | 12 |
| Docs and no-auth wording | 13 |

No task adds auth, CORS, a second container, a list endpoint, WebSockets, or a DTO field.

## Non-goals

Authentication, RBAC, multi-user, tenants, public Internet deployment, S3, CloudFront, ECS, EKS, WebSockets, SSE, request history, Terraform editor, raw plan JSON, checkpoint viewer, Langfuse UI, GitHub administration, new IaC resources, backend DTO expansion, `terraform apply`, and `terraform destroy`.
