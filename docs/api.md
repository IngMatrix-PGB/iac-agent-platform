# Local HTTP API

FastAPI is an inbound adapter over `IntentResolutionService` and `IacApplication`. Routes do not call LangGraph nodes, Terraform, Checkov, OpenAI, the Langfuse SDK, GitHub, or the SQLite checkpointer directly. There is no second request store. `request_id` is the workflow `thread_id`.

The process listens on `127.0.0.1` port 8000. There is no authentication and no authorization. This boundary is for local development. It is not production-ready for public exposure. A later Docker batch has to choose its own bind address and network policy; Docker is not part of this batch.

## Routes

- `GET /health` returns `{"status":"ok"}`. It does not call AWS, OpenAI, Langfuse, GitHub, or the Terraform Registry.
- `GET /ready` returns `{"status":"ready"}` when the application holder exists, and `503 {"status":"not_ready"}` when it does not. Readiness is that local check. Langfuse is not a readiness probe and does not authorize requests.
- `POST /api/v1/requests` accepts `natural_language_request` and an optional `request_id`. An omitted id is generated with the existing request-id helper. The route calls `IntentResolutionService.submit`.
- `GET /api/v1/requests/{request_id}` calls `IacApplication.read`.
- `POST /api/v1/requests/{request_id}/approval` accepts `{"decision":"approve"}` or `{"decision":"reject"}` and calls `IacApplication.resume` only when the durable status is `awaiting_approval`.

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

## What this batch does not do

This API does not authenticate callers, authorize them, deploy to AWS, publish through real GitHub in the HTTP acceptance test, generate arbitrary Terraform, expose a workflow event history, or return Terraform source. The acceptance test uses a fake source-control port and a local SQLite file. Its published URL is the fake `https://example.invalid/pull/7`.
