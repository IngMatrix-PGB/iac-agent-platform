# Batch 34 — operator authentication boundary

## 1. Executive summary

Batch 34 should establish one trust boundary: a caller of the operator HTTP API must present a verified operator principal before any request, list, read, or approval route runs. The current boundary is network reachability. Compose publishes `127.0.0.1:8000:8000`, and every route is anonymous. `GET /api/v1/requests` now enumerates durable request ids and selected workflow metadata. Changing that publish address, or any other path that makes the port reachable beyond the local operator, is unsafe until those routes reject an anonymous caller.

This batch does not select a hosted identity provider, add RBAC, tenants, request ownership, an approval audit record, TLS, or a remote runtime. It does not decouple process startup from GitHub and OpenAI configuration. The principal exists only for the duration of the HTTP request. `RequestResponse`, `RequestListItem`, the approval decision model, `request_index`, and the LangGraph checkpoint stay unchanged.

The approved mechanism is one operator secret supplied by runtime configuration. It is a bootstrap control for this single-operator local architecture. It is not the final identity architecture. The browser keeps that secret in memory only and sends it as `Authorization: Bearer`. GitHub login, OAuth, OIDC, Cognito, Auth0, JWT issuance, users, roles, RBAC, and tenants are out of scope.

## 2. Verified starting state

Discovery ran against `origin/main` at `ecea016b3cafa484bc7a2caee2296b3f015f877d`. The working tree was clean before this document. `2ed66af719bd5a05860a1756273cde50b2558e93`, the rewritten historical main that contains the merged Batch 33 index, is an ancestor of that commit. Batch 32 presentation and Batch 33 index code and docs are in this tree:

- `docs/superpowers/specs/2026-09-28-batch32-design.md`
- `docs/superpowers/specs/2026-09-29-batch33-design.md`
- `src/iac_agent/persistence/request_index.py`
- `GET /api/v1/requests` in `src/iac_agent/api/routes.py`
- Recent requests in `ui/src/pages/compose-page.tsx`

`docs/roadmap.md` still says authentication, RBAC, multi-user access, tenants, and public deployment are not started.

## 3. Current architecture

One FastAPI process is the operator runtime. `python -m iac_agent.api` calls `serve()`, which binds `IAC_AGENT_BIND_HOST` (default `127.0.0.1`) and `IAC_AGENT_PORT` (default `8000`). The Docker image sets `IAC_AGENT_BIND_HOST=0.0.0.0`. Compose publishes only `127.0.0.1:8000:8000`. `docs/api.md` states that the in-container bind is not authentication.

The lifespan in `src/iac_agent/api/app.py` always loads application config, the GitHub token, the OpenAI interpreter config, and the OpenAI API key, then opens `open_intent_application`. `/health` returns `{"status":"ok"}` and does not read the holder. `/ready` is 200 only when `app.state.holder` exists, and 503 otherwise. Neither probe contacts AWS, OpenAI, GitHub, Langfuse, or Terraform Registry.

`ApplicationConfig` holds workspace root, state db path, and non-secret GitHub coordinates. `GITHUB_OWNER`, `GITHUB_REPOSITORY`, `GITHUB_COMMIT_AUTHOR_NAME`, and `GITHUB_COMMIT_AUTHOR_EMAIL` have no defaults. `GITHUB_TOKEN` is a separate `SecretStr`. `IAC_AGENT_LLM_PROVIDER` and `IAC_AGENT_LLM_MODEL` are required to construct the interpreter. `OPENAI_API_KEY` is required on that path. `IAC_AGENT_OBSERVABILITY` defaults to off. Langfuse is constructed only when that value is `langfuse`, and missing Langfuse keys fail that mode without becoming a readiness signal.

`open_intent_application` opens one SQLite checkpointer and a second connection for `request_index` on the same `state.db`. The checkpoint is the workflow authority. `request_index` stores only `request_id` and `created_at`. Index insert happens after a durable workflow submission. Resume does not record. Clarification, unsupported, and interpreter failures are not indexed. A failed index write is logged and does not fail the workflow.

Routes call application services only. `POST /api/v1/requests` submits natural language. `GET /api/v1/requests` lists up to 50 indexed requests, default 20. `GET /api/v1/requests/{request_id}` reads one checkpoint. `POST /api/v1/requests/{request_id}/approval` accepts exactly `approve` or `reject`. There is no CORS middleware. The packaged UI is same-origin. The Vite dev server proxies `/api`, `/health`, and `/ready` to `127.0.0.1:8000`.

The public detail DTO is `RequestResponse`. Findings on the wire are `policy_id`, `status`, and `severity`. The plan object is add/change/destroy counts plus `destructive_change_detected`. The pull-request object is `url` only. `WorkflowErrorDTO` is `stage` and `error_type`. `terraform_apply` is fixed to `not_executed`. `RequestListItem` is six fields: `request_id`, `created_at`, `workflow_status`, `approval_available`, `security_status`, and `name`. The browser does not persist workflow state in `localStorage`, `sessionStorage`, or `IndexedDB`.

`TerraformRunner.plan` exists. There is no apply or destroy method on that runner. Approval publication, when it runs, calls the GitHub source-control port with the server-side token. The browser never receives that token.

The container user is `iac`, uid 10001, with no Docker socket and no host network. The Docker `HEALTHCHECK` calls `http://127.0.0.1:8000/health` from inside the container. SQLite on the named volume `iac-agent-state` is the durable HITL store. Workspaces under `/var/lib/iac-agent/workspaces` are ephemeral.

There is no `User`, `Actor`, `Principal`, `Subject`, `Session`, `Tenant`, `Role`, or request `Owner` type in the application. `src/iac_agent/domain/approval.py` says there is no authenticated-caller identity, and it refuses to store `approved_by`, `reviewer`, comment, or a timestamp until a verified principal exists upstream. AWS `principal` strings in Terraform renderers are resource trust policies, not operator identity.

## 4. Post-Batch-33 operator journey

The code matches this local journey:

1. The compose page submits `natural_language_request` to `POST /api/v1/requests`.
2. The intent interpreter resolves that text. Clarification and unsupported results return HTTP 200 and are not indexed.
3. A workflow submission invokes the graph, writes the LangGraph checkpoint, then records `request_id` and `created_at` in `request_index`.
4. The compose page loads Recent requests once from `GET /api/v1/requests` with no query string. It does not poll the list and does not refresh it after submit.
5. A row navigates to `/requests/{request_id}`. Reload reads `GET /api/v1/requests/{request_id}`.
6. While the view is `awaiting_approval`, the operator approves or rejects through `POST /api/v1/requests/{request_id}/approval`.
7. Approve can publish a GitHub pull request through the server-side source-control port. The public body returns the pull-request URL. `terraform apply` remains `not_executed`.

Nothing in that path identifies the human. Anyone who can open the published port can compose, list, read, and approve.

## 5. Current trust boundary

The operator trust boundary is the published port. Outside Docker the default listen address is loopback. In Docker the process listens on all interfaces inside the network namespace, and Compose is what keeps the host mapping on loopback. `docs/api.md` and the Batch 33 design both say that arrangement is not authentication and is not approval for public exposure.

`GET /health` and `GET /ready` are intentionally anonymous and weak. They prove the process is up, and that the holder was constructed. They do not prove that the caller is the operator.

GitHub, OpenAI, and Langfuse credentials are server-side. Their presence at startup does not authenticate the browser.

## 6. Production-boundary gaps

Leaving loopback means the published port is reachable by a caller who is not the person at the keyboard. That change is not a Kubernetes decision. It is already possible by editing the Compose publish line or by running `IAC_AGENT_BIND_HOST` on a reachable interface outside Docker. The application cannot see the host publish address. The in-container bind is already `0.0.0.0`, so bind address is not a reliable signal of exposure.

What that reachability would expose today:

- Network: the full anonymous API and the same-origin UI.
- TLS: none in this repository. Termination is not designed here.
- Authentication: none.
- Authorization: none. There is one implicit operator.
- Enumeration: `GET /api/v1/requests` returns ids plus workflow status, approval availability, security status, and name.
- Approval: an anonymous POST can approve or reject and can cause a GitHub mutation.
- Secrets: still only on the server, but the server will use them on behalf of any caller who can hit approval.
- Durable state: one SQLite file on a local volume. That is enough for one container replacement. It is not a multi-instance store.
- Workspaces: ephemeral container filesystem.
- Terraform: plan only. Apply is still absent, which limits blast radius but does not limit plan disclosure or GitHub publication.
- Rate limiting: none.
- CORS: none, because the UI is same-origin. A split origin would be a new decision.
- Health: `/health` stays useful for the container probe. `/ready` does not prove dependencies.
- Logs and traces: Langfuse is optional and off. It is not an access log.
- Container lifecycle: one process, uid 10001, grace period 30s.

"Runs in Docker" is not production readiness. The image is a local packaging of the same unauthenticated application.

## 7. Candidate analysis

### A. Identity / authentication boundary

Current implementation: no caller identity. Approval documentation already waits for a verified principal.

Concrete gap: operator routes accept any caller who can open the port.

Architectural value: replaces "reachable" with "proved to be the operator" before any later exposure decision.

Security implications: stops anonymous enumeration and anonymous approval. A single shared secret is not multi-user safety and is not TLS.

Dependencies: none inside the current code. It does not require RBAC, a new database, or a new runtime.

Public API impact: operator routes gain an authentication failure. Success bodies stay the same.

Persistence impact: none, if the principal stays request-scoped.

Workflow impact: none. The graph still receives `approve` or `reject` with no actor.

UI impact: the same-origin client must send the credential. The page shell can still load.

Operational impact: local and Compose runs must have the operator secret. The Docker healthcheck must keep using unauthenticated `/health`.

Testing implications: missing and wrong credentials fail closed; `/health` and `/ready` stay anonymous; DTO fixtures stay free of secrets.

Enables afterward: a later batch can store the principal on an approval record, then consider exposure.

Does not solve: who among several people may approve, remote deployment, startup without GitHub and OpenAI, TLS, or apply.

### B. Authorization / operator ownership / RBAC

Current implementation: no roles and no request owner.

Concrete gap: even an authenticated caller would still be allowed to see and decide every indexed request, because the product is one operator.

Architectural value: necessary only when a second principal exists.

Security implications: roles without a principal are labels. Ownership without auth cannot be enforced.

Dependencies: required prerequisite is a verified principal. Not required for the first authentication boundary.

Public API, persistence, workflow, and UI impact: would add owner or role fields and filtering. That is a different batch.

Does not solve authentication by itself.

### C. Runtime exposure / remote deployment

Current implementation: loopback publish, in-container `0.0.0.0`, local volume, no TLS, no orchestrator.

Concrete gap: there is no approved non-loopback deployment.

Architectural value: this is the outcome that authentication is meant to make discussable. Doing it in the same batch as authentication mixes the boundary with the exposure.

Dependencies: required prerequisites include authentication, a secret-delivery story, and an explicit exposure decision. Durable SQLite on one volume does not become a remote shared store by publishing a port. `/ready` still would not prove GitHub or OpenAI.

Does not solve identity.

### D. Lifespan and dependency decoupling

Current implementation: `src/iac_agent/api/app.py` lifespan calls `load_application_config_from_env`, `load_github_token_from_env`, interpreter config, and `load_openai_api_key_from_env` before it yields. `docs/api.md` calls this unchanged technical debt. Langfuse is already optional.

Concrete gap: the process will not serve, and `/ready` stays 503, unless GitHub coordinates, the GitHub token, and OpenAI settings exist, even for a request that would not call them.

Architectural value: makes local and future runtimes easier to boot. It does not change who may call the API.

Dependencies: independent of authentication. Docker acceptance currently depends on eager startup, so a change has its own regression surface.

Classification: later hardening, not Batch 34, and not a prerequisite of the authentication boundary.

Does not solve anonymous enumeration or anonymous approval.

### E. Secret and configuration hardening

Current implementation: tokens use `SecretStr` and are not fields of `ApplicationConfig`. The browser does not receive them. `.env.example` lists names only. There is no secrets manager.

Concrete gap: secrets are process environment variables. That is appropriate for the local container and is not an identity system.

Dependencies: independent. A manager becomes relevant when a remote runtime is chosen. It does not authenticate the browser.

Does not solve the operator trust boundary.

### F. Readiness and health semantics

Current implementation: `/health` is liveness. `/ready` means the holder exists. The Docker healthcheck uses `/health`.

Concrete gap: probes do not check GitHub, OpenAI, Langfuse, AWS, or Terraform. That is deliberate.

Dependencies: independent. Changing `/ready` to probe external systems would make orchestration flap on vendor outages and would not authorize callers.

Does not solve authentication. Keep the current probe meanings.

### G. Request-index evolution

Current implementation: two columns, insert-once, newest-first, stale rows omitted, no backfill, no cursor.

Concrete gap: none for the local discovery journey Batch 33 just closed. Pagination, search, and backfill are product expansions.

Dependencies: independent. Adding an owner column before a principal exists would invent an unverifiable attribute, which `approval.py` already refuses to do.

Does not solve who may list the index.

### H. Auditability of approval decisions

Current implementation: the decision is `approve` or `reject` only. No actor, comment, or timestamp is stored.

Concrete gap: a future audit record needs a verified principal. Writing a name now would be the false audit trust Batch 13 rejected.

Dependencies: required prerequisite is the principal from candidate A. Persistence of that principal is a follow-on, not the first boundary.

Does not authenticate the caller by itself.

### I. Observability / Langfuse

Current implementation: off unless `IAC_AGENT_OBSERVABILITY=langfuse`. Not a readiness probe and not an authorizer.

Concrete gap: no operator access log. That is useful after a principal exists, so the log can say who called. It is not the boundary.

Dependencies: independent improvement. Not required before authentication.

Does not stop an anonymous caller.

### J. Evaluation hardening

Current implementation: evals grade architecture intent and compositions. They are not on the request path.

Dependencies: independent. They do not change the operator trust boundary.

### K. Additional infrastructure resources

Current implementation: the roadmap still lists EventBridge, SNS, a second Lambda, Cognito on the workload, WAF, and custom domains as not started. Those are resources the agent might generate, not the operator control plane.

Dependencies: independent of the operator boundary. Workload Cognito is not operator authentication.

### L. Exposing the port without a new control

Rejected as a candidate. The repository already treats loopback publication as the only exposure control. Repeating that in a batch does not create a boundary. The dangerous one-line change is already possible.

## 8. Dependency graph

Required before any non-loopback exposure:

- Operator authentication. Without it, reachability is authority, and the request list plus approval POST are the concrete damage.

Required before an auditable approval actor:

- A verified principal. The repository already states this in `approval.py`.

Required before RBAC, tenants, or request ownership:

- A principal, and then a second-principal product decision. One operator does not need roles.

Not required before authentication:

- Lifespan decoupling. The process can demand GitHub and OpenAI at startup and still reject an anonymous HTTP caller.
- Langfuse, evals, new AWS resources, Terraform apply, TLS, and a secrets manager.
- A different `request_index` schema.
- Changing `/health` or `/ready` semantics.

Recommended after authentication, still separate batches:

- Persist the principal on the approval decision.
- Decide whether the port may leave loopback, and only then design TLS and secret delivery.
- Decouple startup so a process can boot without unused GitHub or OpenAI credentials.

Independent improvements, not prerequisites of each other or of this batch:

- Readiness that still must not probe vendors.
- Request-list pagination.
- Observability expansion.
- Evaluation hardening.
- Another workload resource.

These edges are from the code and the Batch 33 design, not from a wish that the roadmap be linear. Batch 33 already recorded that authentication is not required to list local requests, and that it is necessary before non-loopback exposure. This discovery agrees, and treats that exposure as the next unsafe step the current port-publish control does not actually prevent.

## 9. Security analysis

`GET /api/v1/requests` is the new fact. A caller who does not know an id can learn up to 50 ids and, for each, workflow status, whether approval is available, security status, and name. Each id is then a key for `GET /api/v1/requests/{request_id}` and for approval.

If the bind or publish address leaves loopback, that catalog is unauthenticated. Approval can trigger GitHub publication with the server token. The caller does not need the token.

The detail DTO is still thin, and this batch must keep it thin. An authenticated UI must not start returning:

- Terraform source or raw plan JSON
- resource addresses
- `finding.resource` or `finding.message`
- `WorkflowError.message`
- workspace paths
- checkpoint blobs
- GitHub owner, repository, branch, or base branch
- credentials, tokens, or environment variables

Those are already excluded from `RequestResponse` and `RequestListItem`. Authentication does not justify widening them. The list must remain the six current fields. The detail findings remain policy id, status, and severity. The plan remains counts. The pull request remains a URL.

`/health` and `/ready` disclose only a status string. Leaving them anonymous does not disclose the catalog. The static UI shell discloses the application exists. The catalog and the mutations are the routes that must fail closed.

Same-origin is the current browser boundary. Adding CORS so a foreign origin can call the API would widen exposure and is out of scope. The operator secret must not be the GitHub token, the OpenAI key, or a Langfuse key. Those credentials authorize different systems, and the first two are already required for startup.

## 10. Recommended Batch 34 direction

Batch 34 is the operator authentication boundary.

One objective: anonymous callers cannot use the operator API.

Trust boundary: possession of the single operator credential, checked by the server, replaces reachability of the port. Loopback remains how the container is published. This batch does not approve changing that publish.

Why the others wait:

- RBAC and ownership wait until a second principal is a product decision.
- Remote deployment waits until anonymous calls already fail.
- Lifespan decoupling is real debt and a separate batch. It does not identify the caller.
- Approval audit storage waits until this principal exists, then a later batch can persist it.
- Index, eval, Langfuse, probes, and new resources do not change who may call.

## 11. Proposed architecture

Add an HTTP-edge check in front of the operator routes. The check resolves one `OperatorPrincipal` or rejects the call. The principal means "this is the configured operator." It has no user id, role, tenant, or request ownership.

Approved mechanism: one server-only secret, `IAC_AGENT_OPERATOR_SECRET`, loaded as a `SecretStr` and kept off `ApplicationConfig`. There is no repository default. A missing or blank value fails process startup with `MissingConfigurationError` before the server accepts connections. The error names the variable and does not include the value. The Docker image does not set this variable in `Config.Env`. `.env.example` lists the name with an empty value. Compose does not put a value in its `environment` map; the existing `env_file` may supply it. The secret is never a `VITE_` build variable.

The only credential transport is the `Authorization` header:

```http
Authorization: Bearer <operator-secret>
```

That header is conventional HTTP authentication. This repository has no evidence that requires a custom header, a cookie, or a query parameter. The secret is not placed in the URL, the request id, a workflow body, logs, the checkpoint, or `request_index`. The Vite proxy already forwards `/api` and therefore forwards this header. The server compares the bearer value to the configured secret with `hmac.compare_digest` on UTF-8 bytes. A missing header, an empty bearer, a non-`Bearer` scheme, and a wrong secret are the same failure. The comparison result does not say which of those cases occurred.

The check runs before request-id validation, checkpoint lookup, list projection, submit, and resume. A failed check does not reveal whether the request id exists.

Rejected as the default for this batch: inferring safety from loopback. The application bind is `0.0.0.0` in the image, and the process cannot observe the Compose publish address. A loopback bypass would be a bypass of the boundary this batch exists to create.

The Docker `HEALTHCHECK` continues to call `/health` with no credential.

No middleware reads or writes SQLite. No graph node learns the principal in this batch.

## 12. Data ownership / source of truth

The checkpoint remains the workflow authority. `request_index` remains the discovery catalog of `request_id` and `created_at`. The operator secret is process configuration, not a row. The principal is not a stored fact. Approval remains the two-value decision already in the checkpoint. There is still no audit log.

## 13. API implications

These routes require the principal:

- `POST /api/v1/requests`
- `GET /api/v1/requests`
- `GET /api/v1/requests/{request_id}`
- `POST /api/v1/requests/{request_id}/approval`

These stay anonymous:

- `GET /health`
- `GET /ready`
- the static UI assets and the HTML shell, including `GET /` and `GET /requests/{request_id}` as pages

An unauthenticated or invalid operator call returns HTTP 401 and this body only:

```json
{"error":"unauthenticated","message":"Authentication is required."}
```

The body has no `request_id`, no request payload, and no echo of the supplied credential. The response does not use a different status or message for a missing header, a malformed scheme, or a wrong secret. Application methods are not called. After a valid credential, a missing checkpoint is still `request_not_found` and an invalid id is still `invalid_request_id`. Invalid list limits stay HTTP 422.

Success schemas do not change. `RequestResponse` does not gain an actor. `RequestListItem` does not gain an owner. Limit rules stay 1 through 50. Invalid limits stay HTTP 422.

No CORS headers are added.

## 14. Persistence implications

No schema change. No checkpoint field. No `request_index` column. No migration. Existing `state.db` files keep working. The secret is not written to the database, the workspace, or the UI dist.

## 15. UI implications

The packaged UI and the Vite dev client attach `Authorization: Bearer` on `/api/v1/*` only. They do not attach it to `/health` or `/ready`. They do not put the GitHub token, OpenAI key, Langfuse keys, or the operator secret in the built JavaScript.

The React tree keeps the operator secret in memory. It does not use `localStorage`, `sessionStorage`, `IndexedDB`, cookies, or a durable browser cache. A reload clears it, and the operator types it again. The shell shows one credential field and a continue action before compose, recent requests, or review. There is no profile, name, or role. A 401 clears the in-memory value and returns to that field. The header, health indicator, and page shell stay mounted.

## 16. Runtime implications

Local `python -m iac_agent.api` and Compose both need the operator secret in the environment. `.env.example` gains the variable name and no sample value. The image user, uid, volume paths, bind, port, and healthcheck URL stay as they are. Compose continues to publish `127.0.0.1:8000:8000`. This batch does not change `IAC_AGENT_BIND_HOST`.

Startup still requires GitHub and OpenAI configuration. That debt is unchanged on purpose.

`/ready` still means the holder exists. It does not mean the caller is authenticated, and the probe itself stays unauthenticated so the healthcheck does not need the secret.

## 17. Failure semantics

Missing or blank operator secret at startup: the process fails before serving, with an error that names the variable and not the value.

Missing or wrong credential on an operator route: HTTP 401, no workflow effect, no index write.

Interpreter and approval failures keep their current codes when the caller is authenticated.

`/health` stays 200 without a holder and without a credential. `/ready` stays 503 until the holder exists, including when GitHub or OpenAI configuration is missing. Authentication does not mask that.

A leaked secret in a log line or an error body is a test failure.

## 18. Security invariants

- Reachability of the port is not authority for operator routes.
- The in-container bind address is not an authentication signal.
- `/health`, `/ready`, and static assets do not require a credential and do not return request data.
- Operator routes do not run application code for an anonymous caller.
- The principal is not written to the checkpoint, the index, logs, or the public DTOs.
- The operator secret is not the GitHub token, the OpenAI key, or a Langfuse secret.
- Public DTOs do not grow Terraform source, plan JSON, addresses, finding messages, error messages, workspace paths, checkpoint blobs, GitHub coordinates, or credentials.
- No CORS allowance is introduced.
- Compose loopback publication stays in place. This batch is not exposure approval.

## 19. Testing strategy

Unit tests for the secret loader: missing, blank, and repr that hides the value.

Route tests, with a fake holder:

- no credential and a wrong credential on each operator route return 401 and do not call submit, list, read, or resume
- a valid credential preserves today's success and error behavior, including the list limit and the approval conflict
- `/health` and `/ready` succeed and fail as they do now, with no credential

Projection tests stay as they are: the list and detail fixtures still drop plan addresses, finding messages, workspace paths, and GitHub coordinates.

UI tests: API calls include the credential; health and ready calls do not; a 401 renders the existing error path; storage assertions still forbid workflow persistence.

One container or ASGI test proves the Docker healthcheck target remains anonymous.

No Terraform apply or destroy. No real AWS, OpenAI, Langfuse, or GitHub calls.

## 20. Expected files and modules if implemented

Likely touch points, not an implementation plan:

- a small authenticator next to the API edge, not inside LangGraph
- `src/iac_agent/api/app.py` or `routes.py` to enforce it
- `src/iac_agent/app/config.py` only for a `SecretStr` loader, not a field on `ApplicationConfig`
- `ui/src/api/client.ts` and its tests
- `.env.example`, `docs/api.md`, and `docs/roadmap.md`
- route and composition tests

No change expected in `request_index.py`, checkpoint code, `approval.py`'s decision enum, `schemas.py` success models, Terraform modules, or the Dockerfile `USER`.

## 21. Explicit non-goals

- RBAC, tenants, multi-user directories, and per-request ownership
- storing the principal on the approval, in the checkpoint, or in `request_index`
- choosing Cognito, Auth0, GitHub OAuth, or a workload Lambda authorizer
- publishing the service beyond `127.0.0.1`
- TLS termination, Kubernetes, ECS, or any other orchestrator
- lifespan decoupling from GitHub and OpenAI
- a secrets manager
- changing `/health` or `/ready` so they probe external systems
- CORS
- Terraform apply or destroy
- widening public DTOs
- rate limiting, except whatever a later exposure batch requires
- Langfuse, eval expansion, and new infrastructure resources
- backfill, cursor pagination, or search on the request index

## 22. Risks

A shared secret is one operator. If it leaks, the bearer is the operator until it is rotated. Rotation is an environment change, not a user directory.

Requiring the secret at startup will break current local and Compose flows until the variable is set. That is the point of fail-closed behavior, and it must be documented before implementation.

Putting the check in the wrong place could still allow `GET /api/v1/requests` to build the catalog before rejecting. Tests must show the application methods are not called.

Exempting "loopback" inside the app would miss the real exposure path, because the container already binds `0.0.0.0`.

Anonymous static files still let a remote scanner see that the UI exists if the port is published later. That is accepted. The catalog is not.

Startup still refuses to become ready without GitHub and OpenAI. Operators can mistake that for an authentication failure. The 401 versus 503 split has to stay visible.

## 23. Alternatives rejected

Authentication plus RBAC plus exposure in one batch. Those are three decisions. The repository has one operator and an explicit non-goal trail from Batches 31–33 against public deployment.

Lifespan decoupling as Batch 34. It is the largest documented startup debt, and it is independent. Shipping it first leaves anonymous list and anonymous approval in place, which is the boundary Batch 33 said not to cross.

Treating Compose loopback as the permanent control and writing no code. The publish line is configuration, not an application invariant. The next honest boundary is in the request path.

Using the GitHub token or GitHub OAuth as the operator identity. The token already authorizes repository mutation. The browser must not hold it. GitHub identity is not the operator principal this codebase describes.

OIDC or Cognito now. Nothing in the operator path couples to an identity provider. Bootstrap OIDC is the AWS plan role's trust policy, not the UI.

Persisting `approved_by` in this batch. `approval.py` forbids an unverifiable identity. The principal has to exist first, and writing it is a later audit batch.

Changing `request_index` to store an owner. There is no owner.

Making `/ready` depend on GitHub or OpenAI reachability. That is a different probe design and a known non-goal of the current readiness contract.

## 24. Follow-on batches enabled

After this boundary exists, a later batch can attach the principal to the approval record without inventing a name. Only after anonymous operator calls fail does a batch get to decide whether the port may leave loopback, and that batch still has to take TLS, secret delivery, and single-node SQLite as separate problems. Lifespan decoupling can proceed in parallel whenever it is scheduled; it is not unlocked by authentication and does not unlock it. RBAC waits on a human decision that more than one operator exists.

## 25. Closed decisions

These decisions are closed for Batch 34:

1. Mechanism: one operator secret from the environment, variable `IAC_AGENT_OPERATOR_SECRET`. Bootstrap only. Not OAuth, OIDC, Cognito, Auth0, GitHub login, or JWT issuance.
2. Transport: `Authorization: Bearer`.
3. Browser lifetime: memory only. Reload requires entry again. No cookies and no web storage.
4. Persistence: none. The principal exists only for that HTTP request. Approval actor storage is a later boundary that this batch enables and does not implement.
5. Exposure: Compose stays `127.0.0.1:8000:8000`. Authentication does not authorize public Internet exposure.
6. Lifespan: GitHub and OpenAI startup coupling stays. It is independent debt. This batch does not change it.

No human decision remains inside this batch. A later batch must decide whether more than one operator exists before any role or audit-actor work starts.
