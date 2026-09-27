# Observability

Platform telemetry is optional, off by default, and outside every workflow decision. Langfuse, when configured, receives only the allowlisted models already projected by the application. It does not approve, reject, block, or rewrite Terraform, security, or human-approval results.

This document describes the adapter boundary proven with an injected fake client. It does not claim that Langfuse Cloud was called, that a Langfuse project exists, or that a live smoke test passed.

## Architecture

```
domain object
    → explicit projection
    → telemetry model
    → sanitation
    → ObservabilityPort
    → FailOpenObservability
    → NoOpObservability  or  Langfuse adapter
```

`IntentResolutionService` emits `intent.interpret` and `intent.resolve`. `IacApplication.submit` and `IacApplication.resume` emit `workflow.submit` or `workflow.resume`, plus `workflow.terminal` when the view is no longer awaiting approval. `get_state` emits nothing. Graph nodes are not instrumented. Terraform and Checkov timing spans are not part of this batch.

The adapter accepts only `GenerationTelemetry`, `ResolutionTelemetry`, and `WorkflowTelemetry`. It does not accept `WorkflowState`, `WorkflowView`, raw `ArchitectureIntent`, Terraform source, plan JSON, Checkov result objects, exceptions, environment mappings, or provider responses. Projection stays in `project.py`. Sanitation stays in `sanitize.py`.

## Default off

| `IAC_AGENT_OBSERVABILITY` | Result |
|---|---|
| unset, empty, `off`, `noop` | `FailOpenObservability(NoOpObservability())` |
| `langfuse` with both keys | Langfuse adapter, wrapped in `FailOpenObservability` |
| `langfuse` with a missing key or a client that cannot be constructed | `ObservabilityConfigurationError` at configuration time |
| any other value | `MissingConfigurationError` at configuration time |

An explicit `langfuse` selection is never silently replaced with NoOp. Runtime failures after the adapter exists stay fail-open and do not change the workflow result. Configuration failures are printed by the CLI and are not workflow telemetry failures.

`NoOpObservability` implements the port and records nothing. The disabled path does not import or construct Langfuse.

## Optional extra

`langfuse>=4,<5` is an optional extra in `pyproject.toml`. It is not part of the base dependencies and not part of the `dev` or `openai` extras. CI installs `.[dev,openai]` and does not install Langfuse. The application imports without the `langfuse` distribution. The SDK import lives inside `build_langfuse_observability`, which runs only after `langfuse` mode has passed configuration checks.

## Configuration

| Variable | Role |
|---|---|
| `IAC_AGENT_OBSERVABILITY` | `off` / `noop` or `langfuse` |
| `LANGFUSE_PUBLIC_KEY` | required when the mode is `langfuse` |
| `LANGFUSE_SECRET_KEY` | required when the mode is `langfuse` |
| `LANGFUSE_BASE_URL` | optional; default `https://cloud.langfuse.com` |

Keys are wrapped in `SecretStr` and are not fields of `ApplicationConfig`. They are unwrapped only at the Langfuse client constructor. Configuration errors name the missing variable or the exception type. They do not include secret values. Self-hosting is not the portfolio path.

## Trace identity

`request_id` is the durable correlation key. It is also the LangGraph thread id. The adapter calls `create_trace_id(seed=request_id)` on the Langfuse client. That value is a vendor formatting of the same seed. It is not a second platform id, and it is not stored on `WorkflowState`, the SQLite checkpoint, `ArchitectureIntent`, or a resource spec.

A fresh process that resumes the same `request_id` derives the same trace id because the function of the seed does not depend on process or object identity. A different `request_id` derives a different trace id. Pause and resume therefore share one trace without persisting the vendor id.

## Observations

| Name | Kind |
|---|---|
| `intent.interpret` | generation |
| `intent.resolve` | event |
| `workflow.submit` | event |
| `workflow.resume` | event |
| `workflow.terminal` | event |

Token counts are sent as Langfuse `usage_details` (`input`, `output`) only when the interpreter already supplied them. Absent counts stay absent. There is no cost estimate. The generation metadata is provider, model, prompt version, latency, attempt count, and outcome category. No prompt or completion argument is passed.

Flush runs at the end of interpretation/resolution and at the end of submit/resume, after the platform result already exists.

## Allowlist

Generation: `request_id`, `provider`, `model`, `prompt_version`, `latency_ms`, `attempt_count`, `outcome_category`, and token counts when present.

Resolution: `request_id`, `outcome`, `workload_type`, `interaction_pattern`, `capabilities`, `user_provided_hints`, `matched_pattern`, `resolved_type`, `clarification_reason`, `unsupported_reason`.

Workflow: `request_id`, `kind`, `workflow_status`, `current_stage`, `security_status`, add/change/destroy counts, `destructive_change_detected`, `approval_decision`, `error_stage`, `error_type`, `published`.

Findings on the wire: `policy_id`, `status`, `severity`.

## Denylist

These values have no telemetry field and are not sent:

- raw prompts and raw model responses
- assumptions, unresolved questions, and `logical_name_hint`
- Terraform source and plan JSON
- resource addresses, resource names, and ARNs
- AWS account IDs
- `finding.resource` and `finding.message`
- `WorkflowError.message`, stack traces, and subprocess output
- GitHub owner, repository, branch, and pull-request URL
- environment variables, credentials, and tokens
- checkpoint contents and workspace paths

Structural projection is the safety boundary. Regex scrubbing in `sanitize.py` is defense in depth on strings that already passed the allowlist. The CLI may still show denied facts locally. That display is not the telemetry payload.

## Failure semantics

`FailOpenObservability` catches exceptions from event creation, generation creation, trace handling, and flush. It logs the operation name, `request_id` when one exists, and the exception type. It does not log the exception text. The underlying submit, resume, approval, rejection, block, or clarification result is unchanged. Graph nodes do not catch observability errors. Security policy evaluation and HITL behavior are unchanged.

## What Langfuse does not control

Langfuse is not Checkov, not a platform policy, and not AWS infrastructure monitoring. It does not decide security status, approval, rejection, or whether Terraform runs. Golden evals stay in the repository. Langfuse scores, if ever added later, must not feed the resolver or the security gate.

## What this batch did not prove

The adapter tests inject a fake client. They do not call Langfuse Cloud, do not use real Langfuse credentials, and do not call OpenAI. A future live smoke test would be a separate, explicit opt-in with the extra installed and keys supplied by a human. That boundary is not implemented here, and this document is not evidence that it passed.
