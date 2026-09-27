# FastAPI application API (Batch 29)

Design and discovery only. No production code, no dependency install,
no server, and no credentials are part of this document.

Baseline: `origin/main` at `179e4ecf8f89d1953086aba17e1b6f95a76b18c7`
(`Merge pull request #11 from IngMatrix-PGB/feat/batch28-llm-observability`).
The merge parents are `04513d3` and `de45c74`. This branch is
`docs/batch29-fastapi-application-api-design`, created from that merge
commit. `de45c74` is an ancestor of `origin/main`.

Section 11 is closed. Those seven decisions were checked against
`IntentResolutionService`, `IacApplication.get_state`, `WorkflowError`,
`SecurityFinding`, and `PullRequestResult` on this merge commit. The
empty-snapshot `pending` projection in `get_state` is the only gap, and
section 6 keeps it off the HTTP path.

The HTTP API is an adapter over the existing application boundary. It
is not a second workflow engine.

## 1. Current path

```
CLI argparse
    → IntentResolutionService.submit
        → IntentInterpreterPort.interpret
        → ArchitectureResolver.resolve
        → IacApplication.submit          only for ResolvedArchitecture
    → IacApplication.get_state           resume command, before any decision
    → IacApplication.resume              only when status is awaiting_approval
```

`iac_agent.cli.main` is the only production caller of those three
service methods. It does not construct a LangGraph `Command`, and it
does not call Terraform, Checkov, OpenAI, GitHub, or SQLite itself.
`open_intent_application` owns that wiring.

`IntentResolutionService` (`src/iac_agent/intent/service.py`) stops
before the graph for `ClarificationRequired`, `UnsupportedArchitecture`,
and every `IntentInterpreterError`. Only `ResolvedArchitecture` reaches
`IacApplication.submit`.

`IacApplication` (`src/iac_agent/app/service.py`) holds a compiled
graph and returns `WorkflowView`. Its own docstring already names a
future FastAPI layer as a caller of this boundary. `get_state` reads
the checkpoint and does not execute a node. `resume` is the only method
that supplies `Command(resume=decision.value)`.

The compiled graph is:

`START → render_terraform → terraform_execute → plan_analysis →
platform_policy → checkov_scan → security_gate → approval_gate →
source_control → END`

`security_gate` routes `BLOCK` and `ERROR` to `END`. Only
`AWAITING_APPROVAL` reaches `interrupt()`. Only `APPROVED` reaches
`source_control`. `source_control` refuses to publish unless status is
already `APPROVED`, and it does not call GitHub again when
`pull_request` is already set.

`workflow_config` sets LangGraph `thread_id` to the exact `request_id`
after `validate_request_id`. There is no second workflow identity.

`WorkflowStatus` values that exist today:

| Status | Meaning |
|---|---|
| `pending`, `running` | Declared. A synchronous `submit` does not leave a checkpoint in these states for a caller to read afterward. |
| `awaiting_approval` | Pass or warn, durable interrupt. |
| `approved` | Intermediate, inside the same `resume` invocation that then publishes. |
| `rejected` | Human reject. No publish. |
| `blocked` | Security gate block. No interrupt. |
| `error` | A stage failed. `WorkflowError` stores stage, exception type name, and `str(exc)[:500]`. |
| `pr_created` | Publication succeeded. |

`WorkflowView` already hides the workspace path, raw plan JSON, raw
Checkov payload, tokens, and SQLite handles. It still carries facts
that must not be copied verbatim onto the wire: `plan_summary` includes
Terraform addresses, `security_gate` findings include `resource` and
`message`, `error.message` can be subprocess text, and `resource_name`
is a single name rather than the composition's component names.

Rendered Terraform lives on checkpoint state as `generated_files` and
on disk under the workspace directory. `WorkflowView` does not include
it. The CLI does not print it.

Clarification and unsupported results are not checkpointed. After the
process that handled `propose` exits, nothing in SQLite can
reconstruct them. Fresh-process recovery is proven only for graph
checkpoints: integration tests close the saver, open a new saver on the
same database file, and `get_state` returns the interrupted values.

A missing thread is not a stored `pending` request. LangGraph
`Pregel.get_state` returns `StateSnapshot(values={}, next=(),
created_at=None, interrupts=())` when `checkpointer.get_tuple` finds
nothing (`langgraph.pregel._prepare_state_snapshot`). Today's
`IacApplication.get_state` would still project that empty snapshot as
`workflow_status=pending`. The HTTP adapter must not present that as a
request.

`generate_request_id` in `src/iac_agent/cli/ids.py` produces
`req-%Y%m%dT%H%M%SZ-` plus 12 lowercase hex digits. Its docstring says
generation is CLI-owned and application APIs require an explicit id.
`IacApplication` must continue to require an explicit id. The HTTP
adapter may call the same generator when the client omits one. That is
the same identity, not a second one.

Platform policy and Checkov remain the security gate. Langfuse is
optional, fail-open, and off unless `IAC_AGENT_OBSERVABILITY=langfuse`.
It is not consulted for authorization. Human approval remains mandatory
for pass and warn, and it cannot override a block.

No authentication principal exists. `ApprovalDecision` is only
`approve` or `reject`.

`pyproject.toml` already depends on `pydantic>=2.6,<3`. FastAPI is not
installed. CI installs `.[dev]` and `.[dev,openai]`. It does not need a
workflow-file edit for a package added to the `dev` extra.

## 2. Adapter boundary

```
HTTP route
    → request and response models
    → IntentResolutionService / IacApplication
    → existing graph, tools, and SQLite checkpointer
```

Route modules may call:

- `generate_request_id`
- `validate_request_id`
- `parse_approval_decision`
- `IntentResolutionService.submit`
- `IacApplication` read and `resume`

Route modules must not import or call graph nodes, `TerraformRunner`,
`CheckovAdapter`, the OpenAI adapter, `GitHubSourceControl`,
`sqlite3`, or `open_sqlite_checkpointer`. They must not read
`WorkflowState`, `generated_files`, or checkpoint tuples.

Composition stays in `open_intent_application`. The ASGI lifespan opens
that context once for the process and closes it on shutdown. Tests
pass an already-built `IntentApplication`, the same injection CLI
`main(..., holder=)` uses. The API must not call
`IacApplication.from_application`, because that drops the shared
observability port.

One process holds one checkpointer for one `state_db_path`. Status and
approval are read from that database on every request. The process
must not cache `WorkflowView` or approval results in a dict.

A second process that opens the same database file must observe the
same checkpoint. Tests have to close the app, open a new app on the
same file, and `GET` the same `request_id`.

## 3. v1 routes

| Method and path | Role |
|---|---|
| `POST /api/v1/requests` | Interpret, resolve, and submit when resolved. Synchronous, same as `iac-agent propose` without the interactive prompt. |
| `GET /api/v1/requests/{request_id}` | Read the durable checkpoint. No node execution. |
| `POST /api/v1/requests/{request_id}/approval` | Resume only when the checkpoint is `awaiting_approval`. |
| `GET /health` | Process is serving. No dependency calls. |
| `GET /ready` | The lifespan holder is open. No Terraform, OpenAI, Langfuse, or GitHub probe. |

No list endpoint, no delete, no Terraform endpoint, no apply endpoint,
no auth endpoint, and no webhook.

`GET /health` returns `200` `{"status": "ok"}`. `GET /ready` returns
`200` `{"status": "ready"}` when the holder is open, and `503`
`{"status": "not_ready"}` otherwise. Neither body contains a path, a
database filename, or a configuration value.

Startup configuration errors (`MissingConfigurationError`, including an
explicit `langfuse` mode without keys) fail the process the way the CLI
returns exit 1. They are not per-request workflow results.

## 4. Identity

`request_id` is the only workflow identity. It is the checkpoint
`thread_id`, the workspace directory name, and the git branch suffix
`iac-agent/<request_id>`.

`POST` accepts an optional `request_id`. When it is absent, the route
calls `generate_request_id`. When it is present, the route calls
`validate_request_id` before any service call. Invalid ids, including
empty strings, absolute paths, separators, and `..`, are HTTP 400.
They never reach the checkpointer or the workspace resolver.

A supplied id that already has a checkpoint is HTTP 409. The route
does not call `submit` again. Clarification and unsupported outcomes
do not write a checkpoint, so repeating that same id is a new `POST`,
not a 409.

## 5. HTTP representation

Successful bodies use one JSON object. `outcome` is the discriminator.

Fields that are not applicable are JSON `null`. The body always
includes `terraform_apply: "not_executed"`.

### 5.1 Resolved workflow

Used for `awaiting_approval`, `approved`, `rejected`, `blocked`,
`error`, and `pr_created`.

```json
{
  "request_id": "req-20260927T191300Z-a1b2c3d4e5f6",
  "outcome": "awaiting_approval",
  "approval_available": true,
  "terraform_apply": "not_executed",
  "intent": {
    "workload_type": "storage",
    "interaction_pattern": "unspecified",
    "capabilities": ["object_storage"]
  },
  "resolution": {
    "outcome": "resolved",
    "matched_pattern": "storage+object_storage",
    "architecture": "s3",
    "name": "order-events",
    "components": []
  },
  "workflow": {
    "workflow_status": "awaiting_approval",
    "current_stage": "approval",
    "security_status": "pass",
    "plan": {
      "add": 1,
      "change": 0,
      "destroy": 0,
      "destructive_change_detected": false
    },
    "findings": [
      {
        "policy_id": "platform.example",
        "status": "pass",
        "severity": "high"
      }
    ],
    "approval_decision": null,
    "error": null,
    "pull_request": null
  }
}
```

`approval_available` is true only when `workflow_status` is
`awaiting_approval`.

`intent` on `GET` and on the approval response is null. The checkpoint
does not store `ArchitectureIntent`. Only the `POST` response that just
ran interpretation includes `intent`. `GET` still includes `resolution`
derived from the checkpointed `resource_spec`: architecture label and
component names. It does not include `matched_pattern`, because that
string is not in the checkpoint. `matched_pattern` is present only on
the original `POST` body.

`architecture` uses the same labels the CLI already prints (`sqs`,
`s3`, `dynamodb`, `lambda`, `api_gateway`, `ecr`, `serverless_worker`,
`api_lambda`, and `API Gateway + Lambda + DynamoDB`). `name` is
`spec.name`, the same value as the CLI `name:` line. `components`
follows the CLI component lines (`queue`, `function`, `table`, `api`,
`route`, and for ECR `repository` plus `image_tag_mutability` and
`scan_on_push`). Standalone resources other than ECR have an empty
`components` array. A parity test locks that agreement. Names are
included because the operator is approving the resources that will be
proposed. This is wider than the Langfuse allowlist on purpose.
Langfuse still receives neither names nor this HTTP body.

`plan` is counts plus `destructive_change_detected`. Addresses,
`changed_fields`, and raw plan JSON are omitted.

`findings` are only `policy_id`, `status`, and `severity`.
`finding.resource`, `finding.message`, `source`, raw Checkov JSON, and
scanner-derived addresses or account identifiers are omitted. Pass
findings are included so the UI can show a complete gate result; the
CLI hides passes, and that display choice stays in the CLI.

`error` is `{"stage": "<workflow stage>", "error_type": "<type name>"}`
or null. `WorkflowError.message` is omitted because it is
`str(exc)[:500]` and can carry Terraform stderr. The CLI may keep
printing that message. The public API does not.

`pull_request` is null except for `pr_created`, where the only field is
`url`. Branch, base branch, owner, repository, and token are not
separate HTTP fields. `PullRequestResult` still stores branch and base
branch for the CLI.

`approved` is represented if a read ever observes it. A normal
`resume(approve)` continues into `source_control` before it returns, so
the synchronous approval response is `pr_created` or `error`, not a
resting `approved`.

### 5.2 Clarification and unsupported

No `workflow` object. `approval_available` is false.

```json
{
  "request_id": "req-20260927T191300Z-a1b2c3d4e5f6",
  "outcome": "clarification_required",
  "approval_available": false,
  "terraform_apply": "not_executed",
  "intent": {
    "workload_type": "unspecified",
    "interaction_pattern": "unspecified",
    "capabilities": []
  },
  "resolution": {
    "outcome": "clarification_required",
    "field": "workload_type",
    "reason": "workload_type_required",
    "allowed_values": ["api", "worker", "storage"]
  },
  "workflow": null
}
```

Unsupported:

```json
{
  "outcome": "unsupported",
  "resolution": {
    "outcome": "unsupported",
    "reason": "unsupported_capability",
    "detail": "<resolver-authored detail>"
  },
  "workflow": null
}
```

`detail` is the existing resolver string. It is not an exception
message. The body omits `assumptions`, `unresolved_questions`,
`logical_name_hint`, `confidence`, and the natural-language request.

These two outcomes are not written to SQLite. See decision 1.

### 5.3 Interpreter failure

Not a workflow body. The message is the stable CLI sentence for that
exception type, never `str(exc)`.

```json
{
  "request_id": "req-20260927T191300Z-a1b2c3d4e5f6",
  "error": "intent_provider_unavailable",
  "message": "Intent provider unavailable."
}
```

Codes match `iac_agent.cli.present`:

| Exception | `error` | HTTP status |
|---|---|---|
| `IntentProviderUnavailableError` | `intent_provider_unavailable` | 503 |
| `IntentProviderTimeoutError` | `intent_provider_timeout` | 504 |
| `IntentProviderRefusalError` | `intent_provider_refusal` | 502 |
| `IntentValidationError` | `intent_payload_malformed` | 502 |
| `IntentSchemaVersionUnsupportedError` | `intent_schema_unsupported` | 502 |
| any other `IntentInterpreterError` | `intent_interpretation_failed` | 502 |

### 5.4 What must not cross HTTP

- raw natural-language prompt and raw model output
- `assumptions`, `unresolved_questions`, `logical_name_hint`, `confidence`
- Terraform source and `generated_files`
- raw plan JSON, resource addresses, ARNs, account IDs
- raw Checkov JSON, `finding.resource`, `finding.message`, finding `source`
- GitHub owner, repository, branch, and base branch as separate fields
- `WorkflowError.message`, stack traces, subprocess stdout and stderr
- checkpoint bytes, serializer payloads, workspace paths, database paths
- environment values, tokens, `SecretStr` contents
- Langfuse trace ids and telemetry payloads
- the interrupt payload from `approval_gate` (`resource` plus finding
  `resource` are in that payload today; the HTTP projector must not
  return it)

## 6. Status codes

### `POST /api/v1/requests`

| Condition | Status |
|---|---|
| Body is not the documented object, or `natural_language_request` is missing or empty | 400 `invalid_request` |
| `request_id` fails `validate_request_id` | 400 `invalid_request_id` |
| `request_id` already has a checkpoint | 409 `request_exists` |
| Clarification or unsupported | 200 and the section 5.2 body |
| Checkpoint written (`awaiting_approval`, `blocked`, `error`, or a theoretical early terminal) | 201, `Location: /api/v1/requests/{request_id}`, section 5.1 body |
| Interpreter failure | section 5.3 |
| Unexpected exception after the id is valid | 500 `internal_error`. Body is `{"error": "internal_error", "message": "Internal error."}`. The handler does not copy the exception text. |

### `GET /api/v1/requests/{request_id}`

| Condition | Status |
|---|---|
| Id fails validation | 400 `invalid_request_id` |
| No checkpoint (`created_at is None` and empty values) | 404 `request_not_found` |
| Checkpoint exists | 200 section 5.1 body, with `intent` null and `matched_pattern` null |

Repeated `GET` is a pure read.

### `POST /api/v1/requests/{request_id}/approval`

Body is `{"decision": "approve"}` or `{"decision": "reject"}`.
`parse_approval_decision` rejects every other value. Invalid JSON or
any other decision is 400 `invalid_approval`.

| Checkpoint state | Result |
|---|---|
| Missing | 404 `request_not_found` |
| `awaiting_approval` | Call `resume` once. 200 with the resulting section 5.1 body. |
| `pr_created` or `approved`, stored decision `approve`, new decision `approve` | 200 current body. Do not call `resume`. |
| `rejected`, stored decision `reject`, new decision `reject` | 200 current body. Do not call `resume`. |
| `error`, `blocked`, the opposite decision, or any other status | 409 `approval_conflict`. Do not call `resume`. |

A 409 body is `{"error": "approval_conflict", "message": "This request cannot accept that decision.", "request": <section 5.1 body>}`. The HTTP status is not success. `ERROR` is never treated as an already-applied approval, even when `approval_decision` is set, because a failed publish is not a successful approve. v1 has no retry route for that error.

Repeated `GET` of an id that `validate_request_id` accepts and that has no checkpoint returns 404. The body is `{"error": "request_not_found", "message": "Request not found."}`. It must not contain `workflow_status`, `pending`, `submitted`, or `awaiting_approval`.

`IacApplication.get_state` today projects an empty snapshot as `pending`, because `_to_view` defaults a missing `workflow_status`. HTTP must not call `get_state` to decide existence. It calls a new `IacApplication.read` that returns `None` when `snapshot.created_at is None`. The CLI keeps `get_state`.

Two overlapping approvals can both observe `awaiting_approval` before either `resume` returns. SQLite serializes the writers. The loser re-reads with `read`. If that read now proves the same decision already applied, respond 200. If it proves a conflict, respond 409. Do not call `resume` a second time.

## 7. Rendered Terraform

v1 does not return HCL and does not add
`GET /api/v1/requests/{request_id}/terraform`.

The files already go to the pull request after approval. Reading
`generated_files` or the workspace would be a new internal-state
export. A later batch can add that endpoint only with an explicit
authorization decision. This batch does not reserve a hidden query
flag that turns it on.

## 8. Security and observability

Routes do not call `evaluate_security_gate`, Checkov, or platform
policy functions. Those run inside the existing graph during `submit`.
A block remains terminal. Approval cannot unblock it, because
`resume` is refused unless status is `awaiting_approval`.

Langfuse stays behind `FailOpenObservability` inside the services the
routes already call. A telemetry failure does not change the HTTP
status that the service result maps to. The API does not read Langfuse
to decide readiness, authorization, or workflow status.

No auth middleware is added. There is no OAuth, OIDC, Cognito, JWT,
API key, session, or RBAC in this batch. The unauthenticated server is
a local development boundary. It is not production-ready for public or
network exposure. The serve helper binds `127.0.0.1` only. Docker is a
later batch and must choose its own bind and network policy. It must
not inherit loopback as if that were a deployment design. This batch
does not invent `approved_by`.

## 9. Dependencies and modules

Pydantic stays the existing base dependency. Add these to the `dev`
extra so the current CI install lines pick them up without a workflow
edit:

- `fastapi>=0.115,<1`
- `httpx>=0.27,<1` for `TestClient`
- `uvicorn>=0.32,<1` so the process can be served

Do not add them to the base `dependencies` list. A bare install must
still import `iac_agent.app`, `iac_agent.intent`, `iac_agent.graph`, and
`iac_agent.cli`. `iac_agent/__init__.py` must not import the API
package. The API package may import FastAPI at module import. Because
the `dev` extra installs FastAPI, CI cannot assert that the
distribution is absent. Isolation is an AST check: `app`, `intent`,
`graph`, `cli`, and `domain` modules do not import `fastapi`.

Expected production files when implementation is later approved:

- `pyproject.toml`
- `src/iac_agent/api/__init__.py`
- `src/iac_agent/api/app.py` — `create_app`, lifespan, health, readiness
- `src/iac_agent/api/routes.py` — the three `/api/v1` routes
- `src/iac_agent/api/schemas.py` — public DTOs, not `WorkflowView`
- `src/iac_agent/api/project.py` — projection from submission and view
- `src/iac_agent/api/approval.py` — idempotent versus conflict decision
- `src/iac_agent/app/service.py` — `read` returns `None` for an empty snapshot
- `src/iac_agent/cli/ids.py` — docstring only: the HTTP adapter may call
  `generate_request_id`; `IacApplication` still requires an explicit id
- `docs/api.md` — public contract, including the pre-workflow and auth limits
- `docs/roadmap.md` — replace the sentence that says a FastAPI adapter
  has not been started, after the implementation exists

Expected tests:

- `tests/unit/api/test_schemas.py` — projection allowlist and denylist
- `tests/unit/api/test_routes.py` — status codes with a fake holder
- `tests/integration/test_api_fresh_process.py` — real SQLite, fake
  Terraform, Checkov, and source control; close instance A; open
  instance B; `GET`; approve; assert the PR URL and no GitHub call
- `tests/unit/api/test_import_isolation.py`
- an addition to `tests/unit/app/test_service.py` for the missing
  checkpoint read

Not expected to change: `graph/workflow.py`, policy modules, Checkov
profiles, Terraform modules, GitHub adapter, observability package,
CI workflow files, Docker, and any UI.

## 10. Testing strategy

Tests use FastAPI `TestClient` and the existing fake interpreter,
renderer, Terraform runner, Checkov adapter, and source-control port.
They are unmarked. They stay inside
`pytest -m "not real_tool and not real_llm"`.

Required cases:

- each section 5 outcome, including clarification, unsupported, blocked,
  error, awaiting approval, reject, and pull-request created
- interpreter errors map by exception type and hide `str(exc)`
- omitted `request_id` matches `req-` plus a timestamp and 12 hex digits
- malformed ids return 400 and do not create a workspace
- duplicate `POST` of an existing id returns 409 and does not publish
- repeated `GET` is stable and does not call publish
- approve and reject from a fresh process on the same database file
- second identical approve returns 200 only when status is `pr_created` or `approved` with decision `approve`; second identical reject returns 200 only when status is `rejected`
- approve after reject, reject after approve, and any approval while `blocked` or `error` return 409 and are not success
- a valid unknown id returns 404 for `GET` and approval, with no synthesized `pending` or `awaiting_approval`
- response JSON contains none of the section 5.4 denylist needles
- component names that the operator must see are present
- a raising observability port does not change a 201 or a 200 approval
- AST confirms `app`, `intent`, `graph`, `cli`, and `domain` do not
  import `fastapi`

No live OpenAI, AWS, GitHub, or Langfuse call is part of this batch.

## 11. Closed decisions

Accepted for implementation. No alternative in this list is in scope
for Batch 29.

1. Clarification-required and unsupported-architecture outcomes are
   synchronous HTTP responses. They are not written to the LangGraph
   SQLite checkpoint. There is no second request database, table, event
   store, or persistence abstraction to hold them. `POST` returns 200.
   A later `GET` of that id is 404.
2. Public findings are only `policy_id`, `status`, and `severity`.
3. The public API omits `WorkflowError.message`, exception repr,
   traceback, subprocess output, Terraform diagnostics, provider
   responses, and internal paths. It may include `error_type` and the
   workflow stage. The CLI keeps its current error text.
4. Resolved resource and component names are on the HTTP body. The
   pull-request body field is `url` only. Owner, repository, branch,
   base branch, and tokens are not HTTP fields.
5. Rendered Terraform stays off every v1 response. There is no
   Terraform or source endpoint.
6. Authentication is deferred. The server binds `127.0.0.1`. An
   unauthenticated API is not production-ready for public exposure.
   Docker must revisit bind and network policy later.
7. The same decision is idempotent only when the checkpoint proves it
   already happened: approve when status is `pr_created` or `approved`
   with decision `approve`, and reject when status is `rejected` with
   decision `reject`. Contradictory or impossible transitions, including
   any approval while `blocked` or `error`, are HTTP 409. They are not
   rewritten as success.

## 12. Out of scope

Docker, a web UI, CORS for a browser on another origin, pagination,
request listing, caller accounts, apply and destroy, a publication
retry, KMS, CloudFront, registry or catalog work, Batch 25 AWS and
OIDC changes, and any live cloud call.
