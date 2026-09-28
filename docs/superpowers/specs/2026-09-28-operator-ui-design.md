# Batch 31 — Operator UI

Closed design. Approved on 2026-09-28 as the implementation baseline. This document does not add a frontend, a `package.json`, a dependency install, a Dockerfile change, or a FastAPI change. Implementation is a separate plan and a later turn.

Verified baseline: `origin/main` is `9552d4be647d4a79270e9793637d8be66711f4ff`, the merge of pull request #13 (`feat/batch30-docker-runtime`). The second parent is `bc5e82328f7b143b68ace7300d5c0a24607202e4`. `Dockerfile`, `compose.yaml`, `docs/api.md`, `src/iac_agent/api/`, and `tests/docker/test_volume_resume.py` are on that commit. There is no `package.json` and no frontend tree.

## 1. Context

Batch 29 is the HTTP boundary. Batch 30 packages that same application as one local container. The operator still has no browser client. The next product boundary is a small console that submits natural-language infrastructure requests and approves or rejects the durable human-in-the-loop pause.

The console is a client of the existing FastAPI boundary. It is not a second application, not a workflow engine, and not an admin dashboard.

```
Browser
   |  HTTP only
   v
FastAPI  (src/iac_agent/api)
   |
   v
IntentResolutionService / IacApplication
   |
   v
LangGraph workflow
   +-- Terraform
   +-- Checkov
   +-- SQLite checkpointing
   +-- GitHub source-control adapter
   +-- optional observability
```

The browser must not import Python modules, call LangGraph, Terraform, Checkov, SQLite, OpenAI, Langfuse, or GitHub, read checkpoints, construct workflow state, or keep its own approval state machine.

## 2. Goals

- Let an operator submit one natural-language request through `POST /api/v1/requests`.
- Render clarification, unsupported, and durable-workflow outcomes from the public body only.
- When `approval_available` is true, send `approve` or `reject` through `POST /api/v1/requests/{request_id}/approval`.
- Reopen a known durable request through `GET /api/v1/requests/{request_id}`.
- Show the public pull-request URL when `workflow.pull_request.url` is present.
- Keep the local Docker runtime as one container, with the API still published only on host loopback.

## 3. Non-goals

Authentication, RBAC, multi-user support, organizations, tenants, and public Internet exposure.

AWS, Kubernetes, ECS, Fargate, CloudFront, S3 hosting, Cognito, and any new AWS resource (KMS, SNS, EventBridge, Secrets Manager, CloudFront/S3/OAC, ECS/Fargate expansion).

WebSockets and server-sent events. A Terraform source editor, raw Terraform, raw plan JSON, a checkpoint inspector, a Langfuse embed, a GitHub management UI, a resource inventory, and a request history that would need a list endpoint.

`terraform apply` and `terraform destroy`. Image-registry publication. Changing public DTO fields to make the UI richer.

## 4. Discovered architecture

`create_app` in `src/iac_agent/api/app.py` builds one FastAPI app. Routes in `src/iac_agent/api/routes.py` call `IntentResolutionService.submit`, `IacApplication.read`, and `IacApplication.resume`. `project_submission` and `project_view` in `src/iac_agent/api/project.py` are the only HTTP projections. `decide_approval` in `src/iac_agent/api/approval.py` is the only approval policy the route uses.

`IacApplication.submit` and `resume` call `graph.invoke`. The HTTP handlers wait for that call. There is no background worker and no status-push channel. A normal `POST` returns only after interpretation and, when the architecture resolves, after the graph stops at a boundary. The usual secure boundary is `awaiting_approval`. Blocked and error workflows are also returned on that same response when the graph stops there. Clarification and unsupported results never call the graph.

`GET` calls `read`. A snapshot whose `created_at` is null is missing. HTTP does not call `get_state`, so an unknown id is 404 rather than a synthetic `pending`.

`compose.yaml` publishes `127.0.0.1:8000:8000`. The container bind is `0.0.0.0:8000`. `docs/api.md` states: 0.0.0.0 inside the container is network binding, not authentication or authorization. There is no CORS middleware, no `StaticFiles` mount, and no auth middleware.

The production lifespan still requires GitHub and OpenAI configuration before `python -m iac_agent.api` serves. `/health` and `/ready` do not check those services. That eager startup debt stays as documented in `docs/api.md`.

## 5. Exact API contract the UI may use

Public models are frozen Pydantic models in `src/iac_agent/api/schemas.py`. `terraform_apply` is always the literal `not_executed`.

### `POST /api/v1/requests`

Request JSON object:

- `natural_language_request`: required non-empty string after strip.
- `request_id`: optional. Omitted or JSON `null` lets the server generate `req-YYYYMMDDTHHMMSSZ-` plus 12 lowercase hex digits (`src/iac_agent/cli/ids.py`). A supplied id must be a non-empty single path segment: no separators, no `..`, not absolute (`validate_request_id`).

Success:

- `200` when `workflow` is null. Outcomes are `clarification_required` and `unsupported`. These are not written to SQLite. A later `GET` of that id is 404.
- `201` when a workflow view exists. `Location: /api/v1/requests/{request_id}`. `outcome` is the workflow status value. The usual secure value is `awaiting_approval`. `blocked` and `error` are also 201 responses when the graph returns them.

Response body is `RequestResponse` (see below).

Errors, all `{"error","message"}` unless noted:

| Status | `error` | When |
| --- | --- | --- |
| 400 | `invalid_request` | Body is not a JSON object, or `natural_language_request` is missing, not a string, or blank. |
| 400 | `invalid_request_id` | `request_id` is present and not a valid id string. |
| 409 | `request_exists` | `read` already finds a checkpoint. The body has no embedded request. The route does not submit again. |
| 503 | `intent_provider_unavailable` | Includes `request_id`. No checkpoint. |
| 504 | `intent_provider_timeout` | Includes `request_id`. No checkpoint. |
| 502 | `intent_provider_refusal` | Includes `request_id`. No checkpoint. |
| 502 | `intent_payload_malformed` | Includes `request_id`. No checkpoint. |
| 502 | `intent_schema_unsupported` | Includes `request_id`. No checkpoint. |
| 502 | `intent_interpretation_failed` | Fallback for any other `IntentInterpreterError`. Includes `request_id`. No checkpoint. |
| 500 | `internal_error` | Any other exception from `submit`. Message is `Internal error.` |

Stable messages are the strings in `routes.py`. The UI shows those messages. It does not show exception text.

### `GET /api/v1/requests/{request_id}`

No body. `200` and `RequestResponse` from `project_view` when a checkpoint exists. `400` `invalid_request_id`. `404` `request_not_found` with message `Request not found.`

### `POST /api/v1/requests/{request_id}/approval`

Body: `{"decision":"approve"}` or `{"decision":"reject"}`. Any other JSON value is `400` `invalid_approval`. Non-object JSON is `400` `invalid_request`.

`decide_approval` is the policy:

- Status `awaiting_approval`: resume the graph. `200` and `project_view` of the resumed checkpoint.
- Same decision again: `approve` while status is `pr_created` or `approved` and the stored decision is `approve`, or `reject` while status is `rejected` and the stored decision is `reject`. `200` and the current projection. The graph is not resumed.
- Anything else, including the opposite decision and any decision while `blocked` or `error`: `409`.

`409` body:

```json
{
  "error": "approval_conflict",
  "message": "This request cannot accept that decision.",
  "request": {}
}
```

`request` is the current `RequestResponse` projection. The UI replaces its view with that object.

`400` `invalid_request_id`. `404` `request_not_found`. `500` `internal_error` if `resume` fails and a follow-up read is neither idempotent success nor a conflict.

### `GET /health` and `GET /ready`

`/health` is `200` `{"status":"ok"}`. It does not call AWS, OpenAI, GitHub, Langfuse, or the Terraform Registry.

`/ready` is `200` `{"status":"ready"}` when the application holder exists, and `503` `{"status":"not_ready"}` when it does not. Readiness is that local check only.

### `RequestResponse`

| Field | POST, resolved workflow | POST, clarification or unsupported | GET and approval responses |
| --- | --- | --- | --- |
| `request_id` | string | string | string |
| `outcome` | workflow status | `clarification_required` or `unsupported` | workflow status |
| `approval_available` | true only for `awaiting_approval` | false | true only for `awaiting_approval` |
| `terraform_apply` | `not_executed` | `not_executed` | `not_executed` |
| `intent` | `workload_type`, `interaction_pattern`, `capabilities` | same three fields | `null` |
| `resolution` | resolved spec projection | clarification or unsupported projection | `outcome=resolved`, `name` only |
| `workflow` | `WorkflowDTO` | `null` | `WorkflowDTO` |

`IntentDTO` does not include assumptions, confidence, hints, unresolved questions, or schema version. Those stay off the wire. The UI must not ask for them.

`ResolutionDTO` fields that can be null: `matched_pattern`, `architecture`, `name`, `field`, `reason`, `allowed_values`, `detail`. `components` defaults to `[]`.

Resolved `POST` fills `matched_pattern`, `architecture`, `name`, and `components`. Clarification fills `field`, `reason` (`workload_type_required` or `interaction_pattern_required`), and `allowed_values` (`api`/`worker`/`storage`, or `synchronous`/`asynchronous`). Unsupported fills `reason` (`unsupported_workload`, `unsupported_capability`, or `unsupported_combination`) and `detail`.

`ComponentDTO`: `role`, `name`, and optional `image_tag_mutability` and `scan_on_push` (ECR only). Standalone resources other than ECR project an empty component list; the name is `resolution.name` and the architecture label is `sqs`, `s3`, `dynamodb`, `lambda`, `api_gateway`, or `ecr`. Compositions use roles such as `queue`, `function`, `table`, `api`, and `route`.

`WorkflowDTO`: `workflow_status`, `current_stage` nullable, `security_status` nullable (`pass`, `warn`, or `block`), `plan` nullable, `findings` (possibly empty), `approval_decision` nullable (`approve` or `reject`), `error` nullable, `pull_request` nullable.

`PlanDTO`: `add`, `change`, `destroy`, `destructive_change_detected`. Counts only. No plan JSON and no addresses.

`FindingDTO`: `policy_id`, `status` (`pass`, `warn`, `block`), `severity` (`info`, `low`, `medium`, `high`, `critical`). No resource, message, or source.

`WorkflowErrorDTO`: `stage`, `error_type`. No message.

`PullRequestDTO`: `url` only.

Workflow status values the UI must be able to render if the API returns them: `pending`, `running`, `awaiting_approval`, `approved`, `rejected`, `blocked`, `error`, `pr_created`. Stage values: `render`, `terraform`, `plan_analysis`, `platform_policy`, `checkov`, `security_gate`, `approval`, `source_control`, `complete`, `error`.

### Reconstructed GET is thinner than POST

`project_view` documents that the checkpoint has no `ArchitectureIntent`. After `GET`, and after every approval response (those also use `project_view`):

- `intent` is null.
- `resolution.architecture`, `matched_pattern`, `components`, `field`, `reason`, `allowed_values`, and `detail` are null or empty.
- `resolution.name` remains when the checkpoint has a resource spec.
- Workflow fields, plan counts, findings, approval decision, error stage/type, and pull-request URL remain.

The UI prints unavailable for the missing submission-only fields. It does not copy them from an earlier response into `localStorage` or `sessionStorage`, and it does not invent them. Showing them from the in-memory `POST` body until the next server response is fine. The next `GET` or approval response replaces that view.

## 6. Architectural boundary

One typed HTTP client owns the base URL, JSON, status codes, and the public DTO. Components receive that result. They do not call `fetch` themselves.

There is no second domain model. TypeScript types are the JSON shapes above, including the error envelopes. Workflow labels in the UI are the server strings, plus short operator sentences that do not add facts.

`approval_available` and `workflow.workflow_status` come from the server. Controls render only when `approval_available` is true. The client does not infer that a status "should" be approvable.

## 7. Technology comparison

The repository has no frontend stack, no Node manifest, and no server-rendered templates.

### Option A — React, TypeScript, and Vite

A static SPA built by Vite. Production output is files. The FastAPI process serves them. Node exists only in a build stage and on the developer machine.

Complexity is moderate and limited to one page. TypeScript can mirror the small DTO set. Component tests and one browser test have a normal toolchain. Vite's dev server proxies API calls, so production CORS stays absent.

### Option B — Server-rendered pages from FastAPI

Jinja (or another template engine) plus a small script, returned by new HTML routes. No Node in development or in the image. Docker stays a pure Python image.

The cost is a second presentation layer inside the Python app, weaker DTO typing, and more FastAPI surface before the UI exists. Partial updates for approval and errors tend to become ad hoc JavaScript anyway. The API contract would grow HTML routes that the browser client does not need.

### Recommendation

Option A. The UI is a client. The API already exists. A static build keeps Node out of the runtime image and keeps route handlers as JSON. Server rendering would add backend behavior this batch does not need.

This is a design recommendation. It is not an implementation.

## 8. Serving model

### A. Static assets in the existing container

Build stage: Node image, `npm ci`, `npm run build`, output a `dist/` directory. Runtime stage: the current Python image copies `dist/` and does not include Node. FastAPI mounts those files. Compose stays `127.0.0.1:8000:8000`. One container. No CORS, because the browser and the API share the origin. Image growth is the static files, not a Node runtime.

### B. Separate frontend container

A second service, a second port, and CORS on the API. That splits the Batch 30 one-container local runtime and widens the browser origin story. It is not justified for one operator page.

### Recommendation

Option A, in Gate C only. Gates A and B run the Vite dev server against the existing API and do not change FastAPI.

Gate C needs one narrow serving change: mount the built assets and, for client routes, return `index.html`. The SPA fallback must not intercept `/api`, `/api/*`, `/health`, or `/ready`. A request to those paths stays a backend response, including 404, and must never be `index.html`. `/docs`, `/openapi.json`, and `/redoc` stay FastAPI's own routes. No DTO, route-contract, LangGraph, Terraform, Checkov, SQLite, or GitHub change. No CORS middleware.

Until that mount exists, deep links work on the Vite server only.

The API loopback assumption stays. The UI does not publish a second port.

## 9. Information architecture

One shell, two client paths.

| Path | Role |
| --- | --- |
| `/` | Empty composer, plus the latest non-durable `200` (clarification or unsupported) while the tab still holds that response. |
| `/requests/{request_id}` | Load `GET /api/v1/requests/{request_id}` and render the durable projection. |

After `201`, the client navigates to `/requests/{request_id}` and renders the `POST` body it already has. Refresh runs `GET` and drops submission-only fields, labeled unavailable.

Clarification and unsupported do not navigate. Those ids are not checkpoints. Copy on that panel says the result is not saved and a refresh clears it.

Do not add a history list. There is no list endpoint.

### Regions

A. Header. Title `IaC Agent Platform`. One health line (section 16). No account, org, or environment switcher.

B. Request composer. A labeled multiline field for the infrastructure description. Submit button. No request-id field. The server generates the id. A separate "Open request" control accepts an existing id and navigates to `/requests/{request_id}`.

C. Request summary. Request id. Outcome. Architecture and component names when the body has them. Resource name when `resolution.name` is set. Explicit unavailable text when a reconstructed body omits architecture, components, or intent.

D. Workflow status. `workflow_status`, `current_stage` when present, `security_status` when present, `approval_decision` when present. `terraform_apply` shown as the fixed sentence from the field: apply was not executed.

E. Plan summary. Add, change, and destroy counts, plus destructive-change text when `destructive_change_detected` is true. Hidden when `workflow.plan` is null, with the text that no plan summary was returned.

F. Security gate. A table of `policy_id`, `status`, and `severity`. Empty state when `findings` is empty. Hidden when `workflow` is null.

G. Approval panel. Rendered only when `approval_available` is true. Approve and Reject.

H. Pull-request result. The `url` string as a link when present. No owner, repository, branch, or number parsed out as facts. The URL may be displayed as the href and the visible text.

I. Recovery. The open-request control and the `/requests/{request_id}` path. That is the whole history feature.

## 10. Page and component inventory

Proposed tree. Not created in this turn.

```
ui/
  index.html
  package.json
  tsconfig.json
  vite.config.ts
  src/
    main.tsx
    app.tsx                 shell, header, route switch
    router.ts               `/` and `/requests/:requestId` only
    api/types.ts            public JSON shapes
    api/client.ts           fetch, status, envelopes
    api/errors.ts           typed client failures
    pages/compose-page.tsx
    pages/request-page.tsx
    components/request-form.tsx
    components/open-request.tsx
    components/outcome-panel.tsx
    components/request-summary.tsx
    components/workflow-status.tsx
    components/plan-summary.tsx
    components/findings.tsx
    components/approval-panel.tsx
    components/pull-request.tsx
    components/error-banner.tsx
    components/health-indicator.tsx
```

No Redux, Zustand, XState, or TanStack Query. Local `useState` in the page is enough: the last server body, an in-flight flag, and the banner. A hand-rolled two-route listener is enough. React Router is deferred until there are more routes.

`api/client.ts` is the only module that reads `import.meta.env` for the API origin. Packaged builds use same-origin relative URLs. The dev server proxies, so the dev build also uses relative URLs.

## 11. Workflow-state UX

| UI state | Behavior |
| --- | --- |
| Initial | Empty textarea, submit enabled, no summary. |
| Submitting | Disable the form and the submit button. `aria-busy`. Do not send a second `POST`. |
| Clarification | Stay on `/`. Show `resolution.field`, `resolution.reason`, and `resolution.allowed_values`. Keep the textarea so the operator can revise the sentence and submit a new `POST`. The server will assign a new id. There is no durable clarification thread and no API to patch the old id. |
| Unsupported | Stay on `/`. Show `resolution.reason` and `resolution.detail`. The operator may edit and submit a new request. |
| Durable workflow | Navigate to `/requests/{id}`. Render status, stage, plan, findings, and error type from the body. |
| `pending` / `running` | Render the words. They are not the normal `POST` result. They can appear if a `GET` observes a checkpoint mid-invoke. |
| `awaiting_approval` | Show the approval panel. |
| `approved` | Render the status. Do not show Approve. This status can exist on a checkpoint; a completed resume in the same request usually continues to `pr_created` or `error`. |
| `rejected` | Render the status and stored decision. Hide the panel. |
| `blocked` | Render status and findings. Say the security gate stopped the workflow before review. Hide the panel. |
| `error` | Render `workflow.error.stage` and `workflow.error.error_type` when present. Do not invent a message. Hide the panel. |
| Approval in flight | Disable Approve, Reject, and the confirm action. Keep the previous server body on screen. |
| Approval conflict | Replace the view with `409.request`. Recompute the panel from that body. |
| Not found | `404` banner using the stable message. Clear any stale detail for that id. |
| Invalid request | `400` banner. Keep the draft text. |
| Interpreter failure | Banner for 502, 503, or 504 using the stable message. Say the request was not saved. Do not link a recovery page for that id. |
| Internal error | Banner text `Internal error.` Nothing else from the body. |
| Backend unavailable | Distinct banner: the API could not be reached. This is not an `error` field from JSON. Keep the last successful body if one was already shown. |
| `pr_created` | Show `workflow.pull_request.url` when it is a non-empty string. If the status is `pr_created` and `url` is null, say the URL was not returned. Do not construct a GitHub URL. |

Terminal for operator purposes: `rejected`, `blocked`, `error`, `pr_created`. `awaiting_approval` is paused, not finished. `approved` is intermediate.

## 12. Approval UX

Approve and Reject render only when the latest server body has `approval_available === true`.

Approve opens a confirmation dialog before any HTTP call. The dialog states that approval resumes the workflow and publication may create a pull request, and that Terraform apply will not run (`terraform_apply` is `not_executed`). Confirm sends `{"decision":"approve"}`. Cancel sends nothing.

Reject sends `{"decision":"reject"}` from its button without a second dialog. The button label is `Reject request`. Reject does not publish. Both decisions are mutually exclusive afterward: the opposite call is a 409.

While the approval request is in flight, both buttons and the dialog confirm action are disabled.

The client does not set `workflow_status` to `approved` locally. It renders the returned `200` body. A repeated approve or reject that the server treats as idempotent is also that `200` body. A `409` renders `request` from the conflict envelope, which is the server's current projection.

Refresh and deep link call `GET` and derive the panel only from `approval_available`.

## 13. Error UX

Map envelopes to operator text. Prefer the API `message` when it is one of the stable sentences. Never render a stack, a provider payload, or `WorkflowError.message` (it is not on the wire).

| Condition | UI |
| --- | --- |
| `invalid_request`, `invalid_request_id`, `invalid_approval` | Validation banner. Focus it. |
| `request_exists` | Say this id already exists. Offer the open-request action for the id that was sent. Do not invent the checkpoint body; `GET` loads it. |
| Clarification / unsupported | Outcome panel, not an error banner. |
| `request_not_found` | Not-found banner. |
| `approval_conflict` | Conflict banner plus the embedded `request`. |
| `intent_provider_unavailable` | Unavailable banner. Not saved. |
| `intent_provider_timeout` | Timeout banner. Not saved. |
| `intent_provider_refusal`, `intent_payload_malformed`, `intent_schema_unsupported`, `intent_interpretation_failed` | Interpreter banner using the stable message. Not saved. |
| `internal_error` and any other HTTP 500 | Internal-error banner. |
| `TypeError` / failed `fetch` / connection reset | Backend-unavailable banner. Distinct from HTTP 500. |

Focus moves to the banner after a failed submit, and to the outcome heading after a successful `200` or `201`.

## 14. State management

React state holds the draft text, the in-flight flag, the last `RequestResponse` the server returned, and the current banner. That is not a workflow store. The checkpoint is authoritative.

The active request id lives in the URL (`/requests/{request_id}`). Refresh and paste both call `GET`.

Do not store the id, the prompt, or the response in `localStorage` or `sessionStorage`. On an unauthenticated local API, a leftover id in browser storage is a capability to approve whatever that checkpoint still allows. The URL is visible, does not outlive a closed tab unless the operator bookmarks it, and is the deep link we want.

The prompt stays in the textarea only. The API does not echo it. A refresh drops an unsaved clarification result on purpose.

## 15. Polling

`POST` and approval `POST` already wait until the graph stops. The happy path does not poll.

Do not poll `awaiting_approval`. Nothing advances until an approval call.

Do not poll `rejected`, `blocked`, `error`, or `pr_created`.

If a loaded body has `workflow_status` of `pending`, `running`, or `approved`, poll `GET` every 5 seconds, at most 12 times (about one minute), then stop and show a Refresh action. Those three values are the only ones that can mean another invoke is still writing the same checkpoint, or that a resume stopped early. A network failure during a poll stops the loop and shows the unavailable banner with the last good body kept. The operator retries with Refresh. There is no backoff ladder and no WebSocket.

`/health` and `/ready` are read once when the shell loads, and again when the operator uses Refresh after a connection failure. They are not a workflow poll.

## 16. Health and readiness presentation

Header text, not a green-only dot:

- `/health` 200: `API process responded.`
- `/health` failed: `API process did not respond.`
- `/ready` 200: `Application process is ready to accept requests.`
- `/ready` 503: `Application process is not ready.`

Do not say that AWS, OpenAI, GitHub, Langfuse, or the Terraform Registry is reachable. The indicator does not authorize the operator.

## 17. Routing and deep links

`router.ts` reads `location.pathname`. `/requests/{request_id}` decodes one segment and calls `GET`. `/` is the composer. Any other path shows a short not-found line and a link home. The API remains the authority for id validity: a bad id still calls `GET` or surfaces `400` from the client only after the server responds. The client may refuse to navigate when the segment contains `/`, but the server check stands.

Packaged FastAPI must serve `index.html` for `/` and `/requests/{request_id}` so a refresh does not 404 the document. API paths stay API paths. This fallback is Gate C. It is not implemented here.

Direct browser navigation to `http://127.0.0.1:8000/requests/{id}` is the packaged deep link. In development it is the Vite origin with the proxy.

## 18. Types

Hand-write `api/types.ts` from `schemas.py` and the error envelopes in `routes.py`. The DTO surface is one response model and a dozen error codes. A generator would add a toolchain step and an OpenAPI snapshot for little drift reduction.

FastAPI already publishes `/openapi.json` because `create_app` does not disable docs. The UI must not require a human to use `/docs`. Contract tests compare fixture JSON (taken from existing API tests' public bodies) to the client parser. OpenAPI codegen stays deferred until the public models grow.

Do not generate types in the design turn.

## 19. Local development

Two processes:

- Existing API: `python -m iac_agent.api` on `127.0.0.1:8000`, or the compose stack on that same host port.
- Vite dev server on `127.0.0.1:5173`.

Vite proxies `/api`, `/health`, and `/ready` to `http://127.0.0.1:8000`. The browser talks only to Vite. Production builds do not set a CORS origin and do not change FastAPI CORS. There is no CORS config today; this design does not add one.

The dev proxy is not a production bind change. Compose remains loopback.

## 20. Docker

Gate C adds a Node build stage in front of the current runtime stage. The runtime stage stays Python 3.12, uid 10001, Terraform 1.16.1, Checkov 3.3.13, the trusted modules, and the offline AWS provider mirror. Node is not installed in the runtime stage. Static files are copied into an image path the runtime user can read and not write, same as the application tree.

`.dockerignore` will need to exclude `ui/node_modules` when the package exists. That edit belongs to Gate C, not this turn.

No second compose service. No host port besides `127.0.0.1:8000`. Secrets stay runtime configuration. The UI bundle must not contain API keys.

## 21. Security and trust boundary

Batch 31 does not add authentication or authorization.

The UI does not make the API safe for public exposure. Host publishing remains `127.0.0.1:8000:8000`. `0.0.0.0` inside the container remains only a bind address. Approval through this API on a publicly reachable port would be unsafe, because anyone who can call `POST .../approval` can resume a paused workflow.

The UI renders only public DTO fields. It must not request prompts, raw model output, assumptions, Terraform source, plan JSON, resource addresses, ARNs, account ids, `finding.resource`, `finding.message`, `WorkflowError.message`, stack traces, subprocess output, checkpoints, SQLite internals, workspace paths, tokens, credentials, or GitHub owner, repository, branch, or base branch. The public pull-request URL is allowed.

## 22. Accessibility

The audience is an operator on a laptop, and the layout must remain usable below that width: the regions stack in one column. The workflow status and the approval panel stay above the fold on a laptop.

- The description field has a visible label. Submit, Approve, Reject, Open, and Refresh are `button` elements.
- Status is a text word plus a badge. Color is not the only signal. `blocked`, `error`, and `warn` include the word.
- The submitting state sets `aria-busy` on the form and does not rely on a spinner alone.
- After success, focus the outcome heading. After failure, focus the banner. The approval dialog traps focus and returns focus to Approve on cancel.
- Findings are a table with column headers: policy, status, severity.
- No animation beyond the browser's native focus ring.
- The confirmation dialog is a `dialog` element with an accessible name.

## 23. Visual direction

Restrained engineering UI. System UI font stack. Neutral background, one accent for primary actions, and a separate destructive treatment for Reject. Dense spacing, left-aligned, a single main column with a max width around 72rem.

Status is a text badge (`awaiting approval`, `blocked`, `pull request created`) using the server value as the accessible name. Plan counts are three labeled numbers in a row: add, change, destroy. Destructive change is a sentence under them when the boolean is true.

Findings are a table, not cards. The approval panel is a bordered region directly under the status, with Approve as the primary button and Reject as the secondary destructive button. Errors are a banner at the top of the outcome column, icon-free, with the stable message.

No marketing hero, no chart library, no illustration.

CSS is not written in this turn.

## 24. Test strategy

### Unit and component

Vitest and React Testing Library, in `ui/`. Cover the form disable-on-submit behavior, DTO rendering, plan counts, findings rows, each workflow status, the approval panel's presence and absence, the approve dialog, and each error banner. Fixtures are JSON objects shaped like `RequestResponse` and the error envelopes.

### API client

Mock `fetch`. Assert mapping for 200, 201 (including `Location` not required for rendering), 400, 404, 409 `request_exists`, 409 `approval_conflict` with `request`, 500, 502, 503, 504, and a rejected `fetch`.

### Integration

Keep using the existing FastAPI tests with injected fakes. The UI client tests do not replace them. A browser-level test starts `create_app(holder)` with a fake interpreter and a fake publisher, the same pattern as the current API tests: no OpenAI, AWS, GitHub, or Langfuse call.

### Browser

Playwright, one path: operator submits a prompt, the fake workflow returns `awaiting_approval` with a plan and at least one finding, the operator confirms Approve, the UI shows `pr_created` and the fake pull-request URL. A second short case: Reject ends on `rejected` with the panel gone. Do not install Playwright in this turn.

Python API tests stay the contract source. The browser test is the operator path.

## 25. UI capability matrix

| UI capability | Endpoint | Fields | Available | Notes |
| --- | --- | --- | --- | --- |
| Submit infrastructure request | `POST /api/v1/requests` | `natural_language_request` | YES | Server generates `request_id` when omitted. |
| Clarification | `POST` 200 | `outcome`, `resolution.field`, `reason`, `allowed_values`, `intent` | YES | Not durable. `workflow` null. Next step is a new POST. |
| Unsupported intent | `POST` 200 | `outcome`, `resolution.reason`, `detail`, `intent` | YES | Not durable. |
| Request id | POST, GET, approval | `request_id` | YES | |
| Intent enums | POST only | `intent.*` | YES on POST, NO on GET | Show unavailable after reload. |
| Architecture and components | POST only | `resolution.architecture`, `components` | YES on POST, NO on GET | Same. |
| Resource name | POST and GET | `resolution.name` | YES | May be null. |
| Workflow status and stage | POST 201, GET, approval | `workflow.workflow_status`, `current_stage` | YES | Stage may be null. |
| Plan counts | same | `workflow.plan.add/change/destroy`, `destructive_change_detected` | YES | Null plan means no summary. |
| Security findings | same | `findings[].policy_id/status/severity` | YES | No resource or message. |
| Security status | same | `workflow.security_status` | YES | May be null. |
| Error stage and type | same | `workflow.error.stage`, `error_type` | YES | No error message field. |
| Awaiting approval | same | `approval_available`, status | YES | Panel only when `approval_available`. |
| Approve | `POST .../approval` | `decision=approve` | YES | Confirm first. Render returned body. |
| Reject | `POST .../approval` | `decision=reject` | YES | |
| Idempotent repeat | approval 200 | current projection | YES | Do not treat as a new transition. |
| Approval conflict | approval 409 | `request` | YES | Replace the view. |
| PR URL | workflow body | `pull_request.url` | YES | URL only. |
| Apply not executed | every success body | `terraform_apply` | YES | Display only. No apply action. |
| Recover by request id | `GET /api/v1/requests/{id}` | projection | YES | |
| Health / ready | `GET /health`, `GET /ready` | `status` | YES | Local process only. |
| Request history | — | — | NO | No list endpoint. Deferred. |
| Terraform source | — | — | NO | No route. |
| Raw plan JSON | — | — | NO | |
| Finding resource or message | — | — | NO | |
| Workflow error message | — | — | NO | |
| GitHub owner, repo, branch | — | — | NO | |
| Durable clarification thread | — | — | NO | |
| Auth, users, public deploy | — | — | NO | |

Anything marked NO stays out of Batch 31 implementation.

## 26. Backend gaps

No public DTO change is required for v1.

The only backend work is Gate C static hosting: serve the built files and return `index.html` for the two client routes without intercepting `/api`, `/health`, or `/ready`. That is serving, not a new application capability.

Not gaps to fill in this batch: request lists, persisted clarification, richer GET projections, auth, CORS, websockets.

## 27. Risks

- A refresh after `201` hides architecture and components. The unavailable label has to be obvious so operators do not think the architecture disappeared from the workflow.
- Approval responses are also thin projections. The same label applies the moment Approve or Reject returns.
- `approved` may be observed briefly or after a crashed resume. The UI must not offer Approve again unless `approval_available` is true.
- Serving `index.html` for unknown paths would hide API 404s if the fallback is too broad.
- Putting the last request id in `localStorage` would let a later browser session approve a paused workflow on a shared machine. The URL-only choice avoids that.
- The lifespan still refuses to serve without GitHub and OpenAI configuration. The UI cannot fix that. `/ready` will not explain it.

## 28. Deferred work

Request history, auth, public deployment, websockets, OpenAPI code generation, React Router, a second container, CORS, and any widening of `WorkflowView` or the public DTO.

## 29. Locked decisions

Approved. These decisions are the implementation baseline.

1. React, TypeScript, and Vite. Not server-rendered FastAPI pages.
2. Static assets in the existing container. Node only in the image build stage. One compose service.
3. Client routes `/` and `/requests/{request_id}`.
4. The request id lives in the URL only. No `localStorage` or `sessionStorage`.
5. No polling on the happy path. Five-second `GET` only for `pending`, `running`, and `approved`, at most one minute, then a manual Refresh.
6. Confirmation dialog for Approve. Reject is a single explicit button. No optimistic status.
7. Hand-written TypeScript DTOs. Fixture contract tests. No codegen in v1.
8. Vitest, React Testing Library, and one Playwright path against `create_app` with fakes.
9. Vite dev proxy to `127.0.0.1:8000`. No production CORS change.
10. Component inventory in section 10.
11. Clarification stays on `/`, shows field, reason, and allowed values, and continues only as a new `POST`. It is not saved.
12. Submission-only fields render from the POST body until the next GET or approval response, then show unavailable.
13. Health copy is process liveness. Ready copy is holder presence. Neither claims external services.
14. Packaged UI is same-origin on `127.0.0.1:8000`. No new published port.
15. No API behavior change. Gate C may mount static files and an SPA fallback that does not cover `/api`, `/api/*`, `/health`, or `/ready`.
16. Node exists only at build time. The final image does not run Node.
17. One container. Compose keeps `127.0.0.1:8000:8000`. `0.0.0.0` inside the container is only a bind address.
18. No Redux, Zustand, XState, TanStack Query, or another state framework unless implementation discovers a concrete requirement. The checkpoint stays authoritative. No optimistic approval state.
19. Hand-written TypeScript DTOs. OpenAPI generation stays deferred. The UI renders only public DTO fields. The pull-request URL is allowed. Terraform source, raw plan JSON, addresses, ARNs, account ids, finding resource/message, `WorkflowError.message`, subprocess output, checkpoints, workspace paths, credentials, tokens, and GitHub owner/repository/branch/base branch are not.
20. The UI is unauthenticated. This batch does not make the API safe for public Internet exposure. `/health` is process liveness. `/ready` is holder presence. Neither is dependency connectivity.

## 30. Implementation gates

These gates are the approved split. The executable task list is a separate plan. This document does not authorize starting that work.

### Gate A — frontend foundation

Package and Vite toolchain, hand-written client, shell, composer, open-request control, summary, workflow status, plan counts, and findings. Dev proxy only. No Dockerfile change and no approval calls required to finish the gate, though the client may already know the approval types.

### Gate B — HITL operator flow

Approve with confirmation, Reject, in-flight disable, 409 reconciliation, deep link reload, error banners, and the Playwright path against a fake-backed `create_app`. Still no production image change.

### Gate C — packaged runtime

Node build stage, static files in the existing runtime image, FastAPI asset mount and client-route fallback, Docker acceptance that the UI is served on the loopback port and that a durable approve still works through the browser or the same API, docs, and the existing deterministic suite. No second container, no auth, no CORS, no apply or destroy.

## 31. Human review

Section 29 is approved. This design commit does not add files under `ui/`, does not install packages, and does not change production code.
