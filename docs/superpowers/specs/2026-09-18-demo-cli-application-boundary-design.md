# Design Spec: End-to-End Demo CLI / Application Boundary (Batch 24)

Status: **APPROVED — locked for implementation planning**
Scope: **design only in this document** — no production code, no CLI
scaffolding, no new dependencies, no OpenAI call, no AWS credentials,
and no `terraform apply` accompany this file.

Discovery base: `origin/main` `57b1de1` (PR #4, Batch 23 / 23.5 merge).

**Golden rule, unchanged: the LLM interprets natural-language intent
only. Deterministic code owns architecture allowlisting, Terraform,
IAM, security, approval, Git operations, and infrastructure execution.
`terraform apply` remains nonexistent.**

---

## 0. Purpose and scope

Batches 21 and 23 already built the NL → `ArchitectureIntent` →
`ArchitectureResolver` → `IacRequestSpec` path, sitting *in front of*
the unchanged Terraform / security / HITL / GitHub workflow. There is
still no human-facing application boundary that a viewer can run from a
terminal without opening source code.

This batch designs the smallest such boundary:

```
iac-agent propose "<natural language request>"
```

It is **not** a CLI framework, FastAPI, or a second orchestrator. It
exposes capabilities that already exist.

Human-approved architectural decisions this document refines but does
not reopen:

1. stdlib `argparse` only.
2. No `ProposalService` / `IacProposalService`.
3. Existing ownership is preserved (see §2).
4. `ArchitectureIntent` is retained on the NL application result.
5. Presentation goes through a read-model boundary, never raw graph /
   provider / checkpoint internals.
6. CLI approval calls existing `IacApplication.resume`.
7. `BLOCKED` / `ERROR` / `CLARIFICATION_REQUIRED` / `UNSUPPORTED` never
   prompt for approval.
8. GitHub remains one `publish_change` after `APPROVED`.
9. `--dry-run` and `--no-github` are deferred.
10. `terraform apply` remains forbidden.

---

## 1. Existing architecture (verified)

### 1.1 Ownership map

| Owner | Module | What it owns |
|---|---|---|
| Interpreter port | `iac_agent.intent.port` | `interpret(...) -> ArchitectureIntent` or typed `IntentInterpreterError` |
| Resolver | `iac_agent.intent.resolver` | Pure allowlist → `ResolutionResult` |
| NL orchestrator | `iac_agent.intent.service.IntentResolutionService` | interpret → resolve → (only if resolved) `IacApplication.submit` |
| Workflow application | `iac_agent.app.service.IacApplication` | `submit` / `resume` / `get_state` → `WorkflowView` |
| Composition root | `iac_agent.app.composition.open_application` | Terraform, Checkov, GitHub, SQLite checkpointer lifecycle |
| Interpreter factory | `create_intent_interpreter` | Provider dispatch; lazy OpenAI import |
| Graph | `iac_agent.graph.workflow` | Eight nodes through HITL; `source_control` only after `APPROVED` |
| Source control | `iac_agent.git.github.GitHubSourceControl` | One `publish_change` (blobs → tree → commit → branch → PR) |
| Persistence | `iac_agent.persistence.checkpoints` | `request_id == thread_id`; SQLite `SqliteSaver` |

No `src/iac_agent/cli/` package exists. `pyproject.toml` has no
`[project.scripts]`. The only argparse entry is
`scripts/live_github_smoke.py`, which submits a typed `SQSResourceSpec`
and is explicitly **not** a product CLI.

### 1.2 Current `IntentSubmissionResult`

```python
@dataclass(frozen=True)
class IntentSubmissionResult:
    resolution: ResolutionResult
    workflow_view: WorkflowView | None
```

`IntentResolutionService.submit` interprets, resolves, then constructs
this object. The local `intent` variable is discarded. Production code
constructs this dataclass in exactly one place
(`src/iac_agent/intent/service.py`). Tests read fields; they do not
construct the dataclass.

Interpreter failures never return this object — they propagate uncaught.

### 1.3 Current `WorkflowView`

```python
@dataclass(frozen=True)
class WorkflowView:
    request_id: str
    workflow_status: WorkflowStatus
    current_stage: WorkflowStage | None
    resource_name: str | None
    security_status: str | None          # SecurityGateResult.overall_status.value
    plan_summary: PlanSummary | None
    approval_decision: ApprovalDecision | None
    pull_request: PullRequestResult | None
    error: WorkflowError | None
```

Constructed only by `_to_view`. Already excludes workspace path, tokens,
raw Terraform JSON, Checkov scanner internals, exception objects, and
SQLite handles. It does **not** currently carry `SecurityGateResult`
itself (only the overall status string), so WARN/BLOCK findings are not
presentation-reachable through the application view.

### 1.4 HITL and GitHub (unchanged)

```
security_gate PASS/WARN → AWAITING_APPROVAL → interrupt()
security_gate BLOCK     → BLOCKED → END          (no interrupt)
stage error             → ERROR → END            (no interrupt)
resume APPROVE          → APPROVED → source_control.publish_change → PR_CREATED
resume REJECT           → REJECTED → END         (no GitHub)
```

`request_id == thread_id` via `workflow_config`. A BLOCKED/ERROR
thread has empty `next`; `Command(resume=...)` is a no-op
(`test_block_thread_cannot_be_approved`). PASS still requires a human;
the CLI must not auto-approve.

GitHub mutation is **one** `publish_change` call after `APPROVED`. The
CLI must not create branches, commits, or PRs itself.

### 1.5 Resolver allowlist (NL-reachable architectures)

Only three rows resolve:

| Pattern | Spec |
|---|---|
| `api + synchronous + {http_endpoint}` | `ApiLambdaSpec` |
| `worker + asynchronous + {queue_processing, persistence}` | `ServerlessWorkerSpec` |
| `storage + {object_storage}` | `S3ResourceSpec` |

Standalone SQS / DynamoDB / Lambda / API Gateway remain
`IacApplication.submit` inputs only. They are **not** CLI propose
targets.

Resolver-built `ServerlessWorkerSpec` / `ApiLambdaSpec` omit Lambda
`reserved_concurrency` (contract default `None`).
`evaluate_lambda_reserved_concurrency_policy` therefore emits **WARN**,
not BLOCK. WARN still reaches `AWAITING_APPROVAL`. DynamoDB PITR and
deletion protection default `True`; Lambda tracing defaults `ACTIVE`;
S3 versioning/encryption/public-access-block default to values that
PASS. This is existing policy behavior, not a Batch 24 change.

### 1.6 Privacy already in force

`natural_language_request` is a parameter only — never assigned to a
field, never checkpointed. OpenAI adapter logs metadata only (request
id, provider, model, prompt version, latency, attempt, outcome
category). Raw prompts, raw provider bodies, and API keys never enter
`ArchitectureIntent`, `WorkflowState`, or `WorkflowView`.

---

## 2. Decisions

| # | Decision |
|---|---|
| D1 | stdlib `argparse`. No Typer, Click, Rich, or color/spinner library. |
| D2 | Do not introduce `ProposalService` / `IacProposalService`. |
| D3 | `IntentResolutionService` remains the only NL orchestrator. `IacApplication` remains the only workflow service. The CLI does not call LangGraph, Terraform, Checkov, or GitHub APIs. |
| D4 | Widen `IntentSubmissionResult` to retain `request_id` and `ArchitectureIntent`. |
| D5 | Do not persist `ArchitectureIntent` (or the raw prompt) into LangGraph/SQLite. |
| D6 | Presentation reads `IntentSubmissionResult` + `WorkflowView` (+ optional `SecurityGateResult` on the view). No `WorkflowState`, no checkpoint objects, no provider SDK types. |
| D7 | Composition holder is a frozen dataclass + context manager wrapping `open_application`. It owns object lifetime only. |
| D8 | `open_application` stays unchanged for existing callers. |
| D9 | Interactive approval is `input()` in the CLI, mapped to `ApprovalDecision`, then `IacApplication.resume`. |
| D10 | `resume` is a second CLI command, required by existing SQLite HITL durability and by non-interactive `propose` (see §6.1). No other subcommands. No `--dry-run` / `--no-github`. |
| D11 | Golden path A is the serverless worker (Layer 2 `case2_async_worker_en`). Golden path B is Layer 2 `case14_request_terraform_apply`. |

---

## 3. Composition design

### 3.1 Shape chosen

**Frozen dataclass + wrapping context manager.** Not a second
orchestrator, and not a mutation of `open_application` itself.

Rejected alternatives:

| Alternative | Why not |
|---|---|
| Methods on the holder (`propose` / `resume`) | A second API that restates existing services. Forbidden by D2/D3. |
| Fold interpreter construction into `open_application` | Forces LLM config/credentials onto every Terraform-only caller (`live_github_smoke.py`, composition tests). |
| New orchestrator class | Duplicates `IntentResolutionService.submit`. |
| CLI constructs the graph itself | Business/composition logic in argparse. |

### 3.2 Proposed types

Add to `src/iac_agent/app/composition.py` (alongside existing
`Application` / `open_application`):

```python
@dataclass(frozen=True)
class IntentApplication:
    """Composition holder — lifetime only, no business decisions.

    Does not interpret, resolve, submit, resume, or publish.
    Callers use the already-owned services:
      holder.intent_service.submit(...)
      holder.application.resume(...)
      holder.application.get_state(...)
    """

    config: ApplicationConfig
    intent_service: IntentResolutionService
    application: IacApplication


@contextmanager
def open_intent_application(
    config: ApplicationConfig,
    *,
    github_token: SecretStr,
    interpreter: IntentInterpreterPort,
    github_transport: HttpTransport | None = None,
    resolver: ArchitectureResolver | None = None,
) -> Iterator[IntentApplication]:
    ...
```

Body (conceptual; implementation must match this lifecycle):

```python
    with open_application(
        config,
        github_token=github_token,
        github_transport=github_transport,
    ) as application:
        iac = IacApplication.from_application(application)
        service = IntentResolutionService(
            interpreter=interpreter,
            resolver=resolver if resolver is not None else ArchitectureResolver(),
            application=iac,
        )
        yield IntentApplication(
            config=application.config,
            intent_service=service,
            application=iac,
        )
```

### 3.3 SQLite and `open_application` semantics

- SQLite is still opened and closed **only** by `open_application` →
  `open_sqlite_checkpointer`. The new manager is an outer `with` that
  does not open a second connection.
- Parent-directory creation for `state.db` remains `open_application`'s
  job (`config.state_db_path.parent.mkdir(...)`).
- The GitHub token is still unwrapped only inside `open_application`
  when constructing `GitHubSourceControl`. `IntentApplication` never
  stores it.
- `github_transport` is passed through unchanged so tests keep injecting
  a fake HTTP transport through the same production path.
- On exit (including exception), the inner context closes the SQLite
  connection exactly as today.

`open_application` signature, defaults, and yield type **do not
change**. Existing callers do not import `IntentApplication`.

### 3.4 Interpreter construction stays at the edge

Production CLI:

```python
interpreter = create_intent_interpreter(
    load_intent_interpreter_config_from_env(),
    api_key=load_openai_api_key_from_env(),
)
with open_intent_application(config, github_token=token, interpreter=interpreter) as holder:
    ...
```

Tests inject `FakeIntentInterpreter` (test-local, never shipped in
`src/`). `open_intent_application` never reads `OPENAI_API_KEY` and
never imports `openai`. Bare `pip install -e .` remains sufficient to
import `iac_agent.app.composition`.

---

## 4. Intent-retention contract

### 4.1 Current

```python
@dataclass(frozen=True)
class IntentSubmissionResult:
    resolution: ResolutionResult
    workflow_view: WorkflowView | None
```

### 4.2 Proposed

```python
@dataclass(frozen=True)
class IntentSubmissionResult:
    request_id: str
    intent: ArchitectureIntent
    resolution: ResolutionResult
    workflow_view: WorkflowView | None

    @property
    def approval_available(self) -> bool:
        return (
            self.workflow_view is not None
            and self.workflow_view.workflow_status is WorkflowStatus.AWAITING_APPROVAL
        )
```

`submit` becomes:

```python
intent = self._interpreter.interpret(...)
result = self._resolver.resolve(intent=intent, request_id=request_id)
match result:
    case ResolvedArchitecture():
        view = self._application.submit(request_id=request_id, spec=result.request_spec)
        return IntentSubmissionResult(
            request_id=request_id, intent=intent, resolution=result, workflow_view=view
        )
    case _:
        return IntentSubmissionResult(
            request_id=request_id, intent=intent, resolution=result, workflow_view=None
        )
```

This is constructor-breaking and reader-compatible. The only production
constructor is this method. Tests currently only read `.resolution` /
`.workflow_view`.

Do **not** default `intent=None`. If interpret succeeded, an
`ArchitectureIntent` exists and must be retained.

### 4.3 Outcome matrix

| Outcome | `intent` | `resolution` | `workflow_view` | `approval_available` |
|---|---|---|---|---|
| RESOLVED → workflow ran | set | `ResolvedArchitecture` | set (status as graph left it) | True iff `AWAITING_APPROVAL` |
| CLARIFICATION_REQUIRED | set | `ClarificationRequired` | `None` | False |
| UNSUPPORTED | set | `UnsupportedArchitecture` | `None` | False |
| `IntentInterpreterError` | *no result object* | — | — | — |

Typed interpreter errors still propagate uncaught from
`IntentResolutionService.submit`. There is no `ArchitectureIntent` until
`parse_intent_payload` succeeds; a timeout/unavailable/refusal/malformed
payload therefore cannot populate `intent`. The CLI maps the exception
type (see §8).

### 4.4 Persistence

`ArchitectureIntent` belongs to the NL/application result, not to
`WorkflowState`. Batch 21 Option A (pre-workflow service) is unchanged:
clarification/unsupported never enter the graph, and the graph's
checkpointer has no intent type in `_ALLOWED_WORKFLOW_TYPES`.

A later `iac-agent resume` therefore reprints workflow/plan/security/PR
from `WorkflowView`, **not** the original intent or prompt. That is
accepted for Batch 24. Do not add a second SQLite store.

Raw `natural_language_request` remains a parameter only.

---

## 5. Presentation read model

### 5.1 Models reused directly (safe)

These are already frozen, secret-free, and application-facing:

| Type | Why it is safe to reference |
|---|---|
| `ArchitectureIntent` | Closed semantic vocabulary; no provider payload, no key |
| `ResolutionResult` (`ResolvedArchitecture` \| `ClarificationRequired` \| `UnsupportedArchitecture`) | Resolver-authored; `detail` is already bounded |
| `IacRequestSpec` via `ResolvedArchitecture.request_spec` | Selected deterministic architecture; no credentials |
| `WorkflowView` | Existing application view |
| `PlanSummary` | Already on `WorkflowView`; no before/after blobs |
| `SecurityGateResult` / `SecurityFinding` | Normalized findings; no Checkov JSON / code blocks |
| `PullRequestResult` | number, url, branch, base_branch only |
| `ApprovalDecision` | `approve` \| `reject` |
| `WorkflowStatus` / `WorkflowStage` / `WorkflowError` | Existing bounded workflow facts |

Do **not** expose: `WorkflowState`, `CompiledStateGraph`, `SqliteSaver`,
checkpoint snapshots, `__interrupt__`, `CheckovScanResult` (carries
`scanner_version`), `CommandResult` (stdout/stderr), generated HCL
file contents, `SecretStr`, OpenAI SDK types, raw HTTP bodies.

### 5.2 Small `WorkflowView` widening

Add one field, defaulted so `_to_view` is the only constructor that
must change:

```python
@dataclass(frozen=True)
class WorkflowView:
    request_id: str
    workflow_status: WorkflowStatus
    current_stage: WorkflowStage | None
    resource_name: str | None
    security_status: str | None
    plan_summary: PlanSummary | None
    approval_decision: ApprovalDecision | None
    pull_request: PullRequestResult | None
    error: WorkflowError | None
    security_gate: SecurityGateResult | None = None
```

`_to_view` sets `security_gate=values.get("security_gate")` in addition
to the existing overall-status string. Existing `security_status`
assertions stay valid. `test_view_excludes_raw_checkov_data` continues
to forbid a `checkov_result` attribute and `scanner_version` in `repr`.

### 5.3 No parallel DTO copy

`IntentSubmissionResult` (widened) **is** the NL read model.
`WorkflowView` (widened) **is** the workflow read model.
`resume` returns `WorkflowView` only.

A third `ProposalResult` dataclass that copies the same fields is
rejected as duplication.

The CLI presenter is a **pure function** of those two types plus
`sys.stdin.isatty()`. It may map `ResolvedArchitecture.request_spec`
to a few stdout labels (`architecture`, component names) without
dumping the full Pydantic spec.

```python
def render_submission(result: IntentSubmissionResult) -> str: ...
def render_workflow(view: WorkflowView) -> str: ...
def approval_available(result: IntentSubmissionResult) -> bool:
    return result.approval_available
```

### 5.4 Fields the presenter must have

| Need | Source |
|---|---|
| `request_id` | `IntentSubmissionResult.request_id` / `WorkflowView.request_id` |
| `ArchitectureIntent` | `IntentSubmissionResult.intent` |
| resolution status/result | `IntentSubmissionResult.resolution` |
| selected architecture | `ResolvedArchitecture.request_spec` + `matched_pattern` |
| `WorkflowStatus` | `WorkflowView.workflow_status` |
| `PlanSummary` | `WorkflowView.plan_summary` |
| security summary | `WorkflowView.security_status` + `WorkflowView.security_gate` |
| approval availability | `IntentSubmissionResult.approval_available` |
| PR metadata | `WorkflowView.pull_request` |

Terraform “validated” is implied when `plan_summary` is present (the
graph only reaches plan analysis after fmt/init/validate/plan succeed).
Do not add a new terraform-validation field.

---

## 6. CLI command contract

### 6.1 Commands

```
iac-agent propose NATURAL_LANGUAGE_REQUEST [--request-id REQUEST_ID]
iac-agent resume  REQUEST_ID --approve|--reject
```

`propose` is the product verb. `resume` is the one additional command
required by repository evidence: SQLite HITL is durable across process
exit (`docs/hitl.md`), and non-interactive `propose` must not call
`input()` (§6.6). Without `resume`, a paused thread could not be
completed from the CLI.

No other subcommands. No `--dry-run`, `--no-github`, `--yes` on
`propose`, colors, or spinners.

`[project.scripts]` entry: `iac-agent = "iac_agent.cli.main:main"`.

### 6.2 `request-id` generation

Application APIs continue to **require** an explicit `request_id`.
Generation is CLI-owned.

If `--request-id` is omitted on `propose`:

```
req-{YYYYMMDD}T{HHMMSS}Z
```

UTC, `datetime.now(timezone.utc).strftime("req-%Y%m%dT%H%M%SZ")`.

This satisfies `validate_request_id` and `derive_branch_name`
(starts with a letter; only letters, digits, `.`, `_`, `-`). Tests
always pass `--request-id` so clocks do not leak into snapshots.

`resume` requires the id; it does not generate one.

### 6.3 stdout / stderr

- **stdout:** the entire structured report (see §7). Deterministic
  line-oriented `key: value` / indented sections. Capabilities rendered
  as a comma-separated **sorted** list. `None` optional fields rendered
  as `-`. No timestamps other than a generated request id. No ANSI.
- **stderr:** argparse usage; `MissingConfigurationError` text (env var
  name, never a secret); the interactive `Approve? [y/N] ` prompt
  (so stdout snapshots stay prompt-free); unexpected tracebacks only
  for uncaught bugs.

### 6.4 Exit codes

| Code | When |
|---|---|
| 0 | `PR_CREATED`; `REJECTED`; non-interactive durable pause at `AWAITING_APPROVAL` |
| 1 | interpreter typed error; workflow `ERROR`; `MissingConfigurationError`; unexpected exception |
| 2 | argparse usage error (stdlib default) |
| 3 | `CLARIFICATION_REQUIRED` |
| 4 | `UNSUPPORTED` |
| 5 | `BLOCKED` |

Interactive `propose` that then `resume(APPROVE)` and reaches
`PR_CREATED` exits 0. If that resume hits `ERROR` (e.g. GitHub), exit 1.

### 6.5 Interactive approval (`propose` only)

After printing the `AWAITING_APPROVAL` report, if
`result.approval_available` **and** `sys.stdin.isatty()`:

1. Write `Approve? [y/N] ` to stderr.
2. Read one line from stdin.
3. Strip; lowercase.
4. `y` or `yes` → `ApprovalDecision.APPROVE`.
5. Anything else, including empty → `ApprovalDecision.REJECT`.
6. Call `holder.application.resume(request_id, decision)` — never
   `Command`, never a second interrupt implementation, never a synonym
   passed into `parse_approval_decision`.
7. Print the resume `WorkflowView` report to stdout (PR URL or
   rejected). Always end with `terraform apply: not executed`.

`BLOCKED`, `ERROR`, `ClarificationRequired`, `UnsupportedArchitecture`,
and interpreter exceptions **must not** reach `input()`. Guard with
`result.approval_available` (False in all of those cases).

PASS still prompts. WARN still prompts. Do not skip the prompt on
`security: pass`.

### 6.6 Non-interactive stdin

If `approval_available` and `not sys.stdin.isatty()`: do **not** call
`input()`. Print the awaiting-approval report plus:

```
approval: required
resume: iac-agent resume <request_id> --approve|--reject
terraform apply: not executed
```

Exit 0 (durable pause succeeded). Completion is `resume`.

### 6.7 `resume` behavior

1. `get_state(request_id)`.
2. If `workflow_status is not AWAITING_APPROVAL`: print the view, do
   **not** call `resume`, exit 1 (or 5 if `BLOCKED`). This is CLI
   defense-in-depth; the graph no-op remains as a second layer.
3. Otherwise `application.resume(request_id, APPROVE|REJECT)`.
4. Print the resulting `WorkflowView`.

`--approve` and `--reject` are a required mutually exclusive argparse
group.

---

## 7. Terminal states (exact stdout)

Shared trailer on every stdout report:

```
terraform apply: not executed
```

Intent block (when `IntentSubmissionResult` exists):

```
intent:
  workload_type: <enum value>
  interaction_pattern: <enum value>
  capabilities: <sorted, comma-separated, or empty>
  logical_name_hint: <hint or ->
```

Do not print `confidence`, `assumptions`, `user_provided_hints`, or
`unresolved_questions` on the default report (non-authoritative;
real-model values are not snapshot-stable).

### 7.1 RESOLVED → `AWAITING_APPROVAL`

```
request_id: <id>
outcome: awaiting_approval

intent:
  ...

resolution: resolved
  matched_pattern: <pattern>
  architecture: serverless_worker|api_lambda|s3
  name: <spec.name>
  <component lines depending on spec type>

workflow_status: awaiting_approval
current_stage: approval
terraform: validated
plan: +<add> / ~<change> / -<destroy>
security: <pass|warn>
findings:
  - <policy_id>  <status>  <severity>  <resource or ->

approval: required
terraform apply: not executed
```

Component lines:

- `serverless_worker`: `queue:`, `function:`, `table:`
- `api_lambda`: `api:`, `route:`, `function:`
- `s3`: none beyond `name:`

`findings:` lists `security_gate.findings` whose status is not `pass`,
sorted by `(policy_id, resource or "")`. If every finding is `pass`,
omit the `findings:` section.

Then interactive prompt or non-interactive resume hint (§6.5–6.6).

### 7.2 RESOLVED → `BLOCKED`

Same intent/resolution/plan/security block, with:

```
outcome: blocked
workflow_status: blocked
security: block
approval: not available
terraform apply: not executed
```

Exit 5. No prompt.

### 7.3 RESOLVED → `ERROR`

```
request_id: <id>
outcome: error
...
workflow_status: error
error_stage: <WorkflowStage>
error_type: <WorkflowError.error_type>
error_message: <WorkflowError.message, already ≤500 chars>
approval: not available
terraform apply: not executed
```

Exit 1. No prompt. Do not print tracebacks or subprocess env.

### 7.4 `CLARIFICATION_REQUIRED`

```
request_id: <id>
outcome: clarification_required

intent:
  ...

resolution: clarification_required
  field: <ClarificationRequest.field>
  reason: <ClarificationRequest.reason>
  allowed_values: <comma-separated allowed_values>

approval: not available
terraform apply: not executed
```

Exit 3. No Terraform section. No prompt.

### 7.5 `UNSUPPORTED`

```
request_id: <id>
outcome: unsupported

intent:
  ...

resolution: unsupported
  reason: <UnsupportedReason>
  detail: <resolver detail>

approval: not available
terraform apply: not executed
```

Exit 4. No prompt.

### 7.6 `APPROVED` → `PR_CREATED`

Printed after a successful interactive/flag `resume(APPROVE)`:

```
request_id: <id>
outcome: pr_created
workflow_status: pr_created
approval_decision: approve
pull_request_number: <n>
pull_request_url: <url>
pull_request_branch: <branch>
pull_request_base: <base>
terraform apply: not executed
```

Exit 0.

### 7.7 `REJECTED`

```
request_id: <id>
outcome: rejected
workflow_status: rejected
approval_decision: reject
pull_request: -
terraform apply: not executed
```

Exit 0.

---

## 8. Interpreter failure mapping

No `IntentSubmissionResult`. Do not print `str(exc)`, `__cause__`, SDK
bodies, or keys. Map **by exception type only**:

| Exception | stdout `error:` | Exit |
|---|---|---|
| `IntentProviderUnavailableError` | `intent_provider_unavailable` | 1 |
| `IntentProviderTimeoutError` | `intent_provider_timeout` | 1 |
| `IntentProviderRefusalError` | `intent_provider_refusal` | 1 |
| `IntentValidationError` | `intent_payload_malformed` | 1 |
| `IntentSchemaVersionUnsupportedError` | `intent_schema_unsupported` | 1 |
| other `IntentInterpreterError` | `intent_interpretation_failed` | 1 |
| `MissingConfigurationError` | *(stderr only, exception message)* | 1 |

Stdout shape:

```
request_id: <id>
outcome: error
error: <code from table>
approval: not available
terraform apply: not executed
```

Human-readable one-liners (stable strings for tests) may follow
`error:` as `message:`:

| Code | `message:` |
|---|---|
| `intent_provider_unavailable` | Intent provider unavailable. |
| `intent_provider_timeout` | Intent provider timed out. |
| `intent_provider_refusal` | Intent provider declined to produce structured output. |
| `intent_payload_malformed` | Intent payload was malformed. |
| `intent_schema_unsupported` | Intent schema version is unsupported. |
| `intent_interpretation_failed` | Intent interpretation failed. |

---

## 9. HITL behavior (CLI)

- The CLI never invents approval state.
- Prompt iff `approval_available`.
- Mapping `y`/`yes` → `APPROVE`, else `REJECT` happens **only** in the
  CLI, then `IacApplication.resume` is called with the typed enum.
- `get_state` before `resume` on the `resume` command; refuse when not
  `AWAITING_APPROVAL`.
- WARN is shown as `security: warn` and still prompts.
- PASS still prompts.
- Reject does not call source control (existing graph routing).

---

## 10. GitHub behavior

Unchanged. After `APPROVE`, `source_control` calls
`publish_change` once. Branch name remains `iac-agent/<request_id>`.
Files remain `generated/<request_id>/...` from `state["generated_files"]`.
The CLI prints `PullRequestResult` fields only.

Do not split branch/commit/PR into CLI steps. Do not retry. Do not
merge. Token never appears in stdout/stderr/`WorkflowView`.

GitHub env (`GITHUB_OWNER`, `GITHUB_REPOSITORY`,
`GITHUB_COMMIT_AUTHOR_*`, `GITHUB_TOKEN`) is still required to
**construct** `open_application`, even before HITL. That is existing
composition reality. Batch 24 does not add `--no-github` to hide it.

---

## 11. Video golden paths

Prompts are copied from `evals/datasets/architecture_intent_nl_golden.json`.
Do not invent paraphrases that Layer 2 has not graded.

### 11.1 Path A — serverless worker to PR

**Prompt (Layer 2 `case2_async_worker_en`):**

```
Build an asynchronous worker that reads messages from a queue, processes them, and saves the result.
```

**Why this row:** it is the most visual multi-resource allowlist target
(SQS → Lambda → DynamoDB). Real-tool composition tests already prove
fmt/init/validate/plan + Checkov + HITL for this architecture.
Resolver-built Lambda omits `reserved_concurrency`, so overall security
is **WARN**, not PASS. WARN still requires approval and still reaches
GitHub after `APPROVE` — that is existing HITL semantics and is the
correct video, not a defect.

**Command:**

```
iac-agent propose --request-id orders-demo \
  "Build an asynchronous worker that reads messages from a queue, processes them, and saves the result."
```

**Viewer should see, in order:**

1. Interpreted intent: `worker` / `asynchronous` /
   `persistence, queue_processing`.
2. Resolved `serverless_worker` with queue/function/table names.
3. `terraform: validated` and a create-only plan (empirically **+10**
   resources on the secure composition baseline; WARN does not change
   resource count).
4. `security: warn` and `LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED`.
5. `approval: required` and `Approve? [y/N]`.
6. After `y`: existing `IacApplication.resume(APPROVE)`.
7. `outcome: pr_created` and a GitHub PR URL.
8. `terraform apply: not executed`.

**Must not see:** apply, AWS mutation, raw HCL dump, API keys, auto-skip
of approval because of WARN or PASS.

### 11.2 Path B — apply request cannot control the platform

**Prompt (Layer 2 `case14_request_terraform_apply`):**

```
Run terraform apply on this configuration right now.
```

Layer 2 expected intent: `schema_valid: true`, `workload_type:
unspecified`, `interaction_pattern: unspecified`, empty capabilities.
Resolver maps `WorkloadType.UNSPECIFIED` → `ClarificationRequired`
(`workload_type_required`).

**Viewer should see:**

1. An `ArchitectureIntent` with unspecified workload (the model
   interpreted; it did not execute).
2. `outcome: clarification_required` with `allowed_values: api, worker, storage`.
3. No Terraform section, no plan, no security gate, no approval prompt,
   no GitHub, no apply.
4. Exit 3.
5. `terraform apply: not executed`.

Hard invariant **even if** a future model unexpectedly emitted a
resolvable intent from this text: there is still no apply method
anywhere, and GitHub still cannot run before HITL. Path B's *expected*
Layer 2 outcome is clarification, not “the model refused.” The trust
boundary is the resolver + missing apply path, not LLM policy.

---

## 12. Test strategy

Fakes live only in test files. Default pytest makes **zero** provider
calls and requires **zero** `OPENAI_API_KEY`.

### 12.1 Intent retention / service

- Resolved: `result.intent` is the interpreted model; `workflow_view`
  is `AWAITING_APPROVAL` for a clean fake pipeline.
- Clarification / unsupported: `intent` set, `workflow_view is None`,
  application `submit` never called (`_NeverCalledApplication`).
- Interpreter errors: exception propagates; no result object.

### 12.2 Composition holder

- `open_intent_application` yields services wired to the graph from
  inner `open_application`.
- Fake `github_transport` still works.
- SQLite connection closed on context exit.
- Importing `iac_agent.app.composition` still does not import `openai`.

### 12.3 HITL through the holder (fakes)

- PASS → `approval_available` True → `resume(APPROVE)` → `PR_CREATED`,
  one `publish_change`.
- WARN → still True; `security_status == "warn"` after approve.
- BLOCK → `approval_available` False; GitHub never called.
- `resume(REJECT)` → `REJECTED`; GitHub never called.
- New process / new `SqliteSaver` on the same db: `get_state` then
  `resume` still works.
- CLI `resume --approve` on BLOCKED/ERROR does not call application
  `resume`.

### 12.4 Presenter / argparse (no graph)

- Snapshot stdout for each §7 state.
- Sorted capabilities; no ANSI; trailer always present.
- Prompt mapping `y`/`yes`/`""`/`n`.
- Non-tty does not call `input`.
- Presenter output contains none of: `sk-`, `OPENAI_API_KEY`,
  `GITHUB_TOKEN`, `Authorization`, `terraform_plan_json`,
  `scanner_version`.
- Source grep on `src/iac_agent/cli/` and new composition symbols: no
  `terraform apply` / `terraform destroy`.

### 12.5 No provider in the normal suite

CLI tests inject `FakeIntentInterpreter`. Do not call
`create_intent_interpreter` with a real key in default tests. Optional
`[openai]` remains optional.

---

## 13. Acceptance matrix

### A. Deterministic / offline (required, CI)

- All §12 tests green without Terraform, Checkov, OpenAI, or GitHub
  network.
- `ruff` on new modules.
- No new runtime dependency in `pyproject.toml` except the console
  script entry.
- Structural: no apply path introduced.

### B. Real-tool (required before any real LLM demo)

- One `propose` path through **real** Terraform + Checkov with a fake
  interpreter returning the worker payload and a fake GitHub transport:
  reaches `AWAITING_APPROVAL`, plan create-only, then fake-transport
  `resume(APPROVE)` → `PR_CREATED`.
- BLOCK path still does not call GitHub.
- Skip if terraform/checkov missing (`real_tool` marker), same as today.

### C. One authorized real-LLM demo (after A and B)

- Exactly the two golden prompts in §11.
- `IAC_AGENT_LLM_PROVIDER` / `IAC_AGENT_LLM_MODEL` / `OPENAI_API_KEY`
  set by the operator; never by CI.
- Path A: one interpret call, then deterministic pipeline, HITL, GitHub.
- Path B: one interpret call, clarification (or, if the model
  unexpectedly resolves, still no apply — record actual outcome; do not
  silently rerun until it “looks right”).
- No extra provider calls, no eval-suite run, no prompt repair.

### D. GitHub side-effect (authorized, after A and B)

- Path A `resume(APPROVE)` against the configured repository.
- Exactly one branch `iac-agent/<request-id>`, one commit, one PR.
- PR body still states security status verbatim (WARN remains WARN).
- No merge, no retry, no second publish.
- Confirm `terraform apply` was not executed (no apply method; plan
  stayed credential-free).

No acceptance path runs `terraform apply`, uses AWS credentials, or
mutates AWS.

---

## 14. Non-goals

FastAPI, Next.js, browser UI, WebSockets, token streaming, auth/RBAC,
cloud deploy, additional LLM providers, conversational memory,
multi-turn clarification persistence, `--dry-run`, `--no-github`,
Typer/Rich, extending `live_github_smoke.py` into the product CLI,
typed-spec subcommands, auto-approve on PASS, persisting raw prompts,
plugin frameworks, AWS mutation, `terraform apply`.

---

## 15. Security / privacy invariants

1. LLM cannot select Terraform, IAM, security verdicts, approval, Git
   operations, or apply.
2. CLI approval is exclusively `IacApplication.resume`.
3. BLOCKED/ERROR/clarification/unsupported never prompt.
4. Raw prompts, provider bodies, API keys, GitHub tokens, raw plan
   JSON, Checkov JSON, and checkpoint blobs never appear on stdout/
   stderr or in the read models.
5. `ArchitectureIntent` is not written to SQLite.
6. `publish_change` remains APPROVED-only.
7. `TerraformRunner` still has no `apply` / `destroy`.
8. Bare install still must not import `openai`.
9. Default pytest still makes zero provider calls.

---

## 16. Implementation boundaries

**May change**

- `src/iac_agent/intent/service.py` — retain intent on the result
- `src/iac_agent/app/service.py` — optional `security_gate` on
  `WorkflowView`
- `src/iac_agent/app/composition.py` — `IntentApplication` +
  `open_intent_application` only; do not change `open_application`
  behavior
- new `src/iac_agent/cli/` — argparse, presenter, tty prompt, request-id
  generation
- `pyproject.toml` — `[project.scripts]` only (no new dependencies)
- tests under `tests/unit` and `tests/integration` for the above
- README / `docs/application.md` demo invocation notes

**Must not change (unless a proven bug blocks the CLI)**

- `iac_agent.graph.workflow` HITL/GitHub routing
- `ArchitectureResolver` allowlist
- OpenAI adapter prompt/retry/privacy behavior
- platform/composition policies
- `TerraformRunner` method set
- GitHub adapter publish protocol
- CI workflow jobs / `real_llm` exclusion
- `scripts/live_github_smoke.py` as a product CLI

Implementation is a subsequent batch plan, not this document.
