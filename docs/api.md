# Local HTTP API

FastAPI is an inbound adapter over `IntentResolutionService` and `IacApplication`. Routes do not call LangGraph nodes, Terraform, Checkov, OpenAI, the Langfuse SDK, GitHub, or the SQLite checkpointer directly. There is no second request store. `request_id` is the workflow `thread_id`.

`python -m iac_agent.api` serves this same app. Outside Docker the process listens on `127.0.0.1` port 8000. Operator routes require one local operator secret. That check is not RBAC and not authorization for public Internet exposure. This boundary is for local development.

## Routes

- `GET /health` returns `{"status":"ok"}`. It does not call AWS, OpenAI, Langfuse, GitHub, or the Terraform Registry, and it does not validate external connectivity.
- `GET /ready` returns `{"status":"ready"}` when the application holder exists, and `503 {"status":"not_ready"}` when it does not. Readiness is that local check. It does not validate AWS, OpenAI, GitHub, Langfuse, the Terraform Registry, or any other external service. Langfuse is not a readiness probe and does not authorize requests.
- `POST /api/v1/requests` accepts `natural_language_request` and an optional `request_id`. An omitted id is generated with the existing request-id helper. The route calls `IntentResolutionService.submit`.
- `GET /api/v1/requests` lists the newest checkpointed requests.
- `GET /api/v1/requests/{request_id}` calls `IacApplication.read`.
- `POST /api/v1/requests/{request_id}/approval` accepts `{"decision":"approve"}` or `{"decision":"reject"}` and calls `IacApplication.resume` only when the durable status is `awaiting_approval`.

Those four `/api/v1/requests` routes require `Authorization: Bearer <operator-secret>`. `GET /health`, `GET /ready`, and the SPA HTML and static assets do not. Authentication runs before request lookup or application behavior. A missing header, a malformed bearer, and an incorrect secret all return HTTP 401 with this body only:

```json
{"error": "unauthenticated", "message": "Authentication is required."}
```

The 401 body has no `request_id`. It does not say whether an id exists.

There is no Terraform-source route.

## Lifecycle

`POST` interprets the prompt and resolves it. A clarification or an unsupported architecture returns 200 with `workflow` set to null. Those outcomes are not written to SQLite, so a later `GET` of that id is 404.

A resolved architecture is submitted to the existing workflow. The usual secure result is 201, `Location: /api/v1/requests/{request_id}`, and `outcome` `awaiting_approval`. The checkpoint is the LangGraph SQLite snapshot. Duplicate detection calls `read`. If that snapshot exists, `POST` returns 409 `request_exists` and does not submit again. Detection does not use process memory, so a restart does not make an existing checkpoint look new.

`GET` returns the projected checkpoint. `read` treats a LangGraph snapshot whose `created_at` is null as missing, so a valid but unknown id is 404 `{"error":"request_not_found","message":"Request not found."}`. The body is not a synthetic `pending`, `submitted`, or `awaiting_approval`. `get_state` still maps an empty snapshot to `pending` for the CLI. HTTP does not call `get_state`.

Approval reads the checkpoint first. `awaiting_approval` is the only status that resumes the graph. A repeated approve returns 200 without resuming when the checkpoint is already `pr_created` or `approved` and the stored decision is approve. A repeated reject returns 200 without resuming when the checkpoint is `rejected` and the stored decision is reject. Approve after reject, reject after approve, and any decision while the status is `blocked` or `error`, return 409 `approval_conflict` with the current request projection. Those calls do not resume.

## Public response

The HTTP body is an explicit projection. It may include `request_id`, the approved intent enums, architecture and component display fields when the submission still has the resolved spec, the resolved resource name, plan add/change/destroy counts, finding `policy_id`, `status`, and `severity`, workflow status and stage, error `stage` and `error_type`, approval state, and `pull_request.url`.

It does not include the raw prompt, model output, assumptions, unresolved clarification text, Terraform source, Terraform plan JSON, Terraform addresses, ARNs, AWS account ids, raw Checkov JSON, `finding.resource`, `finding.message`, `finding.source`, `WorkflowError.message`, exception text, stack traces, subprocess output, checkpoint bodies, workspace paths, environment mappings, credentials, or GitHub owner, repository, branch, and base branch. The CLI still prints `WorkflowError.message`. Findings on the wire are only `policy_id`, `status`, and `severity`. The pull-request object is `url` only.

`GET` reconstructs that projection from `WorkflowView`. A reconstructed view has the resource name and the workflow fields. It does not carry architecture, components, `matched_pattern`, or the full intent, so those fields are null or empty on `GET`. Batch 29 does not invent them and does not widen `WorkflowView` to copy the `POST` body. `POST` of a resolved request still projects the spec it just resolved.

## Observability

Batch 28 telemetry stays under the application services. `POST` and approval receive it through `submit` and `resume`. `GET` and `read` do not emit workflow telemetry. The API does not import the Langfuse SDK and does not store a Langfuse trace id. `request_id` remains the correlation seed. The Langfuse adapter stays optional and off unless configured, as described in `docs/observability.md`.

## Local Docker runtime

Batch 30 packages this same application as one local container. `compose.yaml` builds that image. The runtime is Python 3.12, the FastAPI application served by Uvicorn, Terraform 1.16.1, Checkov 3.3.13 in an isolated `/opt/checkov` environment, the trusted Terraform modules, and an offline filesystem mirror of `hashicorp/aws`. The container command is `python -m iac_agent.api`. The image pins `python:3.12-slim-bookworm` by digest.

The container binds `0.0.0.0:8000`. Compose publishes only `127.0.0.1:8000:8000`. 0.0.0.0 inside the container is network binding, not authentication or authorization. Reaching the published port is not enough to call an operator route. The caller also needs the configured operator secret. That is a single-operator local authentication mechanism, not approval for public Internet exposure. The operator UI is packaged into this same image.

The process runs as user `iac`, uid 10001. Compose does not set privileged mode, does not mount the Docker socket, and does not use host networking. The runtime user cannot write `/opt/iac-agent`, the trusted modules under that root, `/opt/checkov`, the Terraform binary, or the provider mirror. It can write `/var/lib/iac-agent/state`, `/var/lib/iac-agent/workspaces`, `/home/iac`, and `/tmp`.

`IAC_AGENT_TRUSTED_MODULE_ROOT=/opt/iac-agent` in the container. An unset value on the host still resolves modules from the checkout. The request does not choose that root.

SQLite is the durable HITL store. The named volume `iac-agent-state` is mounted at `/var/lib/iac-agent/state`, and the database path is `/var/lib/iac-agent/state/state.db`. The database, WAL, and SHM files stay in that mounted directory. Generated workspaces at `/var/lib/iac-agent/workspaces` are ephemeral and are not on that volume.

The acceptance proof removes container A after a request reaches `awaiting_approval` and the checkpoint is on the volume. Replacement container B mounts the same volume, opens a new process, checkpointer, graph, and application, and `GET` reconstructs `awaiting_approval`. Approve resumes that checkpoint to `pr_created`. Process-local state from A does not survive. B does not need A's workspace.

The AWS provider mirror supplies `hashicorp/aws` without a registry download at runtime. The acceptance test ran credential-free `terraform init`, `validate`, and `plan` with container networking disabled. Checkov 3.3.13 is invoked as `checkov` on `PATH` and is not installed into the application virtualenv.

The image sets `IAC_AGENT_OBSERVABILITY=off`. Langfuse stays optional. Installing the Langfuse extra does not enable telemetry.

`.env.example` lists variable names and empty or example-safe values. Application credentials are runtime configuration. They are not copied into the image.

The production lifespan still requires GitHub and OpenAI configuration before `python -m iac_agent.api` serves, including for a request that would not call those integrations. That eager startup requirement is unchanged technical debt. It is separate from operator authentication. `IAC_AGENT_OPERATOR_SECRET` is also mandatory. A missing, blank, or whitespace-only value refuses startup and names the variable without including the value. There is no default. The secret is runtime environment configuration. The application does not persist it.

Tests that need a Docker daemon use `@pytest.mark.docker`. Deterministic CI runs `pytest -m "not real_tool and not real_llm and not docker"`. The `real_tool` job is unchanged. The Frontend job runs `npm ci`, `npm test`, and `npm run build` in `ui/`. It does not publish an image.

## Operator UI

The local operator UI is a React and Vite application in `ui/`. During development, `npm run dev` serves it on `127.0.0.1:5173` and proxies `/api`, `/health`, and `/ready` to `127.0.0.1:8000`.

The production UI is same-origin static files from FastAPI. The image build compiles the UI with Node and copies only the built files to `/opt/iac-agent/ui`. `IAC_AGENT_UI_DIST=/opt/iac-agent/ui`. Node is build-time only. The runtime image does not run Node, npm, or Vite, and it does not add a second service or a second host port. Compose still publishes only `127.0.0.1:8000:8000`.

`GET /` returns the packaged `index.html`. `GET /requests/{request_id}` returns that same page so a reload can recover the request. The request id in the URL is the durable key. The page loads it with `GET /api/v1/requests/{request_id}`. The SQLite checkpoint remains authoritative. The browser does not store the workflow in local storage.

Approve asks for confirmation before the approval POST. Reject sends immediately. A 409 `approval_conflict` replaces the displayed request with the request embedded in that response. The page polls every 5 seconds, at most 12 times, only while the status is `pending`, `running`, or `approved`.

The UI renders the public request DTO only. It does not receive credentials, Terraform source, raw plan JSON, checkpoint contents, finding messages, finding resources, or `WorkflowError.message`.

`GET /api/v1/requests` lists the newest checkpointed requests. The index stores the request id and the server creation time. Workflow status, approval availability, security status, and name are read from the checkpoint when the list is built. The list does not include checkpoints created before the index existed; those requests remain available at `GET /api/v1/requests/{request_id}`. A failed index write does not change the create response. The list route requires the operator secret. The index itself is not an authorization model and does not make the API safe for public Internet exposure.

The default page is 20 requests. `limit` may be an integer from 1 through 50. There is no cursor and no offset. A stale index row whose checkpoint is gone is omitted, and the page is not filled from older rows. `request_index` in the existing `state.db` stores only `request_id` and `created_at`. Recent requests is discovery. The checkpoint remains the workflow authority. Compose remains `127.0.0.1:8000:8000`. Batch 33 did not authorize public exposure, and Batch 34 does not either.

Batch 32 presents that same public request DTO. It does not add a route, a field, or a workflow state. Server status values stay visible. A destructive plan is still the server boolean, and the page still says "Destructive change detected."

The operator enters `IAC_AGENT_OPERATOR_SECRET` in the page. React keeps that value in memory only. Authenticated API calls send it as `Authorization: Bearer`. SPA navigation can retain it because the React application stays mounted. A browser reload reconstructs the application and loses it, so the operator enters it again. The application does not store it in localStorage, sessionStorage, IndexedDB, cookies, the URL, query parameters, public API DTOs, checkpoints, or `request_index`. It must not be placed in URLs or request bodies. There is no `VITE_` build-time copy.

This is not RBAC. It is not OAuth, OIDC, JWT identity, users, roles, tenants, TLS, a reverse proxy, or public Internet exposure. The approving actor is not persisted. There is no `approved_by` field and no audit trail. The secret is not a durable user identity.

Approval semantics are unchanged. `approval_available` controls whether the actions exist. Approve requires confirmation. Reject is immediate. The returned server state is authoritative. HTTP 409 reconciliation is unchanged. The UI does not invent a workflow state before that response. Terraform apply is still not executed.

The operator UI does not make this API safe for public Internet exposure. GET /health and GET /ready do not prove AWS, OpenAI, GitHub, Langfuse, or Terraform Registry connectivity.

The state plane is required before the operator runtime serves. It is the SQLite checkpoint and `request_index` in the same `state.db`. Intent interpretation and source-control publishing are optional. A group is configured when every required value is present and valid, absent when the whole group is omitted or whitespace, and partial when configuration was started but is incomplete or inconsistent. A partial group fails startup. GITHUB_BASE_BRANCH=main alone does not configure publication. A non-default branch without the GitHub group is partial. A blank branch beside a complete GitHub group is invalid and fails startup. Submit of a new request requires the interpreter group. An existing request does not. List and detail do not require GitHub or OpenAI. Reject does not require GitHub. Approve requires the GitHub publication group. That check applies only when the approve would resume. `GET /health` means the process is alive. /ready means the state plane is open, not that GitHub or OpenAI is configured or reachable. Ready does not mean submit or approve is available. A missing capability is HTTP 503 `{"error": "capability_unavailable", "message": "..."}`. The submit message begins `Intent interpretation is not configured.` The approve message begins `Source-control publishing is not configured.` `capability_unavailable` is not a workflow ERROR, an authentication failure, an approval conflict, a missing request, or a provider network failure. Success responses do not grow a capability field.

## What this batch does not do

This API does not authorize callers beyond the single operator secret, deploy to AWS, publish through real GitHub in the HTTP acceptance test, generate arbitrary Terraform, expose a workflow event history, or return Terraform source. The acceptance test uses a fake source-control port and a local SQLite file. Its published URL is the fake `https://example.invalid/pull/7`.
