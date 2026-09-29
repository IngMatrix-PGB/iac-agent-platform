# Batch 33 design — durable request index

Status: closed. The decisions in section 29 are approved. This document does not implement them.

## 1. Executive summary

After Batch 32, the operator can review one request only when its `request_id` is already known. Durable workflows live in the SQLite LangGraph checkpoint and survive process replacement. The UI has no server-owned list of those requests.

Batch 33 should add a local, application-owned request index and one read API that lists checkpointed requests. The checkpoint remains the authority for workflow state. The index is only the set of request ids and the order in which they were created. The public list row is projected from the checkpoint at read time. It carries `request_id`, `created_at`, `workflow_status`, `approval_available`, `security_status`, and `name`. Only `request_id` and `created_at` are stored in the index. The API stays unauthenticated and loopback-only. A list makes accidental port exposure more damaging, and this batch does not approve that exposure. Clarification, unsupported, and interpreter-failure results stay non-durable. The list is the newest 20 requests by default, and at most 50. It is not a cursor or an event log.

Authentication, remote deployment, a new resource type, Langfuse, eval expansion, and lifespan decoupling are deferred.

## 2. Current verified architecture

Verified on `origin/main` `5618c2027da15cc5847685589609688e4a31d007`, which is the merge of pull request #15. That commit contains Batch 32 head `c69b0b1a4f5b3f644535058852eea98295c632a2`.

The process is one FastAPI application. `python -m iac_agent.api` uses `create_app`. The lifespan calls `open_intent_application`, which opens one SQLite checkpointer and compiles the LangGraph workflow with Terraform, Checkov, and GitHub source control. `/health` does not prove dependencies. `/ready` is 200 only when that holder exists.

HTTP routes today:

- `POST /api/v1/requests` creates a request.
- `GET /api/v1/requests/{request_id}` reads one checkpoint.
- `POST /api/v1/requests/{request_id}/approval` resumes with `approve` or `reject`.

There is no list route.

`thread_id` is exactly `request_id` (`workflow_config`). `IacApplication.read` uses `get_state`. An unknown thread has `created_at is None` and returns `None`, not a synthetic `pending`.

A resolved architecture calls `IacApplication.submit` and returns HTTP 201 with `Location`. Clarification and unsupported resolutions return HTTP 200 with `workflow: null` and do not call `submit`. Interpreter failures return 502, 503, or 504 and do not call `submit`. The UI says "This result is not saved. Refreshing clears it."

`project_view` rebuilds a public `RequestResponse` from the checkpoint. It does not have the original natural-language text or `ArchitectureIntent`. After reload, `intent` is null and the resolution carries `outcome: resolved` plus the resource `name`.

Public workflow fields stay narrower than checkpoint state. Findings expose `policy_id`, `status`, and `severity` only. Errors expose `stage` and `error_type` only. The pull-request object exposes `url` only. `terraform_apply` is the literal `not_executed`.

The operator UI submits, navigates to `/requests/{request_id}` on 201, and can open an id the operator types. It polls `pending`, `running`, and `approved` every 5 seconds, at most 12 times. It does not use `localStorage`, `sessionStorage`, or `IndexedDB`.

Compose publishes `127.0.0.1:8000:8000`. The container bind `0.0.0.0` is not authentication. The state volume holds `state.db`. Replacement-container acceptance already reconstructs `awaiting_approval` from that volume and resumes it to `pr_created`.

Observability defaults to off. Langfuse is constructed only when explicitly selected, and telemetry passes through sanitization. The production lifespan still requires GitHub and OpenAI configuration before the process serves. `docs/api.md` records that as unchanged technical debt.

Supported end-to-end kinds remain SQS, S3, DynamoDB, Lambda, API Gateway, and ECR, including the existing compositions. Golden datasets exist for those slices.

## 3. Problem statement

A durable request is recoverable only by an id the operator still has. The id is in the URL after submit. If that tab is gone, the checkpoint still exists and the UI cannot discover it. "Open a saved request" asks the operator to supply the id.

That is the operator gap left by Batches 31 and 32. Those batches made one known request reviewable. They did not make the set of durable requests visible.

## 4. Discovery evidence

- `src/iac_agent/api/routes.py` registers create, get-one, and approval only.
- `src/iac_agent/intent/service.py` calls `application.submit` only for `ResolvedArchitecture`.
- `src/iac_agent/persistence/checkpoints.py` documents that `thread_id` is `request_id` and that the serializer allowlist is the checkpoint boundary.
- Installed `SqliteSaver.list` can be called with `config=None`. `search_where` then omits `thread_id` and selects every `checkpoints` row, including the serialized `checkpoint` blob, ordered by `checkpoint_id`. That is a checkpoint history API, not a request-summary API. One request has many checkpoint rows.
- `project_view` cannot recover architecture, intent, or the natural-language request from a checkpoint.
- `ui/src` has no web storage of the request.
- `docs/roadmap.md` still lists authentication, RBAC, tenants, and public deployment as not started.
- `docs/api.md` states that the UI does not make the API safe for public Internet exposure, and that the API does not expose a workflow event history.
- Golden eval files exist under `evals/datasets/` for the supported slices. They do not cover an operator index.
- CI jobs are Quality, Tests, Tool Validation, and Frontend. No deploy job.

## 5. Candidate approaches

### A. Durable request index

Operator value: high. The local operator can return to work that already exists.

Architectural value: high. It separates enumeration from checkpoint payload without making the browser authoritative.

Prerequisite: none inside the current loopback boundary. It uses the existing state file and the existing public projection.

Security: a list is easier to enumerate than a known id. On the current loopback bind that is the same trust as the existing API. It must not add checkpoint internals to the response.

Trust boundary: unchanged if the route stays unauthenticated and local.

Persistence: a new application table. The checkpoint schema stays LangGraph's.

API: one new read route and one new summary item. Existing routes stay.

Workflow: none.

Migration: requests created before the table exist only as checkpoints. They stay reachable by id. They are absent from the list unless a later batch backfills them.

Testability: high. Reopen the same SQLite file in a second process-equivalent application and list the row. No cloud calls.

Size: one vertical slice across persistence, API, projection, and the compose page.

Reversibility: the table can be ignored and the route removed. Checkpoints do not depend on it.

Unlocks: a local operator home for in-progress and finished reviews. It does not unlock public deployment.

Now: yes. This is the recommended slice.

### B. Authentication and authorization

Operator value: low while one person uses loopback. It adds login before there is a second principal or a public route.

Architectural value: necessary before any non-loopback exposure. Not necessary to list local requests.

Threat model today: anyone who can open the published port is the operator. Compose publishes loopback only.

Authentication alone does not decide who may approve. Authorization would have to name that principal, and the approval record would have to store it. The checkpoint and public DTO have no actor.

Cookie sessions would add CSRF on the approval POST. Bearer tokens would add a browser secret and a configuration lifecycle. Neither is justified by a local single-operator UI.

An identity provider is not selected by this repository. Cognito, Auth0, and generic OIDC are not implied by the code.

Doing this now would change the trust boundary without an exposure decision. Deferred.

### C. Remote runtime

ECS, EKS, or another remote runtime needs an exposure decision, authentication, secret delivery, a persistent volume story, workspace filesystem rules, the provider mirror, GitHub credentials, and health semantics that still do not probe AWS or GitHub. The current `/ready` means the holder opened, not that those systems are reachable.

This depends on B and on an explicit deployment decision. It does not fix the lost-id gap. Deferred.

### D. Observability

Langfuse is already an optional, fail-open sink and defaults to off. Sanitization strips a fixed set of secret-shaped strings. The operator approves from the public DTO, not from traces. Enabling a cloud project would be a new external dependency and a new sensitive-data review. It does not list requests. Deferred.

### E. Evaluation and quality

Golden sets already exist for the supported resource and composition slices. A quality batch would deepen regression coverage. It would not give the operator a way to find a request. It is not the next platform slice. Deferred as ongoing work, not as Batch 33.

### F. Another resource type

EventBridge, SNS, a second Lambda, and composition chaining are larger than another copy of the current resource pattern. More kinds would not make unknown request ids recoverable. Deferred.

### G. Startup and lifespan

`docs/api.md` is accurate: the process refuses to serve until GitHub and OpenAI settings exist, even when a request would not call them. That blocks casual local startup. It does not block an operator who already has the placeholder or real settings used today. Docker acceptance depends on that eager startup. Changing it is real debt, and it is not required before an index. Deferred, and it does not block Batch 33.

### H. Use `SqliteSaver.list` as the index

Rejected as the product mechanism. `list(None)` returns full checkpoint blobs for every thread, ordered by checkpoint id rather than by request. The blob is internal state: resource specs, plan detail, Checkov data, and error objects. Building a public list by deserializing those rows couples the API to LangGraph's table layout and would be easy to over-expose. The saver remains the checkpoint store. It is not the request catalog.

## 6. Recommended Batch 33 slice

Add an application-owned durable request index and `GET /api/v1/requests` for checkpointed requests only. Show that list on the existing compose page. Keep the typed request-id opener. Do not change approval, polling, workflow nodes, or the public shape of `GET /api/v1/requests/{request_id}`.

## 7. Why now

Batches 31 and 32 finished the single-request review surface. The next operator action that the server can already support, and the UI cannot, is finding a request whose checkpoint exists. The data is on the state volume. The missing piece is a catalog that does not become a second workflow authority.

## 8. Why the other candidates are deferred

Authentication and remote deployment change who may call the API and where it runs. The repository has not approved that exposure. Observability, evals, and another resource type improve other axes and leave the lost-id gap in place. Lifespan decoupling is documented debt with a smaller operator payoff than a list, and it is entangled with Docker startup. None of those slices is a prerequisite for a loopback index.

## 9. Scope

- An application-owned table in the existing `state.db`.
- A row written after a checkpointed submit succeeds.
- `GET /api/v1/requests` returning the newest `limit` rows, default 20 and maximum 50, with no cursor.
- Each item projected by reading that request's checkpoint through the existing application read and the existing public field set.
- Compose-page list with links to the existing request route.
- Tests for ordering, the limit cap, omission of non-durable outcomes, a stale index row, reopen of the same database file, and the public field boundary.

## 10. Non-goals

- Authentication, RBAC, tenants, or an identity provider.
- Public Internet exposure, ECS, EKS, or any other remote runtime.
- Changing bind address or Compose port publication.
- `terraform apply` or `terraform destroy`.
- New workflow statuses, nodes, or polling rules.
- Persisting clarification, unsupported results, or interpreter failures.
- Backfilling checkpoints that exist before the index.
- Storing natural-language text, intent, architecture, plan JSON, Terraform source, finding resource or message, workflow error messages, GitHub coordinates, or checkpoint blobs in the index or the list response.
- Browser durable storage.
- Offset or cursor pagination. Callers receive the newest page only.
- Enabling Langfuse or adding a trace UI.
- A workflow event log. The list is current requests, not checkpoint history.
- Lifespan refactor.
- A new resource type.
- Making the index authoritative for approve or reject.

## 11. Architecture

```text
POST /api/v1/requests
        |
        +-- clarification / unsupported / interpreter error
        |         |
        |         +-- no checkpoint, no index row
        |
        +-- resolved architecture
                  |
                  v
            LangGraph checkpoint (authority)
                  |
                  v
            request_index row (id, created_at)
                  |
GET /api/v1/requests
        |
        v
   page of ids from request_index
        |
        v
   application.read(id) per id
        |
        v
   public summary projected from that view
```

The compose page fetches the list and links each id to `/requests/{request_id}`. That page still loads `GET /api/v1/requests/{request_id}`.

## 12. Data ownership / source of truth

The LangGraph checkpoint remains the source of truth for workflow status, stage, plan counts, findings, approval, errors, and the pull-request URL.

`request_index` owns only:

- `request_id` text, primary key, the same validated id the checkpoint uses.
- `created_at` text, generated on the server when the row is inserted. It is UTC in the form `YYYY-MM-DDTHH:MM:SS.ffffffZ`, with six fractional digits, so lexical order matches time order. It does not come from the browser, the filesystem, or a checkpoint blob.

It does not own status. A list response reads status from the checkpoint at request time. If a row exists and `read` returns `None`, that item is omitted from the page. The response does not invent `pending`.

Clarification and unsupported results have no checkpoint and no index row. They remain session-local in the browser until refresh.

## 13. API impact

New route: `GET /api/v1/requests`.

Query parameter `limit` is an integer. Omitted means 20. A present value must be from 1 through 50. Zero, negative, above 50, and non-integer values are rejected by FastAPI/Pydantic with HTTP 422. They are not clamped and they are not rewritten into the existing `invalid_request` 400 body.

There is no cursor and no offset. The response is the newest matching rows, at most `limit`. Rows older than that page are not returned. They remain reachable by id. Full pagination is deferred.

`GET /api/v1/requests` and `GET /api/v1/requests/{request_id}` are different path shapes. The collection route is registered as its own route. `requests` is not a request id. The UI catch-all already treats `api/` as backend and must not serve `index.html` for this path.

Success HTTP 200:

```json
{
  "requests": [
    {
      "request_id": "req-20260929T000000Z-abcdef012345",
      "created_at": "2026-09-29T00:00:00.000000Z",
      "workflow_status": "awaiting_approval",
      "approval_available": true,
      "security_status": "pass",
      "name": "orders"
    }
  ]
}
```

`requests` is ordered by `created_at` descending, then `request_id` descending. An empty catalog is 200 with `requests: []`.

`created_at` is the index timestamp. `workflow_status` is the checkpoint enum string. `approval_available` is true only when that status is `awaiting_approval`, matching `project_view`. `security_status` is the checkpoint string, or JSON null when the checkpoint has no security gate. `name` is `resource_name` from the checkpoint view, or JSON null when that view has no resource name. None of those four dynamic fields is stored on `request_index`.

`POST /api/v1/requests`, `GET /api/v1/requests/{request_id}`, and `POST /api/v1/requests/{request_id}/approval` keep their current status codes and bodies.

No `DELETE`. No update route. The list is not a workflow command.

## 14. Public DTO impact

Add a list document and a summary item. Do not add fields to `RequestResponse`.

The summary item has exactly `request_id`, `created_at`, `workflow_status`, `approval_available`, `security_status`, and `name`. `security_status` and `name` are nullable. The other four are always present on a row that is returned.

It does not include outcome captions, intent, resolution detail, plan counts, findings, errors, pull-request URLs, `terraform_apply`, or GitHub coordinates. Those remain on the single-request read when they are already public there. The list stays smaller than that read so a catalog response is not a bundle of every review.

Server enums stay raw. The UI may caption them beside the raw value, as Batch 32 does, without removing the raw value.

## 15. Workflow impact

None. Submit, interrupt, approve, reject, and publish behave as they do now. The index write happens inside `IacApplication.submit` after `graph.invoke` has returned and the view has been built. That is the first point at which this process knows a checkpointed request exists. `IntentResolutionService.submit` calls `application.submit` only for `ResolvedArchitecture`. Clarification, unsupported, and interpreter failures never reach it. `resume` does not insert a second catalog concept; a repeated insert for the same id is an idempotent no-op. A failed index write does not roll back the checkpoint and does not change the 201 body. The request remains available at its id. It is missing from the list until a later, separately approved repair exists. This batch does not add that repair.

Approval still reads the checkpoint. It does not consult the index.

## 16. Persistence impact

Create table `request_index` in the same SQLite file the checkpointer already opens (`IAC_AGENT_STATE_DB`, default under the state directory, `/var/lib/iac-agent/state/state.db` in the container). The named volume therefore keeps the index across container replacement.

The application creates the table if it is absent. It does not alter LangGraph's `checkpoints` or writes tables. It does not call `SqliteSaver.list` to serve the route.

Insert is idempotent on `request_id`. A duplicate id is already rejected with `request_exists` before submit, so a second insert for the same id is a defensive no-op, not a second workflow.

No second database file. No migration of old rows.

## 17. UI impact

The compose page gains a "Recent requests" section that loads `GET /api/v1/requests` with the default limit. It does not add search, filter, sort controls, or infinite scroll.

Each row shows the request id, the name when present, the raw `workflow_status`, and the raw `security_status` when present. The row links to `/requests/{request_id}`. `approval_available` may be shown as the existing "Approval available" / "Approval not available" sentences. It must not be the only signal. A null `security_status` or `name` is omitted, not replaced with an invented enum.

Keep the typed id form. Absence from Recent requests does not mean the checkpoint is gone. Empty-state copy says no indexed requests exist and that an older id can still be opened directly.

Do not store the list in browser storage. Do not poll the list. Opening a row uses the existing request page, including its existing poll rules.

No change to the approval dialog, plan summary, or findings table.

## 18. Security / trust-boundary analysis

The route is unauthenticated because every current route is unauthenticated. This batch does not approve binding the API beyond loopback or publishing it past `127.0.0.1`.

Enumeration risk: a caller who can reach the port can list ids and statuses instead of guessing ids. That is acceptable only while the port remains the local operator port. A later exposure decision must treat this route as authenticated surface area. This batch must not be cited as that decision.

Disclosure rules for the list:

- no natural-language request
- no Terraform source
- no raw plan JSON
- no resource addresses
- no `finding.resource` or `finding.message`
- no `WorkflowError.message`
- no AWS account id or ARN
- no workspace path
- no checkpoint payload
- no GitHub owner, repository, branch, or base branch
- no tokens

`name` is already public on the single-request DTO. It is a resource name the operator chose, not an account identifier.

The index table stores the id and timestamp only, so a stolen `state.db` gains no new secret from this table. The checkpoint tables remain as sensitive as they are today. This batch does not claim to encrypt them.

No `VITE_` secret. The browser calls the same-origin API.

## 19. Failure semantics

- Invalid `limit`: HTTP 422 from request validation. No partial list and no clamping.
- Empty index: 200 and an empty array.
- Index row whose `read` returns `None`: omit that id. Do not synthesize `pending` or any other status. The list may then be shorter than `limit` even if older index rows exist. This batch does not look past the newest `limit` rows to fill the gap.
- Index insert fails after a successful checkpoint: log `error_type` and `request_id` through the existing `logging` warning style. Do not log checkpoint payloads. Do not retry. The create response stays the current 201 body. The list can omit that id. The single-request route still works.
- Interpreter, clarification, and unsupported results: unchanged HTTP behavior, no index row.
- Approval 409: unchanged. The list is not involved.

## 20. Concurrency considerations

The supported runtime is one local process and one operator. SQLite serializes writers. Primary key on `request_id` prevents two index rows for one id.

A create that commits before the next list query appears in that query when it is among the newest `limit` rows. There is no cursor to keep stable.

The list reads checkpoints one by one for those rows. The cap of 50 bounds that work. The route does not scan checkpoint blobs to discover ids.

No new lock around approve. Approve and list can interleave. The list shows whatever `read` returns at that moment.

## 21. Migration / compatibility

Existing checkpoints are not inserted into `request_index`. Deep links and typed ids keep working. The list starts with requests created after the table exists.

Clients that do not call the new route are unchanged. The single-request JSON shape is unchanged.

A replacement container that mounts the same volume sees both old checkpoints and any index rows written before replacement.

## 22. Testing strategy

Deterministic tests, no cloud:

- A checkpointed submit inserts one index row. A second read of the list returns that id and the checkpoint's `workflow_status`.
- Clarification and unsupported submits create no row.
- Order is `created_at` descending, then `request_id` descending.
- `limit` of 0, a negative number, a value above 50, and a non-integer return 422.
- A summary item has only the six public fields. A fixture that contains an ARN, a finding message, a plan address, Terraform source, a workspace path, a checkpoint marker, GitHub coordinates, and a workflow error message does not appear in the list body.
- Close the application, open a new one on the same database path, and the row is still listed. `GET` by id still returns the checkpoint status.
- UI test: the compose page renders a row from the list client and the link target is the request route. The typed opener still navigates. No web storage calls.
- Existing approval, polling, projection, and 409 tests stay as they are.

Docker replacement and real-tool tests are not required to prove the table if the deterministic reopen test uses the same file. Do not add a cloud call.

## 23. Acceptance criteria

- An operator can open the compose page and see checkpointed requests without typing an id.
- Choosing one opens the existing review page.
- The status on the list matches a concurrent `GET` of that id.
- Non-durable outcomes do not appear after refresh.
- Pre-existing checkpoints remain readable by id and are not required to appear in the list.
- Approval still confirms before POST. Reject still sends immediately. HTTP 409 behavior is unchanged.
- The list JSON cannot carry the hidden fields listed in the security section.
- Loopback publication and the absence of authentication are unchanged.

## 24. Risks

- Operators may think a missing list means the checkpoint is gone. The typed opener and empty-state copy have to say that older ids still open directly.
- A failed index insert creates a silent catalog gap. The 201 response still contains the id. A repair job is out of scope; the gap must be tested and documented rather than hidden by scanning checkpoint blobs.
- `SqliteSaver.list(None)` will remain available to application code. Implementation must not use it for this route. A test can assert the route's SQL or repository calls the index table, not the checkpoints table, for enumeration.
- Listing increases the value of an accidentally published port. The batch does not widen the port, and it must not be described as safe for public deployment.

## 25. Deferred work

- Backfill of pre-index checkpoints.
- Durable storage for clarification and unsupported results.
- Repair of index rows whose insert failed.
- Authentication and approval identity.
- Remote runtime.
- Lifespan decoupling from GitHub and OpenAI configuration.
- Langfuse enablement.
- Eval expansion and new resource types.
- Showing plan counts, findings, or pull-request URLs on the list row.
- Cursor or offset pagination.

## 26. Expected files and components affected

Implementation is not part of this design. A later plan would likely touch:

- `src/iac_agent/persistence/` for the index table beside the checkpointer factory.
- `src/iac_agent/app/service.py` or the intent submit path for the insert.
- `src/iac_agent/api/routes.py`, `schemas.py`, and `project.py` for the list route and summary projection.
- `docs/api.md` and `docs/roadmap.md`.
- `ui/src/api/client.ts`, `ui/src/api/types.ts`, and `ui/src/pages/compose-page.tsx`, plus tests.
- New unit tests under `tests/unit/`.

It would not need `src/iac_agent/graph/workflow.py`, Terraform modules, the Dockerfile, `compose.yaml`, or CI unless a later review finds the table is not created on the existing connection.

## 27. Explicit invariants

1. No `terraform apply`.
2. No `terraform destroy`.
3. Human approval still gates publication.
4. Workflow state stays in the server checkpoint.
5. The browser is not the workflow authority.
6. `RequestResponse` stays narrower than internal state.
7. Raw plan JSON stays off the public API.
8. Raw Checkov output stays off the public API.
9. Finding resource and message stay off the public API.
10. Workflow exception messages stay off the public API.
11. Checkpoint internals stay off the public API.
12. GitHub credentials stay off the browser.
13. Secrets stay out of images and frontend bundles.
14. Existing resource behavior does not change.
15. Offline Terraform behavior does not change.
16. Replacement-container HITL durability does not change.
17. No public exposure decision is implied.
18. The UI invents no workflow transition.
19. The checkpoint, not the index, answers approve, reject, and `GET` by id.
20. `thread_id` remains `request_id`.

## 28. Resolved questions

1. `security_status` is on the public list row. It is read from the checkpoint projection. It is not a column on `request_index`.
2. The default limit is 20 and the maximum is 50. Invalid values are HTTP 422 and are not clamped.
3. Checkpoints created before the index are not backfilled. They stay off Recent requests and remain readable by id.
4. A stale index row whose checkpoint cannot be read is omitted. No status is invented. The implementation plan does not need another decision on this point.
5. Batch 33 does not promise pages beyond the newest `limit` rows.

No architectural decision that would change the implementation contract remains open.

## 29. Approved decisions

1. Batch 33 is the local durable request index. It is not authentication, remote deployment, Langfuse, eval expansion, a new resource, or lifespan work.
2. The trust boundary stays unauthenticated and loopback-published. Enumeration increases disclosure if that port is exposed. This batch is not that exposure approval.
3. `request_index` stores only `request_id` and `created_at`. Workflow fields are not copied into it.
4. The public row is `request_id`, `created_at`, `workflow_status`, `approval_available`, `security_status`, and `name`, projected from the checkpoint. `RequestResponse` does not grow.
5. Enumeration uses the application table, not `SqliteSaver.list`.
6. Only `IacApplication.submit` after a successful invoke indexes a request. Clarification, unsupported, and interpreter failures stay non-durable.
7. Existing checkpoints are not backfilled.
8. A failed index insert does not roll back the checkpoint, does not change the 201 body, and is not retried.
9. The same `request_id` cannot occupy two catalog rows. A repeat insert keeps the first `created_at`.
10. `created_at` is a server UTC timestamp in `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
11. The compose page shows Recent requests, keeps the typed id opener, and adds no browser storage.
12. The list is the newest `limit` index rows only. Full pagination is deferred.
