# LLM observability and the Langfuse boundary (Batch 28)

Design and discovery only. No production code, no dependency, no
telemetry, no account, and no credentials are part of this document.

Baseline: `origin/main` at `04513d3` (`Merge pull request #10`).
Branch: `docs/batch28-llm-observability-design`.

Langfuse is a candidate sink for LLM operations. It is not a reason to
redesign the platform, and it is not a security gate.

Sources for the vendor facts below, read on 2026-09-27:

- https://langfuse.com/docs/observability/sdk/overview
- https://langfuse.com/docs/observability/sdk/upgrade-path/python-v3-to-v4
- https://langfuse.com/docs/compatibility
- Python SDK reference: `Langfuse.create_trace_id(seed=...)` produces a
  deterministic 32-hex trace id from an external seed.

## 1. Current-state discovery

The natural-language path and the Terraform path are already separate.

`IntentResolutionService.submit` (`src/iac_agent/intent/service.py`)
calls `IntentInterpreterPort.interpret`, then
`ArchitectureResolver.resolve`. Only a `ResolvedArchitecture` is passed
to `IacApplication.submit`. Clarification, unsupported architecture, and
every `IntentInterpreterError` stop before the graph.

`IacApplication` (`src/iac_agent/app/service.py`) holds a compiled
LangGraph and exposes `submit`, `resume`, and `get_state`. It returns a
`WorkflowView`. It does not contain Terraform, Checkov, or GitHub
objects.

`build_iac_workflow` (`src/iac_agent/graph/workflow.py`) compiles this
graph, with every external tool injected:

`START → render_terraform → terraform_execute → plan_analysis →
platform_policy → checkov_scan → security_gate → approval_gate →
source_control → END`

`security_gate` routes to `approval_gate` only when status is
`AWAITING_APPROVAL`. `BLOCKED` and `ERROR` end there. `approval_gate`
calls LangGraph `interrupt()`. Only `APPROVED` continues to
`source_control`.

Durability is optional and explicit. `workflow_config(request_id)`
(`src/iac_agent/persistence/checkpoints.py`) sets LangGraph `thread_id`
to the same `request_id`. The CLI generates that id in
`generate_request_id` (`src/iac_agent/cli/ids.py`) as
`req-%Y%m%dT%H%M%SZ`. The application APIs require the caller to pass
it. Resume is `IacApplication.resume` → `Command(resume=decision.value)`
on that thread. A fresh process opens a new SQLite checkpointer and a
newly compiled graph against the same database file. That pattern is
already proven by the resource persistence tests.

The only application logger in `src/` is
`iac_agent.intent.adapters.openai._LOGGER`. `OpenAIIntentInterpreter._log`
records `request_id`, `provider`, `model`, `prompt_version`,
`latency_ms`, `attempt_count`, `outcome_category`, and, when the SDK
usage object has them, `input_tokens` and `output_tokens`. The method
docstring forbids the raw request, the raw response, and the API key.
There is no cost field. There is no metric system. There is no trace
that continues into the graph.

Eval diagnostics already exist and are eval-only:
`evals/observability/layer2.py`. It is not imported by `iac_agent.intent`.
It persists a closed allowlist and scrubs `sk-...` and `Bearer` tokens.
`AdapterTelemetryCapture` copies only the adapter's safe log extras.

Configuration already separates secrets from loggable settings.
`ApplicationConfig` (`src/iac_agent/app/config.py`) has no token.
`GITHUB_TOKEN` and `OPENAI_API_KEY` are loaded as `SecretStr` beside
it. The module docstring says no domain module and no LangGraph node
reads `os.environ`. `openai` is an optional extra in `pyproject.toml`.
Langfuse is not a dependency.

`WorkflowState` checkpoints `generated_files` (rendered Terraform text)
and the typed spec. It deliberately has no raw plan JSON field.
`plan_analysis` keeps `terraform show -json` in a local variable and
stores `PlanSummary` only. `WorkflowError` stores stage, exception type
name, and `str(exc)[:500]`. It does not store a traceback. The CLI
presenter is specified not to add a second redaction layer on that
message. Approval payloads include `finding.resource`, which is the
resource name.

The registry/catalog ADR
(`docs/adr/2026-09-27-registry-catalog-deferred.md`) stays deferred.
This batch adds no resource type, no repeated semantic metadata, and no
plugin requirement. None of its reopening criteria are met.

## 2. Exact pipeline map

| Step | Owner | What crosses the boundary |
|---|---|---|
| CLI parse | `cli/main.py`, `cli/parser.py`, `cli/ids.py` | `request_id`, NL text, later `--approve`/`--reject` |
| Config | `app/config.py`, `app/composition.py` | non-secret config; `SecretStr` tokens stay out of config objects |
| Interpret | `IntentInterpreterPort`; today `OpenAIIntentInterpreter.interpret` | NL text in, `ArchitectureIntent` out. One retry (`_MAX_ATTEMPTS = 2`) on timeout and unavailability. Auth and refusal do not retry |
| Parse | `intent/port.py` `parse_intent_payload` | schema version then `ArchitectureIntent.model_validate` |
| Resolve | `ArchitectureResolver.resolve` | pure. Outcomes: `resolved`, `clarification_required`, `unsupported` |
| Submit graph | `IacApplication.submit` | `request_id` + `IacRequestSpec` |
| Render | node `render_terraform` via `IacRenderer` | workspace files, including `generated_files` |
| Terraform | node `terraform_execute` via `TerraformRunner` | fmt, init, validate, plan. Placeholder plan env is in the graph module and is not stored in state |
| Plan analysis | node `plan_analysis` via `analyze_plan` | `PlanSummary` only |
| Platform policy | node `platform_policy` | `PolicyEvaluation` |
| Checkov | node `checkov_scan` via `CheckovAdapter` | `CheckovScanResult` |
| Gate | node `security_gate` | `SecurityGateResult`. This decides BLOCK vs approval. Langfuse does not |
| HITL | node `approval_gate` | `interrupt(_approval_payload(state))`, then `ApprovalDecision` |
| Publish | node `source_control` via `SourceControlPort` | `PullRequestResult` or `SourceControlError` |
| Present | `cli/present.py` | bounded text. Trailer `terraform apply: not executed` |

Direct `IacApplication.submit` of a typed spec never calls the
interpreter. That path exists and must remain valid with no LLM span.

## 3. Existing observability gaps

- The LLM log and the workflow share `request_id` and nothing else.
  After process exit, the log line is not joined to the checkpoint.
- Resolver outcome, policy status, plan counts, approval decision, and
  publication outcome are not logged at all.
- Token counts exist only as log extras on a successful or captured
  adapter call. They are not on `ArchitectureIntent` and not in
  `WorkflowState`.
- There is no latency split between render, Terraform, Checkov, and
  the model.
- `WorkflowError.message` can contain whatever the exception string
  contained, truncated to 500 characters. That is acceptable for the
  local CLI. It is not acceptable as vendor telemetry.
- `generated_files` and resource names are already inside the SQLite
  checkpoint. That is local state, not a license to copy them to a
  third party.

## 4. Langfuse justification

Langfuse is justified for one operation: the interpreter call, plus a
small set of correlation events that let a later resume join the same
request. The platform already has deterministic correctness evals.
Langfuse does not make Terraform more correct.

It is not justified as a trace of every graph node, as a store for
prompts or plans, or as a replacement for `WorkflowView` and the CLI.
If the only goal were "see token counts," the existing log extras
already have them. The missing capability is durable correlation and a
queryable generation record that survives the HITL pause.

Recommendation: adopt Langfuse later as an optional adapter behind a
platform port. Do not adopt it as a dependency of the graph.

## 5. Proposed architecture

Keep business decisions where they are. Add one observability port
beside the existing ports (`IntentInterpreterPort`,
`SourceControlPort`). Composition wires it. Nodes do not import it.

Two emission sites, both already orchestration rather than policy:

1. `IntentResolutionService.submit`, around interpret and resolve.
   This is the only place that sees both the provider outcome and the
   resolver outcome, and the only place that knows the workflow was
   not entered.
2. `IacApplication.submit` and `IacApplication.resume`, after
   `_to_view`. The view is already the minimized workflow fact set.
   `get_state` stays a pure read and emits nothing.

Per-stage latency, if wanted later, is a composition-time wrapper
around the injected `TerraformRunner` and `CheckovAdapter`, not code
inside the nodes. The wrapper records duration and a status. It does
not record stdout, stderr, or the plan document. That wrapper is not
required for the first gate.

Default implementation: `NoOpObservability`. It implements the port and
returns. No network.

Optional implementation: a Langfuse adapter constructed only when
Langfuse settings are present. It is not imported by the graph.

The port's methods must not change return values of submit, resolve, or
resume. They are notifications after the decision exists, or a
generation record around the interpreter that still returns the
interpreter's own result.

## 6. Vendor boundary decision

| | Option A, direct SDK | Option B, platform port + Langfuse adapter | Option C, OpenTelemetry-first |
|---|---|---|---|
| Coupling | Graph and interpreter import Langfuse | One adapter imports Langfuse | Platform imports OTEL; Langfuse is an exporter |
| Testing | SDK fakes or network | In-memory fake of the port | OTEL test exporter, plus exporter config |
| Failure isolation | Easy to miss inside a node | One adapter catches its own failures | Exporter failures still need an isolation wrapper |
| Pause/resume | SDK context dies with the process | `create_trace_id(seed=request_id)` is called again in the new process | OTEL context also dies with the process. The same seed problem remains |
| Portability | Low | The event schema stays if the sink changes | High in theory, large in practice |
| Complexity | Lowest until the first resume bug | Matches `SourceControlPort` | Highest. SDK v4 is already OTEL-based internally |
| Fit | Fights the injected-boundary style | Matches it | Exports far more than this repo logs today |

Langfuse's current Python SDK (v4, documented as the GA line) is
observation-centric and OpenTelemetry-based. Correlating attributes are
context-manager scoped. That context does not exist in the process that
later calls `resume`. v4 also stopped exporting every OTEL span by
default. Choosing Option C would add an instrumentation framework in
order to then filter it back down to a handful of events.

**Decision: Option B.** The Langfuse adapter may use the SDK's
deterministic `create_trace_id(seed=request_id)` and a generation
observation for the interpreter. OpenTelemetry stays inside that SDK.
The platform does not take an OpenTelemetry dependency of its own.

Names in a later implementation should follow this repo's `*Port`
style. `ObservabilityPort` is fine. The illustrative names in the batch
prompt are not an API freeze.

## 7. Trace, span, and generation model

One trace per `request_id`. Not one trace per Python process.

| Observation | Kind | When |
|---|---|---|
| `intent.interpret` | Langfuse **generation** | Only when an interpreter ran. Attributes: provider, model, prompt version, latency, attempt count, outcome category, token counts when the adapter already has them. No prompt text. No completion text |
| `intent.resolve` | **event** on that trace | outcome, matched pattern or clarification/unsupported reason, resolved type name (`EcrResourceSpec`, not the resource name) |
| `workflow.submit` | **event** | only if the graph was entered. Stage and workflow status from `WorkflowView` |
| `workflow.resume` | **event** | `approve` or `reject`. No reviewer identity. The domain model has none (`domain/approval.py`) |
| `workflow.terminal` | **event** | final status: `awaiting_approval`, `blocked`, `rejected`, `error`, `pr_created` |

Do not create Langfuse spans for render, Terraform, plan analysis,
platform policy, or Checkov in the first implementation. Those are
deterministic or external-tool operations. Their useful facts are
already on `WorkflowView`: plan add/change/destroy counts, security
status, current stage. A span that existed only to wrap them would
imply the vendor is on the correctness path.

If a later gate adds tool timing, those are spans with duration and
status only, still emitted by the composition wrapper, still without
HCL or scanner JSON.

Checkov and platform policy remain the security gate. A telemetry event
may repeat `overall_status` and the list of `(policy_id, status)`. It
must not contain finding messages or `finding.resource`. Langfuse never
returns a pass/fail that the graph reads.

## 8. Durable pause and resume correlation

`request_id` is already the workflow thread id and the workspace
directory name, after `validate_request_id`. Use that same string as
the Langfuse trace seed. Do not invent a second id.

On interpret, on submit, and on resume, the adapter computes
`create_trace_id(seed=request_id)` and writes observations onto that
id. The resume process does not need the original SDK context, the
original logger, or an in-memory span stack.

The CLI process exits while the workflow is paused. The adapter must
flush before `submit` and `resume` return to the CLI. A failed flush is
an observability failure, not a workflow failure.

`request_id` values generated before this closure are second-resolution
timestamps. Two proposes in the same UTC second collide. That collision
is a platform identity bug, not only a Langfuse bug. Section 29 locks
the generator change. Observability still uses the exact `request_id`
as its correlation key. It does not invent a second id.

`get_state` must not emit. Reconstruction for a human reading state is
not a new observation.

## 9. Telemetry allowlist

Closed set. Unknown keys are dropped.

- `request_id`
- `provider`, `model`, `prompt_version`
- `latency_ms`, `attempt_count`, `outcome_category`
- `input_tokens`, `output_tokens` when the adapter already observed them
- `workload_type`, `interaction_pattern`, capability value strings
- resolver `outcome`, `matched_pattern` or reason enum, resolved class name
- `workflow_status`, `current_stage`
- `security_status`
- plan `add`, `change`, `destroy` counts and `destructive_change_detected`
- finding `policy_id`, `status`, `severity` (not `resource`, not `message`)
- approval decision value `approve` or `reject`
- error `stage` and `error_type` only
- boolean `published` when status is `pr_created`

This overlaps `evals/observability/layer2.py` (`_TELEMETRY_KEYS`,
`_ALLOWED_NORMALIZED_KEYS`, `_ALLOWED_TOKEN_KEYS`) on purpose. The
production allowlist is not that module. That module stays eval-only.

## 10. Telemetry denylist

Never sent, even if present on an object the caller already holds:

- raw natural-language request
- model output text, `assumptions`, `unresolved_questions`, `logical_name_hint`, `confidence`
- rendered Terraform (`generated_files` and on-disk HCL)
- raw plan JSON, plan addresses, ARNs, account ids
- raw Checkov JSON, code blocks, file paths
- resource names, including `finding.resource` and `WorkflowView.resource_name`
- GitHub owner, repository, branch, PR URL, PR title, PR body
- approval identity (none exists; do not add one for telemetry)
- environment variables
- `OPENAI_API_KEY`, `GITHUB_TOKEN`, AWS access key, secret, session token, OIDC/JWT
- the placeholder plan credentials in `_PLAN_ENV_OVERRIDES`
- checkpoint bodies, SQLite paths, workspace paths
- exception messages, stack traces, subprocess stdout/stderr
- `WorkflowError.message`

`PullRequestResult.url` stays in the CLI view. It does not go to Langfuse.

## 11. Redaction and minimization

The primary control is structural allowlisting. A projection function
builds a small telemetry model by naming the fields it copies. Regex
scanning does not make an arbitrary object safe to send, and the
implementation must not pass a raw object through a scanner and then
on to a vendor.

Order, locked:

```
domain / workflow object
        |
        v
explicit telemetry projection
        |
        v
small allowlisted telemetry model
        |
        v
defense-in-depth secret-pattern sanitation
        |
        v
ObservabilityPort
        |
        v
optional vendor adapter
```

The projection accepts an `ArchitectureIntent`, a `ResolutionResult`,
or a `WorkflowView`, and returns a telemetry dataclass. It never
returns the input. `WorkflowState`, Terraform results, Checkov
results, exception objects, environment mappings, and provider
responses are not parameters of the port and are not parameters of
the vendor adapter.

Defense in depth runs only on strings that already sit on the
allowlisted model. It replaces `sk-`, `sk-lf-`, `ghp_`, `github_pat_`,
`AKIA`, `ASIA`, `Bearer`, JWT-shaped strings, `BEGIN PRIVATE KEY`, and
the env-var names `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_SESSION_TOKEN`, `OPENAI_API_KEY`, and `GITHUB_TOKEN` with
`[redacted]`. A string that needed this replacement is a bug in the
projection. The tests for resource names, prompts, and
`WorkflowError.message` must fail because those fields do not exist on
the model, not because a regex deleted them.

Langfuse masking configuration is not the control.

`WorkflowError.message` continues to exist for the local CLI. The
projection does not read it.

## 12. Fail-open behavior

Invariant: if Langfuse is unreachable, credentials are missing or
rejected, a call times out, the SDK raises, or the payload cannot be
serialized, the IaC result is unchanged.

Mechanism: the adapter's public methods catch `Exception`, log a
metadata-only line (`request_id`, `error_type`, no message body) through
the standard logger, and return. They do not catch
`KeyboardInterrupt` or `SystemExit`. Callers do not wrap the port in
their own `try`. A NoOp adapter cannot fail.

The interpreter's own timeout and retry behavior stays in
`OpenAIIntentInterpreter`. Observability does not add a retry of the
model call and does not convert `IntentProviderTimeoutError` into a
successful intent.

A blocked security gate stays `BLOCKED`. An approved resume that
publishes stays `PR_CREATED`. A valid plan is not failed because a
flush failed.

## 13. Provider, token, and cost metadata

Available today, only inside `OpenAIIntentInterpreter._log`:

- `provider` is the literal `"openai"`
- `model` is the configured model string
- `prompt_version` is the module constant `_PROMPT_VERSION` (currently
  `"4"`)
- `latency_ms` from `time.monotonic`
- `attempt_count`
- `input_tokens` and `output_tokens` via `getattr(response.usage, ...)`
  when the SDK object has those attributes

Not available: a price, a currency, or an estimated cost. This design
does not invent one. A later estimate would be a local table keyed by
model, computed after the counts, and still would not require prompt
text. It is out of scope until a human asks for it.

The generation observation should copy the counts the adapter already
computed. It should not call the provider a second time and should not
parse a raw response body.

## 14. Evaluation integration

Three separate concerns:

| Concern | Owner today | Langfuse role |
|---|---|---|
| Deterministic correctness | golden runners under `evals/`, included in `pytest -m "not real_tool and not real_llm"` | None. Do not move expectations into Langfuse datasets |
| Offline real-model quality | `tests/integration/test_architecture_intent_nl_real_model_eval.py`, marker `real_llm`, plus `evals/observability/layer2.py` | Optional later sink for the same allowlisted diagnostic fields. Not a replacement for the golden score |
| Production observability | does not exist | The port in this design |

Langfuse scores, if ever used, are annotations on a trace. They must
not feed `ArchitectureResolver` or `evaluate_security_gate`.

Useful later distributions, all computable from the allowlist: latency,
token counts, model, attempt count, clarification rate, unsupported
rate, resolver outcome, security status, approve/reject, terminal
workflow status. Cost per request is not computable from current data.

## 15. Local development

`git clone`, install, and `pytest -m "not real_tool and not real_llm"`
must pass with no Langfuse env vars and no Langfuse package imported
on that path.

Default is NoOp when `IAC_AGENT_OBSERVABILITY` is unset, empty, `off`, or `noop`. `langfuse` is a recognized backend name and, until Gate B provides the adapter, `build_observability` raises `ObservabilityConfigurationError` instead of pretending that backend is active. Any other value fails at load. This configuration failure is not a workflow telemetry failure: fail-open still applies only after a sink has been constructed. Langfuse keys are not read in Gate A. When Gate B adds them, they stay `SecretStr` and off `ApplicationConfig`.

The Langfuse SDK belongs in an optional extra, the same way `openai`
does. The base install does not depend on it.

## 16. Test strategy

All of the following are ordinary unit tests. None open a socket.
None are marked `real_tool` or `real_llm`.

| # | Case | Assertion |
|---|---|---|
| 1 | Observability disabled / keys absent | composition builds `NoOp`; submit still returns the workflow view |
| 2 | NoOp | port methods return; no extra attribute appears on `WorkflowView` |
| 3 | Fake adapter | interpret + resolve + terminal events recorded in order for one `request_id` |
| 4 | Generation metadata | fake records model, prompt version, attempt count, token counts; not the prompt |
| 5 | Secret redaction | a payload that somehow contains `sk-`, `ghp_`, `AKIA`, `Bearer`, or `AWS_SECRET_ACCESS_KEY` is dropped or redacted before the fake sees it |
| 6 | Plan minimization | event has add/change/destroy counts and no address, ARN, or HCL |
| 7 | Checkov minimization | policy id and status only; no message, path, or raw JSON |
| 8 | Adapter raises | submit result is unchanged; status is not rewritten to `ERROR` |
| 9 | Adapter timeout | same as 8 |
| 10 | Pause/resume | resume event uses the same `request_id` seed as submit; no second trace id |
| 11 | Fresh process | the id is a pure function of `request_id`, not of process or object identity |
| 12 | Reject | decision `reject`, status `rejected`, no publish event |
| 13 | BLOCK | graph not awaiting approval; security status `block`; no approval event |
| 14 | ERROR | `error_type` and stage only; message text absent |
| 15 | Clarification | workflow view is absent; resolver outcome recorded; no Terraform event |
| 16 | Unsupported | same, with unsupported reason |
| 17 | Network | unit tests do not import the Langfuse SDK. A later smoke test is a new marker, excluded from CI the way `real_llm` is |
| 18 | Secrets at rest | the fake's recorded documents contain none of the denylist |

Do not add a test that calls Langfuse Cloud.

## 17. Langfuse Cloud versus self-hosted

Documented on 2026-09-27:

- Langfuse Cloud always runs the current server. Regions include EU
  (`https://cloud.langfuse.com`), US, Japan, and a HIPAA endpoint.
  Cloud does not inherit self-hosted server minimums.
- Self-hosted upgrades are operator-owned. Python SDK v3 and v4 need
  server ≥ 3.63.0. Observations API v2 and Metrics API v2 need
  Langfuse server v4. On self-hosted v3 the SDK must use the legacy
  API resources.
- Auth is `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`, plus
  `LANGFUSE_BASE_URL` when not using the default cloud host.
- Trace ingestion is moving to the OpenTelemetry endpoint. The legacy
  ingestion API is scheduled to sunset on Cloud on 2026-11-16.

Self-hosting means running and upgrading Langfuse's own stack, database,
and auth secrets. That is a second product. It does not teach the IaC
workflow, and it adds retention and patching work this portfolio does
not otherwise have. Privacy is not automatically better: a
self-hosted server that receives prompts is still a prompt store. This
design refuses prompt upload either way.

**Recommendation for now: Langfuse Cloud, opt-in, off by default.**
No project is created by this batch. No key is committed. If a human
later creates a project, pick the region deliberately and keep the
base URL in the environment, not in code. Self-hosting is a reasonable
later choice for a deployment that must not leave the operator's
network. It is not the next implementation step.

## 18. Security boundaries

| System | Decides whether Terraform may proceed? | Stores prompts? |
|---|---|---|
| Platform policies + Checkov + security gate | Yes | No |
| Langfuse | No | Not in this design |
| AWS monitoring | No, and this batch does not add any | No |
| Application log (`_LOGGER` extras) | No | No |
| SQLite checkpoint | No | It stores the spec and rendered files locally. Telemetry does not copy that |

A Langfuse outage must not flip `PASS` to `ERROR` or `APPROVED` to a
failed workflow. Section 12 is the mechanism.

## 19. Theoretical production files

A later implementation would touch:

- new `src/iac_agent/observability/` package: port, NoOp, fail-open
  wrapper, allowlisted event model, projection, defense-in-depth
  sanitation
- new `src/iac_agent/observability/adapters/langfuse.py`, imported only
  when the optional extra is installed and keys are set
- `src/iac_agent/cli/ids.py`: section 29 generator. Validators stay
- `src/iac_agent/intent/adapters/openai.py`: retain the safe metadata
  dict the adapter already logs, so the service can project it. No
  Langfuse import
- `src/iac_agent/app/config.py`: observability off by default. Langfuse
  secrets, when added, stay `SecretStr` and off `ApplicationConfig`
- `src/iac_agent/app/composition.py`: choose NoOp or the adapter
- `src/iac_agent/intent/service.py`: emit interpret and resolve events
- `src/iac_agent/app/service.py`: emit submit and resume events from
  `WorkflowView`
- `pyproject.toml`: optional extra only, in the implementation batch,
  not in this design commit

Not touched: `graph/workflow.py` nodes, contracts, renderers, Terraform
modules, policies, Checkov profiles, checkpoint allowlist, resolver
rules, CLI presentation rules.

`graph/workflow.py` changes only if a later gate adds the optional
runner/adapter timing wrappers. The first gate does not need that.

## 20. Theoretical test and eval files

- new `tests/unit/observability/` for the table in section 16
- `tests/unit/app/` composition test: missing keys select NoOp
- no change to golden datasets
- no change to `evals/observability/layer2.py` in the first gate
- a future `real_observability` test, if any, lives under
  `tests/integration/` and stays out of the CI pytest mark, following
  `real_llm`

## 21. Migration and compatibility

No change to `ArchitectureIntent`, resolver outcomes, `WorkflowState`,
checkpoint schema, or CLI exit codes. Existing callers that construct
`IntentResolutionService` or `IacApplication` directly in tests keep
working if the port defaults to NoOp.

The graph's checkpoint format does not gain a trace id. The id is
recomputed from `request_id`. Old checkpoints resume without a
migration.

## 22. Risks

- Flush-on-exit can add latency. Cap the adapter timeout in
  milliseconds and fail open. Do not reuse the interpreter's
  multi-second timeout.
- `WorkflowError.message` and `finding.resource` are easy to forward by
  accident because they are already on objects the application holds.
  Tests 5, 7, and 14 exist to stop that.
- Deterministic trace ids are only as unique as `request_id`.
  Section 29 changes the CLI generator so two proposes in the same
  UTC second do not share a thread, workspace, or branch. Caller-supplied
  `--request-id` can still name an existing thread on purpose.
- SDK v4 context managers feel like the natural API and will not
  survive `resume`. The adapter must use the explicit trace id.
- Cloud data leaves the machine. The allowlist is the mitigation.
  Self-hosting does not replace the allowlist.

## 23. Alternatives considered

- **Do nothing.** Keeps the privacy bar. Leaves token counts in
  ephemeral logs and no join across HITL. Rejected as the end state,
  acceptable as the default until a human opts in.
- **Direct SDK in the interpreter only.** Solves the generation and
  misses resume, policy status, and the fail-open rule at the
  application boundary.
- **OpenTelemetry-first.** Section 6.
- **Put traces in SQLite.** Duplicates the checkpoint and still is not
  LLM observability. Rejected.
- **Send the raw prompt to Langfuse and mask later.** Rejected.
  Section 11.

## 24. Portfolio value

The valuable demonstration is not "imported Langfuse." It is a
fail-open port, a denylist enforced before the vendor sees data, and a
trace id that is a pure function of the existing durable `request_id`
so a second process can resume the same trace. That is production AI
engineering sitting next to an IaC control loop that already refuses
to treat an LLM as the authority for Terraform.

If the implementation only wraps the OpenAI call in a decorator and
uploads the prompt, it does not clear that bar and should not be built.

## 25. Relationship to the roadmap

Proposed later batches (KMS, CloudFront + S3 + OAC, SNS/EventBridge,
Secrets Manager, ECS/Fargate + ECR, ALB, RDS/Aurora) add resources.
They do not change the interpreter, the pause/resume thread id, or the
security gate's role.

Batch 28 should stay here. The instrumentation points are
`IntentResolutionService` and `IacApplication`, which already sit in
front of every resource. Waiting until after more resources does not
make the privacy or correlation design more accurate. It also should
not move in front of those resources as a blocker: NoOp is the default,
and KMS does not depend on Langfuse.

The registry ADR is unchanged.

## 26. Explicit non-goals

- Implementing Langfuse, adding the dependency, or editing CI
- Creating a Langfuse project, key, or self-hosted stack
- Changing resolver or intent semantics
- Adding AWS resources, Terraform modules, KMS, CloudFront, or ECS
- Reopening the registry/catalog
- Changing Checkov or platform-policy decisions
- Replacing golden evals
- Sending telemetry anywhere as part of this design batch
- Touching Batch 25's deferred AWS/OIDC work
- Generic IaC generation
- Estimated dollar cost
- Per-node Langfuse spans in the first implementation gate

## 27. Human decisions

Closed in the design-closure review. None of these authorizes prompt
upload, a Langfuse account, or a live telemetry call.

1. Architecture: `ObservabilityPort`, default `NoOpObservability`,
   optional Langfuse adapter. Business and workflow code do not import
   the Langfuse SDK.
2. Default: off. `git clone`, install, and pytest need no Langfuse
   account, credentials, network, or telemetry.
3. If a later real integration is exercised, Langfuse Cloud. Do not
   self-host for this portfolio stage. Do not create the project in
   the planning pass.
4. Denylist in section 10 is approved, including resource names, PR
   URLs, `finding.resource`, `finding.message`, and
   `WorkflowError.message`. The CLI may keep showing those locally.
5. Security findings on the wire are `policy_id`, `status`, and
   `severity` only.
6. Raw prompt and model-output capture are prohibited. There is no
   configuration toggle for them in this batch.
7. Token metadata is copied only when the provider supplied it.
   Missing usage is valid. Cost estimation is deferred.
8. Langfuse does not participate in policy, Checkov, the security
   gate, HITL, or Terraform correctness.
9. Telemetry failure never changes a workflow result. Isolation lives
   inside the observability boundary, not in caller `try` blocks.
10. First-stage observations are `intent.interpret` (generation),
    `intent.resolve` (event), `workflow.submit`, `workflow.resume`,
    and `workflow.terminal` (events). `get_state` emits nothing.
    Terraform and Checkov timing spans are deferred.
11. The correlation key is the durable `request_id`, recomputed after
    process restart. Section 29 locks how that id is generated.
    In-memory span stacks are not the resume mechanism.

## 28. Recommended implementation gates

The task list is
`docs/superpowers/plans/2026-09-27-llm-observability-langfuse.md`.

**Gate A — platform core, no vendor.** Request-id generator fix from
section 29. Telemetry models, projection, defense-in-depth sanitation,
port, NoOp, fail-open wrapper, default-off configuration, and
instrumentation of `IntentResolutionService` and `IacApplication`.
Normal pytest does not import Langfuse and does not open a socket.

**Gate B — optional adapter, still no live call.** Optional extra,
Langfuse adapter against a fake client, deterministic seed, flush,
import isolation, documentation. Gate B tests must pass without
network and without credentials.

**Gate C — not part of this plan.** A live Cloud smoke test is not
required to prove the boundary. It would need credentials and a
network call, and it cannot prove more about allowlisting than the
fake adapter already proves. If a human later wants that smoke, it is
a separate authorized gate, marked like `real_llm`, and excluded from
`pytest -m "not real_tool and not real_llm"`. It is not a task in the plan.

## 29. Request-id collision

### What the code does today

`generate_request_id` (`src/iac_agent/cli/ids.py`) formats
`req-%Y%m%dT%H%M%SZ`. The CLI (`src/iac_agent/cli/main.py`) uses that
only when `--request-id` is omitted. `propose --request-id` and
`resume <request_id>` (`src/iac_agent/cli/parser.py`) pass the caller's
string through unchanged.

`workflow_config` (`src/iac_agent/persistence/checkpoints.py`) sets
LangGraph `thread_id` to that exact string. The workspace directory is
`<workspace_root>/<request_id>`
(`src/iac_agent/graph/workflow.py`, `_resolve_request_workspace`).
`derive_branch_name` returns `iac-agent/<request_id>`
(`src/iac_agent/domain/source_control.py`). Published files land at
`generated/<request_id>/...`. `GitHubSourceControl.publish_change`
(`src/iac_agent/git/github.py`) treats an existing branch as a conflict
and says a second publish of the same `request_id` always collides.
When `logical_name_hint` is absent, `fallback_base_name`
(`src/iac_agent/intent/naming.py`) derives the resource name from
`request_id`. `normalize_hint` keeps at most 40 characters.

The only test that asserts the generated shape is
`tests/unit/cli/test_ids.py`. Other tests and evals pass literal ids
(`req-001`, `req-ecr-durable-001`, `layer2-eval-fixture-request`).
The historical tree `generated/req-20260926T215226Z/` on `main` is a
past artifact, not a generator output this batch should rename.

`validate_request_id` allows any non-empty single path segment.
`derive_branch_name` further requires
`^[A-Za-z0-9][A-Za-z0-9._-]*$`.

### What a same-second collision does

Two generated ids that compare equal are the same platform identity:

- the second `invoke` uses the first run's SQLite thread
- the second render writes the first run's workspace directory
- publication targets the same branch and the same `generated/` path
- a later resume can approve the wrong paused workflow
- a Langfuse seed derived from that id would alias the two requests

A caller who passes an existing `--request-id` is selecting that
identity on purpose. The generator must not rewrite stored ids, and
it must not probe the database to see whether an id is free.

### Options

| | Mechanism | Readability | Checkpoint collision | Dependency | Name fallback |
|---|---|---|---|---|---|
| A | UTC second + 12 hex from `uuid.uuid4()` | Stamp stays visible | New ids differ within the same second | stdlib | 33-character id fits the 40-character `normalize_hint` window |
| B | `req-` + UUID4 | No time stamp | Unique | stdlib | A 40-character id is truncated by `normalize_hint` before `fallback_base_name` adds its own prefix, so hint-less names can lose entropy |
| C | ULID | Sortable and compact | Unique | No stdlib ULID. A new package or a hand-rolled encoder | Not justified. The timestamp prefix already sorts to the second |
| D | Keep the timestamp id and add a second correlation id | Old id unchanged | Thread, workspace, and branch still collide | None | Does not fix the platform bug |

### Locked choice

Option A.

```
req-%Y%m%dT%H%M%SZ-<12 lowercase hex>
```

Example: `req-20260918T232211Z-a1b2c3d4e5f6`.

`generate_request_id(now=None, *, entropy=None)` keeps the injectable
clock. `entropy` defaults to `uuid.uuid4().hex`; the generator uses
the first 12 characters and rejects a value that is not 12 lowercase
hex digits. Tests inject both `now` and `entropy`. Naive datetimes
stay rejected.

Twelve hex digits is 48 bits from `uuid4`, which is enough for a local
CLI. It is not a distributed consensus id. The character class already
accepted by `validate_request_id` and `derive_branch_name` includes
digits and hyphens, so no validator change is required.

The id is 33 characters. `normalize_hint` keeps it. `fallback_base_name`
then prefixes `req-`, producing a 37-character base, inside the
existing 40-character hint budget. Hint-less names of two same-second
requests stay distinct.

### Compatibility

- Existing checkpoints resume with the id they were stored under.
  There is no migration and no rewrite of SQLite rows.
- `generated/req-20260926T215226Z/` stays where it is.
- Literal ids in tests and evals stay valid.
- `--request-id` and `resume <request_id>` stay caller-supplied
  strings. This batch does not add a format check beyond the
  validators those strings already pass through.
- Observability stores and seeds from the exact `request_id`. The
  Langfuse adapter may call `create_trace_id(seed=request_id)` because
  that vendor wants a 32-hex trace id. That derivation is recomputed
  in the resume process. It is not a second platform identifier and
  it is not written to the checkpoint.

### What this closure does not implement

The generator change is specified here and tasked in the plan. This
commit does not edit `src/iac_agent/cli/ids.py`.
