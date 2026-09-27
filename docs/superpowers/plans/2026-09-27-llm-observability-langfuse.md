# LLM observability implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a default-off observability port that records allowlisted intent and workflow facts, and an optional Langfuse adapter that never sits on the Terraform correctness path.

**Architecture:** `generate_request_id` gains a 12-hex suffix so one UTC second cannot alias a checkpoint thread. A projection builds small telemetry models from `ArchitectureIntent`, `ResolutionResult`, and `WorkflowView`. `FailOpenObservability` wraps every sink, including `NoOpObservability`. `IntentResolutionService` and `IacApplication` call the port. Graph nodes do not. The Langfuse SDK is imported only inside the optional adapter factory.

**Tech Stack:** Python 3.12, stdlib `uuid`, existing Pydantic/LangGraph application, optional `langfuse` extra (not installed by CI).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-27-llm-observability-langfuse-design.md`, including section 29.
- Do not change `ArchitectureResolver.resolve` behavior, golden datasets, Checkov profiles, platform-policy decisions, Terraform modules, or Batch 25 `bootstrap/aws-oidc` work.
- Do not reopen `docs/adr/2026-09-27-registry-catalog-deferred.md`.
- Do not edit `.github/workflows/ci.yml`. CI installs `.[dev,openai]` and runs `pytest -m "not real_tool and not real_llm"`. That suite must stay green with no Langfuse package and no network.
- Default observability is off. Missing keys, a missing extra, and `IAC_AGENT_OBSERVABILITY` unset all mean NoOp.
- No configuration flag may enable raw prompt or model-output capture.
- No graph-node instrumentation. No Terraform or Checkov timing spans.
- `get_state` emits nothing.
- Telemetry failure must not change a workflow result. Callers do not wrap port calls in `try`. The one exception is `IntentResolutionService.submit` catching `IntentInterpreterError`, emitting, and re-raising that same exception.
- Do not pass `WorkflowState`, `WorkflowView`, Terraform text, plan JSON, Checkov results, exceptions, environment mappings, or provider responses to the vendor adapter.
- Generated request id shape: `req-%Y%m%dT%H%M%SZ-` plus 12 lowercase hex digits. `--request-id` stays caller-supplied.
- Correlation key is the exact `request_id`. Do not store a second id in the checkpoint.
- Commits must not contain `Co-Authored-By`, `Generated-By`, Cursor, Claude, or Anthropic trailers. `git commit` in this environment injects a trailer. Use `git commit-tree` and `git reset --soft` as in the commit steps. Do not amend. Do not push.
- No `terraform apply` or `destroy`. No AWS, OpenAI, GitHub, or Langfuse calls.

## File map

| File | Responsibility |
|---|---|
| `src/iac_agent/cli/ids.py` | Generate a unique, path-safe, branch-safe request id |
| `src/iac_agent/observability/models.py` | Allowlisted frozen dataclasses. No denylisted fields exist |
| `src/iac_agent/observability/project.py` | Copy named fields off domain objects into those dataclasses |
| `src/iac_agent/observability/sanitize.py` | Regex scrub of strings that are already on a telemetry model |
| `src/iac_agent/observability/port.py` | `ObservabilityPort` protocol |
| `src/iac_agent/observability/noop.py` | `NoOpObservability` |
| `src/iac_agent/observability/failopen.py` | `FailOpenObservability` |
| `src/iac_agent/observability/adapters/langfuse.py` | Optional sink. Fake-client tests. SDK import is inside a function |
| `src/iac_agent/intent/adapters/openai.py` | Keep `last_call_metadata` from the dict `_log` already builds |
| `src/iac_agent/intent/service.py` | Emit generation and resolution |
| `src/iac_agent/app/service.py` | Emit submit, resume, and terminal. `get_state` stays silent |
| `src/iac_agent/app/config.py` | `ObservabilitySettings`, default off. Secrets stay out of `ApplicationConfig` |
| `src/iac_agent/app/composition.py` | One shared port for the intent service and `IacApplication` |
| `pyproject.toml` | Optional `langfuse` extra only. CI does not install it |
| `docs/observability.md` | Operator-facing boundary. No prompts, no live setup that creates a project |

Tests added or edited are listed on each task. Do not edit files under `evals/datasets/`.

---

### Task 1: Unique generated request ids

**Files:**
- Modify: `src/iac_agent/cli/ids.py`
- Test: `tests/unit/cli/test_ids.py`

**Interfaces:**
- Consumes: `validate_request_id`, `derive_branch_name` (unchanged)
- Produces: `generate_request_id(now: datetime | None = None, *, entropy: Callable[[], str] | None = None) -> str`

- [ ] **Step 1: Write the failing tests**

Replace the body of `tests/unit/cli/test_ids.py` with:

```python
"""UTC request-id generation with an injectable clock and entropy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from iac_agent.cli.ids import generate_request_id
from iac_agent.domain.source_control import derive_branch_name
from iac_agent.domain.workflow import validate_request_id
from iac_agent.intent.naming import fallback_base_name


def test_generate_request_id_uses_injected_clock_and_entropy():
    now = datetime(2026, 9, 18, 23, 22, 11, tzinfo=UTC)
    assert (
        generate_request_id(now=now, entropy=lambda: "a1b2c3d4e5f6")
        == "req-20260918T232211Z-a1b2c3d4e5f6"
    )


def test_same_second_with_different_entropy_does_not_collide():
    now = datetime(2026, 9, 18, 23, 22, 11, tzinfo=UTC)
    first = generate_request_id(now=now, entropy=lambda: "a1b2c3d4e5f6")
    second = generate_request_id(now=now, entropy=lambda: "ffffffffaaaa")
    assert first != second


def test_generated_id_is_branch_path_and_name_safe():
    value = generate_request_id(
        now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        entropy=lambda: "0123456789ab",
    )
    assert validate_request_id(value) == value
    assert derive_branch_name(value) == f"iac-agent/{value}"
    assert len(value) <= 40
    assert fallback_base_name(value) != fallback_base_name(
        "req-20260102T030405Z-ffffffffffff"
    )


def test_legacy_timestamp_id_still_validates_and_branches():
    legacy = "req-20260918T232211Z"
    assert validate_request_id(legacy) == legacy
    assert derive_branch_name(legacy) == "iac-agent/req-20260918T232211Z"


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError):
        generate_request_id(now=datetime(2026, 9, 18, 23, 22, 11))


def test_entropy_must_be_twelve_lowercase_hex_digits():
    now = datetime(2026, 9, 18, 23, 22, 11, tzinfo=UTC)
    with pytest.raises(ValueError):
        generate_request_id(now=now, entropy=lambda: "not-hex")
```

- [ ] **Step 2: Run the tests and confirm the new assertions fail**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_ids.py -v`

Expected: the equality `req-20260918T232211Z-a1b2c3d4e5f6` fails because the generator still returns `req-20260918T232211Z`.

- [ ] **Step 3: Implement**

Replace `src/iac_agent/cli/ids.py` with:

```python
"""UTC request-id generation with an injectable clock and entropy.

Application APIs still require an explicit request_id. Generation is
CLI-owned only. Caller-supplied --request-id is not passed through
this function.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

_SUFFIX_LENGTH = 12
_HEX_DIGITS = frozenset("0123456789abcdef")


def generate_request_id(
    now: datetime | None = None,
    *,
    entropy: Callable[[], str] | None = None,
) -> str:
    stamp = datetime.now(UTC) if now is None else now
    if stamp.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    source = uuid.uuid4().hex if entropy is None else entropy()
    suffix = source[:_SUFFIX_LENGTH]
    if len(suffix) != _SUFFIX_LENGTH or any(char not in _HEX_DIGITS for char in suffix):
        raise ValueError("entropy must provide 12 lowercase hex digits")
    return stamp.astimezone(UTC).strftime("req-%Y%m%dT%H%M%SZ-") + suffix
```

Do not change `src/iac_agent/cli/parser.py` or `src/iac_agent/cli/main.py`. `--request-id` already bypasses this function when the caller supplies one.

- [ ] **Step 4: Re-run**

Run: `.venv/bin/python -m pytest tests/unit/cli/test_ids.py -v`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/cli/ids.py tests/unit/cli/test_ids.py
TREE=$(git write-tree)
PARENT=$(git rev-parse HEAD)
NEW=$(git commit-tree "$TREE" -p "$PARENT" -m "$(cat <<'EOF'
fix(cli): make generated request ids unique within one second

EOF
)")
git reset --soft "$NEW"
git log -1 --format='%B' | grep -iE 'co-authored|generated-by|cursor|claude|anthropic' && exit 1 || echo NO_TRAILER
```

---

### Task 2: Allowlisted telemetry models and projection

**Files:**
- Create: `src/iac_agent/observability/__init__.py`
- Create: `src/iac_agent/observability/models.py`
- Create: `src/iac_agent/observability/project.py`
- Test: `tests/unit/observability/test_project.py`

**Interfaces:**
- Consumes: `ArchitectureIntent`, `ResolutionResult`, `WorkflowView`, `SecurityFinding`
- Produces: `GenerationTelemetry`, `ResolutionTelemetry`, `FindingTelemetry`, `WorkflowTelemetry`, `project_generation`, `project_resolution`, `project_workflow`

`__init__.py` is an empty module docstring file so the package imports. Do not re-export a vendor.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/observability/test_project.py`:

```python
from dataclasses import fields

import pytest

from iac_agent.app.service import WorkflowView
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecurityGateResult,
    SecuritySeverity,
)
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus
from iac_agent.intent.models import (
    ArchitectureIntent,
    AwsServiceHint,
    Capability,
    InteractionPattern,
    WorkloadType,
)
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.observability.models import GenerationTelemetry, WorkflowTelemetry
from iac_agent.observability.project import (
    project_generation,
    project_resolution,
    project_workflow,
)


_DENIED = {
    "natural_language_request",
    "assumptions",
    "unresolved_questions",
    "logical_name_hint",
    "confidence",
    "resource_name",
    "message",
    "resource",
    "address",
    "url",
    "branch",
    "generated_files",
    "traceback",
}


def test_telemetry_models_have_no_denylisted_fields():
    for model in (GenerationTelemetry, WorkflowTelemetry):
        names = {item.name for item in fields(model)}
        assert names.isdisjoint(_DENIED)


def test_project_generation_copies_tokens_only_when_present():
    full = project_generation(
        {
            "request_id": "req-001",
            "provider": "openai",
            "model": "gpt-test",
            "prompt_version": "4",
            "latency_ms": 12.5,
            "attempt_count": 1,
            "outcome_category": "ok",
            "input_tokens": 10,
            "output_tokens": 4,
            "natural_language_request": "build a bucket named secret-name",
            "raw_response": "should be dropped",
        }
    )
    assert full.input_tokens == 10
    assert full.output_tokens == 4
    assert "secret-name" not in repr(full)

    missing = project_generation(
        {
            "request_id": "req-001",
            "provider": "openai",
            "model": "gpt-test",
            "prompt_version": "4",
            "latency_ms": 1.0,
            "attempt_count": 2,
            "outcome_category": "timeout",
        }
    )
    assert missing.input_tokens is None
    assert missing.output_tokens is None


def test_project_resolution_keeps_enums_and_drops_names():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.CONTAINER_REGISTRY}),
        logical_name_hint="orders-registry",
        assumptions=("assume private",),
        unresolved_questions=("which region?",),
        user_provided_hints=(AwsServiceHint.ECR,),
    )
    resolution = ArchitectureResolver().resolve(intent=intent, request_id="req-001")
    event = project_resolution("req-001", intent, resolution)
    assert event.outcome == "resolved"
    assert event.resolved_type == "EcrResourceSpec"
    assert event.matched_pattern == "storage+container_registry"
    rendered = repr(event)
    assert "orders-registry" not in rendered
    assert "assume private" not in rendered
    assert "which region?" not in rendered


def test_project_workflow_keeps_counts_and_policy_ids_only():
    finding = SecurityFinding(
        policy_id="ECR_SCAN_ON_PUSH_RECOMMENDED",
        severity=SecuritySeverity.MEDIUM,
        status=PolicyStatus.WARN,
        resource="orders-registry",
        message="scan_on_push is false for orders-registry",
        source=FindingSource.PLATFORM_POLICY,
    )
    change = ResourceChange(
        address="module.ecr.aws_ecr_repository.this",
        actions=("create",),
        action=PlanAction.CREATE,
        replacement=False,
        destructive=False,
    )
    view = WorkflowView(
        request_id="req-001",
        workflow_status=WorkflowStatus.BLOCKED,
        current_stage=WorkflowStage.SECURITY_GATE,
        resource_name="orders-registry",
        security_status="block",
        plan_summary=PlanSummary(
            resource_changes=(change,),
            resources_to_add=("module.ecr.aws_ecr_repository.this",),
            resources_to_change=(),
            resources_to_destroy=(),
            destructive_change_detected=False,
        ),
        approval_decision=None,
        pull_request=PullRequestResult(
            number=7,
            url="https://github.com/octo/example/pull/7",
            branch="iac-agent/req-001",
            base_branch="main",
        ),
        error=WorkflowError(
            stage=WorkflowStage.PLAN,
            error_type="TerraformCommandError",
            message="AWS_SECRET_ACCESS_KEY=supersecret",
        ),
        security_gate=SecurityGateResult(findings=(finding,)),
    )
    event = project_workflow(view, kind="terminal")
    rendered = repr(event)
    assert event.findings[0].policy_id == "ECR_SCAN_ON_PUSH_RECOMMENDED"
    assert event.findings[0].status == "warn"
    assert event.findings[0].severity == "medium"
    assert event.add_count == 1
    assert event.published is True
    assert "orders-registry" not in rendered
    assert "aws_ecr_repository" not in rendered
    assert "github.com" not in rendered
    assert "supersecret" not in rendered
    assert "AWS_SECRET_ACCESS_KEY" not in rendered


def test_project_workflow_rejects_an_unknown_kind():
    view = WorkflowView(
        request_id="req-001",
        workflow_status=WorkflowStatus.ERROR,
        current_stage=WorkflowStage.ERROR,
        resource_name=None,
        security_status=None,
        plan_summary=None,
        approval_decision=ApprovalDecision.REJECT,
        pull_request=None,
        error=None,
    )
    with pytest.raises(ValueError):
        project_workflow(view, kind="get_state")
```

- [ ] **Step 2: Run and confirm collection fails on missing modules**

Run: `.venv/bin/python -m pytest tests/unit/observability/test_project.py -v`

Expected: `ModuleNotFoundError` for `iac_agent.observability`.

- [ ] **Step 3: Implement the models and projection**

`src/iac_agent/observability/__init__.py`:

```python
"""Platform-owned observability. No vendor SDK is imported here."""
```

`src/iac_agent/observability/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class GenerationTelemetry:
    request_id: str
    provider: str
    model: str
    prompt_version: str
    latency_ms: float
    attempt_count: int
    outcome_category: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ResolutionTelemetry:
    request_id: str
    outcome: str
    workload_type: str
    interaction_pattern: str
    capabilities: tuple[str, ...]
    user_provided_hints: tuple[str, ...]
    matched_pattern: str | None = None
    resolved_type: str | None = None
    clarification_reason: str | None = None
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class FindingTelemetry:
    policy_id: str
    status: str
    severity: str


@dataclass(frozen=True)
class WorkflowTelemetry:
    request_id: str
    kind: Literal["submit", "resume", "terminal"]
    workflow_status: str
    current_stage: str | None
    security_status: str | None
    add_count: int | None
    change_count: int | None
    destroy_count: int | None
    destructive_change_detected: bool | None
    findings: tuple[FindingTelemetry, ...]
    approval_decision: str | None
    error_stage: str | None
    error_type: str | None
    published: bool
```

`src/iac_agent/observability/project.py` builds those dataclasses by named attributes only.

`project_generation(metadata: Mapping[str, Any]) -> GenerationTelemetry` reads only `request_id`, `provider`, `model`, `prompt_version`, `latency_ms`, `attempt_count`, `outcome_category`, `input_tokens`, and `output_tokens`. Absent token keys become `None`. Do not call `dict(metadata)` into the model.

`project_resolution(request_id, intent, resolution) -> ResolutionTelemetry`:
- `workload_type`, `interaction_pattern`, sorted capability values, sorted `user_provided_hints` values
- `ResolvedArchitecture`: `outcome`, `matched_pattern`, `type(resolution.request_spec).__name__`
- `ClarificationRequired`: `clarification_reason=resolution.request.reason.value`. Do not copy any free-text question
- `UnsupportedArchitecture`: `unsupported_reason=resolution.reason.value`. Do not copy `detail`
- Do not read `logical_name_hint`, `assumptions`, `unresolved_questions`, `confidence`, or `request_spec.name`

`project_workflow(view, *, kind) -> WorkflowTelemetry`:
- `kind` must be `"submit"`, `"resume"`, or `"terminal"`; otherwise `ValueError`
- store enum `.value` strings: `view.workflow_status.value`, `current_stage.value` when set, `security_status` as already stored on the view (it is already a string or `None`)
- counts from `view.plan_summary` when it is not `None`, else `None`
- findings from `view.security_gate.findings` as `FindingTelemetry(policy_id, status.value, severity.value)` when the gate is not `None`, else `()`
- `approval_decision.value` when set
- `error.stage.value` and `error.error_type` when `view.error` is not `None`. Do not read `error.message`
- `published` is `view.pull_request is not None`. Do not read `url`, `branch`, `number`, or `base_branch`
- Do not read `view.resource_name`

- [ ] **Step 4: Re-run**

Run: `.venv/bin/python -m pytest tests/unit/observability/test_project.py -v`

Expected: pass. The ECR projection test uses the real resolver, not a network call.

- [ ] **Step 5: Commit**

Message: `feat(observability): project allowlisted telemetry models`

Use the Task 1 `commit-tree` sequence. Stage only the four files from this task.

---

### Task 3: Defense-in-depth sanitation

**Files:**
- Create: `src/iac_agent/observability/sanitize.py`
- Test: `tests/unit/observability/test_sanitize.py`

**Interfaces:**
- Consumes: the dataclasses from Task 2
- Produces: `sanitize_telemetry(event) ->` the same dataclass type

Sanitation is not the allowlist. It only rewrites string fields already on the model.

- [ ] **Step 1: Write the failing test**

```python
from iac_agent.observability.models import GenerationTelemetry, WorkflowTelemetry
from iac_agent.observability.sanitize import sanitize_telemetry


def test_secret_patterns_are_replaced_on_allowlisted_strings():
    event = GenerationTelemetry(
        request_id="req-001",
        provider="openai",
        model="sk-live-secret",
        prompt_version="4",
        latency_ms=1.0,
        attempt_count=1,
        outcome_category="Bearer abc.def.ghi",
    )
    cleaned = sanitize_telemetry(event)
    assert cleaned.model == "[redacted]"
    assert cleaned.outcome_category == "[redacted]"
    assert cleaned.request_id == "req-001"


def test_env_var_names_and_key_prefixes_are_replaced():
    event = WorkflowTelemetry(
        request_id="req-001",
        kind="terminal",
        workflow_status="error",
        current_stage="error",
        security_status=None,
        add_count=None,
        change_count=None,
        destroy_count=None,
        destructive_change_detected=None,
        findings=(),
        approval_decision=None,
        error_stage="plan",
        error_type="AWS_SECRET_ACCESS_KEY",
        published=False,
    )
    cleaned = sanitize_telemetry(event)
    assert cleaned.error_type == "[redacted]"


def test_ordinary_enums_pass_through():
    event = GenerationTelemetry(
        request_id="req-001",
        provider="openai",
        model="gpt-test",
        prompt_version="4",
        latency_ms=1.0,
        attempt_count=1,
        outcome_category="ok",
    )
    assert sanitize_telemetry(event) == event
```

Also assert these needles are replaced when planted in a string field: `sk-lf-abc`, `ghp_abc`, `github_pat_abc`, `AKIAIOSFODNN7EXAMPLE`, `ASIAIOSFODNN7EXAMPLE`, `BEGIN PRIVATE KEY`, `AWS_ACCESS_KEY_ID`, `AWS_SESSION_TOKEN`, `OPENAI_API_KEY`, `GITHUB_TOKEN`, and a three-segment JWT (`aaa.bbb.ccc`).

- [ ] **Step 2: Run and confirm import failure**

Run: `.venv/bin/python -m pytest tests/unit/observability/test_sanitize.py -v`

- [ ] **Step 3: Implement**

`sanitize_telemetry` walks `dataclasses.fields`. For each `str`, apply the patterns below and return a new instance via `dataclasses.replace`. Recurse into tuples of dataclasses (`findings`). Do not accept `dict`, `WorkflowView`, or `Exception`.

Patterns, in this order, each replaced with `[redacted]` for the whole field when it matches:

- `(?i)aws_secret_access_key|aws_access_key_id|aws_session_token|openai_api_key|github_token`
- `sk-lf-[A-Za-z0-9_-]+`
- `sk-[A-Za-z0-9_-]+`
- `ghp_[A-Za-z0-9]+`
- `github_pat_[A-Za-z0-9_]+`
- `AKIA[0-9A-Z]{16}`
- `ASIA[0-9A-Z]{16}`
- `(?i)bearer\s+\S+`
- `eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`
- `BEGIN PRIVATE KEY`

- [ ] **Step 4: Re-run the sanitize tests**

Expected: pass.

- [ ] **Step 5: Commit**

Message: `feat(observability): scrub secrets on allowlisted telemetry strings`

---

### Task 4: Port, NoOp, and fail-open

**Files:**
- Create: `src/iac_agent/observability/port.py`
- Create: `src/iac_agent/observability/noop.py`
- Create: `src/iac_agent/observability/failopen.py`
- Test: `tests/unit/observability/test_port.py`

**Interfaces:**
- Produces:

```python
class ObservabilityPort(Protocol):
    def record_generation(self, event: GenerationTelemetry) -> None: ...
    def record_resolution(self, event: ResolutionTelemetry) -> None: ...
    def record_workflow(self, event: WorkflowTelemetry) -> None: ...
    def flush(self) -> None: ...
```

`NoOpObservability` implements all four as `return`.

`FailOpenObservability(inner)` calls `inner` and catches `Exception` only. It does not catch `BaseException`. On failure it logs `error_type` and, when the event has `request_id`, that id. It does not log `str(exc)`. `flush` failures log `error_type` only.

- [ ] **Step 1: Write the failing test**

```python
import logging

from iac_agent.observability.failopen import FailOpenObservability
from iac_agent.observability.models import GenerationTelemetry, WorkflowTelemetry
from iac_agent.observability.noop import NoOpObservability


class _Boom:
    def record_generation(self, event) -> None:
        raise RuntimeError("langfuse down")

    def record_resolution(self, event) -> None:
        raise TimeoutError("telemetry timeout")

    def record_workflow(self, event) -> None:
        raise ValueError("cannot serialize")

    def flush(self) -> None:
        raise OSError("flush failed")


def _generation() -> GenerationTelemetry:
    return GenerationTelemetry(
        request_id="req-001",
        provider="openai",
        model="gpt-test",
        prompt_version="4",
        latency_ms=1.0,
        attempt_count=1,
        outcome_category="ok",
    )


def test_noop_methods_return_none():
    port = NoOpObservability()
    assert port.record_generation(_generation()) is None
    assert port.flush() is None


def test_failopen_swallows_record_and_flush_failures(caplog):
    port = FailOpenObservability(_Boom())
    with caplog.at_level(logging.INFO):
        port.record_generation(_generation())
        port.record_resolution(object())  # type: ignore[arg-type]
        port.record_workflow(
            WorkflowTelemetry(
                request_id="req-001",
                kind="terminal",
                workflow_status="error",
                current_stage=None,
                security_status=None,
                add_count=None,
                change_count=None,
                destroy_count=None,
                destructive_change_detected=None,
                findings=(),
                approval_decision=None,
                error_stage=None,
                error_type=None,
                published=False,
            )
        )
        port.flush()
    text = caplog.text
    assert "RuntimeError" in text
    assert "TimeoutError" in text
    assert "ValueError" in text
    assert "OSError" in text
    assert "langfuse down" not in text
    assert "flush failed" not in text
```

The `record_resolution(object())` line is only there if the inner raises before using the event. Prefer a real `ResolutionTelemetry` if constructing one is shorter. The inner's `record_resolution` ignores its argument and raises `TimeoutError`. Use a real `ResolutionTelemetry` so the test does not depend on a type-ignore.

- [ ] **Step 2: Run and confirm import failure**

- [ ] **Step 3: Implement the three modules**

Logger name: `iac_agent.observability`. Log level `WARNING`. Message template: `"observability %s failed"` with the method name, and `extra={"request_id": ..., "error_type": type(exc).__name__}`.

- [ ] **Step 4: Re-run `tests/unit/observability/test_port.py`**

- [ ] **Step 5: Commit**

Message: `feat(observability): add a fail-open observability port`

---

### Task 5: Retain safe interpreter call metadata

**Files:**
- Modify: `src/iac_agent/intent/adapters/openai.py`
- Test: `tests/unit/intent/adapters/test_openai_adapter.py`

**Interfaces:**
- Produces: `OpenAIIntentInterpreter.last_call_metadata: Mapping[str, Any] | None`

This is the dict `_log` already builds. Assign it to `self._last_call_metadata` at the end of `_log`, including the failure paths that log before raising. Expose it with a read-only property. Do not add the prompt, the response body, or the API key to the dict. Do not import Langfuse.

- [ ] **Step 1: Extend the existing adapter test**

The file already drives a fake client and asserts log extras. Add:

```python
def test_last_call_metadata_matches_safe_log_extras_and_omits_prompt(self):
    ...
    metadata = adapter.last_call_metadata
    assert metadata is not None
    assert metadata["request_id"] == _REQUEST_ID
    assert "input_tokens" in metadata  # only in the test whose fake usage has tokens
    assert "secret request text" not in repr(metadata)
```

Add a second case whose fake usage object has no `input_tokens` or `output_tokens` attribute. Assert those keys are absent. Follow the existing fake-usage test in this file rather than inventing a new client. There is already a test around the `"secret request text"` prompt. Extend that test; do not duplicate the client harness.

- [ ] **Step 2: Run the one new assertion and confirm it fails**

Run: `.venv/bin/python -m pytest tests/unit/intent/adapters/test_openai_adapter.py -v`

- [ ] **Step 3: Store the `extra` dict on `self._last_call_metadata` inside `_log`**

Initialize `self._last_call_metadata = None` in `__init__`.

- [ ] **Step 4: Re-run the adapter tests**

Expected: pass, still with no network. The existing prompt-version assertion stays `"4"`.

- [ ] **Step 5: Commit**

Message: `feat(intent): retain safe interpreter call metadata`

---

### Task 6: Instrument intent resolution

**Files:**
- Modify: `src/iac_agent/intent/service.py`
- Test: `tests/unit/observability/test_intent_instrumentation.py`

**Interfaces:**
- Consumes: `ObservabilityPort`, `project_generation`, `project_resolution`, `sanitize_telemetry`
- `IntentResolutionService.__init__` gains `observability: ObservabilityPort | None = None`. Default is `FailOpenObservability(NoOpObservability())`.

Behavior of `submit`:

```python
try:
    intent = self._interpreter.interpret(...)
except IntentInterpreterError:
    self._emit_generation(request_id)
    raise
self._emit_generation(request_id)
event = sanitize_telemetry(project_resolution(request_id, intent, result))
self._observability.record_resolution(event)
self._observability.flush()
```

`_emit_generation` reads `getattr(self._interpreter, "last_call_metadata", None)`. If it is `None`, it records nothing. Otherwise it projects, sanitizes, and calls `record_generation`. It does not catch exceptions of its own.

Clarification and unsupported still return `workflow_view=None` and still do not call `application.submit`.

- [ ] **Step 1: Write the failing tests**

Use `ArchitectureResolver` and small `ArchitectureIntent` payloads, plus a fake interpreter. Do not import the OpenAI SDK.

```python
class RecordingObservability:
    def __init__(self) -> None:
        self.generations = []
        self.resolutions = []
        self.workflows = []
        self.flushes = 0

    def record_generation(self, event) -> None:
        self.generations.append(event)

    def record_resolution(self, event) -> None:
        self.resolutions.append(event)

    def record_workflow(self, event) -> None:
        self.workflows.append(event)

    def flush(self) -> None:
        self.flushes += 1


class _NeverSubmit:
    def submit(self, **kwargs):
        raise AssertionError("submit must not be called")
```

Cases:

1. Resolved storage+container_registry intent. Interpreter exposes `last_call_metadata` with tokens. Assert one generation, one resolution with `resolved_type == "EcrResourceSpec"`, and that the raw prompt string is absent from `repr(recorder.generations)`.
2. Same, but metadata has no token keys. Assert `input_tokens is None`.
3. Interpreter has no `last_call_metadata`. Assert `generations == []` and a resolution event still exists.
4. Clarification payload, the same shape as `tests/integration/test_intent_resolution_service.py` `_CLARIFICATION_PAYLOAD`: `schema_version=1`, `workload_type=unspecified`, `interaction_pattern=unspecified`, `capabilities=[]`. Assert `outcome == "clarification_required"`, `workflows == []`, and `_NeverSubmit` is the application.
5. Unsupported payload, the same shape as `_UNSUPPORTED_PAYLOAD` in that file: `workload_type=storage`, `interaction_pattern=unspecified`, `capabilities=["persistence"]`. Assert `unsupported_reason` is set and `application.submit` is not called.
6. Interpreter raises `IntentProviderTimeoutError` after setting `last_call_metadata`. Assert the exception propagates, one generation was recorded, and `resolutions == []`.
7. `RecordingObservability.record_resolution` raises `RuntimeError` when the service is wrapped by the caller in `FailOpenObservability`. Assert `submit` still returns the same `IntentSubmissionResult` it would without a recorder. Build that wrap in the test. The service itself must not catch `RuntimeError`.

Construct resolved intents with `logical_name_hint="orders-registry"` and assert that string is absent from every recorded event.

- [ ] **Step 2: Run and confirm failure**

- [ ] **Step 3: Implement the service change**

Existing constructors in `tests/unit/cli/` and `tests/integration/test_intent_resolution_service.py` omit `observability`. The default must keep them working. Do not edit those files in this task.

- [ ] **Step 4: Re-run the new file and the existing intent service tests**

```bash
.venv/bin/python -m pytest tests/unit/observability/test_intent_instrumentation.py tests/integration/test_intent_resolution_service.py -v
```

Expected: pass.

- [ ] **Step 5: Commit**

Message: `feat(intent): emit interpretation and resolution telemetry`

---

### Task 7: Instrument submit, resume, and terminal

**Files:**
- Modify: `src/iac_agent/app/service.py`
- Test: `tests/unit/observability/test_workflow_instrumentation.py`

**Interfaces:**
- `IacApplication.__init__(self, graph, *, observability: ObservabilityPort | None = None)`
- `from_application` stays `cls(application.graph)` so existing callers keep the default NoOp

After `submit` and `resume` build the `WorkflowView`:

```python
self._observability.record_workflow(sanitize_telemetry(project_workflow(view, kind="submit")))
# resume uses kind="resume"
if view.workflow_status is not WorkflowStatus.AWAITING_APPROVAL:
    self._observability.record_workflow(
        sanitize_telemetry(project_workflow(view, kind="terminal"))
    )
self._observability.flush()
return view
```

`get_state` does not call the port.

Duplicate the fakes from `tests/unit/graph/test_workflow.py` (`FakeRenderer`, `FakeTerraformRunner`, `FakeCheckovAdapter`, `FakeSourceControl`, `_spec`, `_DEFAULT_PLAN_JSON`, `_CLEAN_CHECKOV_RESULT`). This repo keeps those fakes per file. Do not import them from the other test module.

Cases, all offline:

1. Happy path `IacApplication.submit` reaches `AWAITING_APPROVAL`. Recorder has one `kind="submit"` event and no `kind="terminal"`. `resource` name `"order-events"` is absent. Plan address `module.queue.aws_sqs_queue.this` is absent. The rendered file text `"# fake"` is absent.
2. `get_state` on that paused graph adds no events and does not increment `flush`.
3. `resume(..., REJECT)` adds `kind="resume"` and `kind="terminal"` with `workflow_status="rejected"`.
4. A second `IacApplication` around a newly compiled graph and a new `SqliteSaver` opened on the same database file, after the first checkpointer context has closed, resumes `ApprovalDecision.APPROVE`. Use the `open_sqlite_checkpointer` plus `build_sqs_workflow(..., checkpointer=saver)` shape from `tests/unit/graph/test_workflow.py` `_build_durable` and `test_interrupted_pass_state_round_trips_through_real_sqlite`. Both recorders receive the same `request_id`. The terminal event has `workflow_status == "pr_created"`, `approval_decision == "approve"`, and `published is True`. `PullRequestResult.url` is not in `repr` of the events.
5. `FakeTerraformRunner(fail_at="plan", fail_exc=TerraformCommandError(CommandResult(command=("terraform", "plan"), returncode=1, stdout="", stderr="benign failure", duration_seconds=0.0)))` produces `WorkflowStatus.ERROR`. The terminal event has `error_type == "TerraformCommandError"`. `repr` of the events does not contain `benign failure`. That string is on `WorkflowError.message` today (`str(exc)[:500]` in `_error_update`); its absence is the proof the projection does not copy the message.
6. `FakeCheckovAdapter(result=...)` uses the same finding shape as `tests/unit/graph/test_workflow.py` `_block_checkov_result`: `policy_id="CKV_AWS_27"`, `status=BLOCK`, `resource="module.queue.aws_sqs_queue.this"`, `message="Checkov CKV_AWS_27 failed."`. Terminal `workflow_status == "blocked"`. The recorded finding is `policy_id`, `status`, `severity` only. `repr` of the events does not contain `module.queue.aws_sqs_queue.this` or `Checkov CKV_AWS_27 failed.`
7. Wrap a recorder whose `flush` raises `OSError`. `submit` still returns `AWAITING_APPROVAL`. Use `FailOpenObservability` as the port the application holds.
8. A recorder whose `record_workflow` raises `TimeoutError`, also behind `FailOpenObservability`, does not change the view.

`TerraformCommandError` is `iac_agent.execution.terraform_runner.TerraformCommandError`. Match an existing `fail_at="plan"` test in `tests/unit/graph/test_workflow.py` if the constructor differs.

- [ ] **Step 1: Write the failing tests**

- [ ] **Step 2: Run and confirm failure**

- [ ] **Step 3: Implement `IacApplication` instrumentation**

Do not edit `src/iac_agent/graph/workflow.py`.

- [ ] **Step 4: Re-run**

```bash
.venv/bin/python -m pytest tests/unit/observability/test_workflow_instrumentation.py tests/unit/cli/test_propose.py tests/unit/cli/test_resume.py -q
```

Expected: pass. Existing CLI tests construct `IacApplication(graph)` with no port.

- [ ] **Step 5: Commit**

Message: `feat(app): emit workflow telemetry from submit and resume`

---

### Task 8: Default-off composition

**Files:**
- Modify: `src/iac_agent/app/config.py`
- Modify: `src/iac_agent/app/composition.py`
- Test: `tests/unit/app/test_observability_config.py`

**Interfaces:**
- Produces: `ObservabilityMode`, `ObservabilitySettings`, `load_observability_settings_from_env`, `build_observability`

```python
class ObservabilityMode(StrEnum):
    OFF = "off"
    LANGFUSE = "langfuse"

@dataclass(frozen=True)
class ObservabilitySettings:
    mode: ObservabilityMode = ObservabilityMode.OFF
```

`load_observability_settings_from_env` reads `IAC_AGENT_OBSERVABILITY`. Unset, `""`, `off`, and `noop` return `OFF`. `langfuse` returns `LANGFUSE`. Any other value raises `MissingConfigurationError`. This object holds no secrets.

Gate A `build_observability(settings)` returns `FailOpenObservability(NoOpObservability())` only for `ObservabilityMode.OFF`. `ObservabilityMode.LANGFUSE` raises `ObservabilityConfigurationError`. It must not be reported as an active or silent no-op. Gate B replaces the `LANGFUSE` arm with the adapter. Unknown values fail in `load_observability_settings_from_env` via `MissingConfigurationError`.

```python
def test_langfuse_is_recognized_and_rejected_until_the_adapter_exists():
    settings = load_observability_settings_from_env({"IAC_AGENT_OBSERVABILITY": "langfuse"})
    assert settings.mode is ObservabilityMode.LANGFUSE
    with pytest.raises(ObservabilityConfigurationError, match="langfuse"):
        build_observability(settings)
```

Disabled settings build a port whose `record_generation` and `flush` do not log a warning.

`open_intent_application` builds one port with `build_observability(load_observability_settings_from_env())` and passes that same object to both `IacApplication(application.graph, observability=port)` and `IntentResolutionService(..., observability=port)`.

Do not read `LANGFUSE_PUBLIC_KEY` or `LANGFUSE_SECRET_KEY` in Gate A.

- [ ] **Step 1: Write the failing config tests**

Also assert `ApplicationConfig` field names do not include `langfuse`, `api_key`, or `token`. Read `dataclasses.fields(ApplicationConfig)`.

- [ ] **Step 2: Run and confirm failure**

- [ ] **Step 3: Implement config and composition**

- [ ] **Step 4: Re-run**

```bash
.venv/bin/python -m pytest tests/unit/app/test_observability_config.py tests/unit/app/test_intent_interpreter_config.py -q
```

- [ ] **Step 5: Commit**

Message: `feat(app): default observability to a no-op`

---

### Task 9: Gate A verification

**Files:** none new. This task only runs the suite and commits nothing unless a test from Tasks 1–8 is still red, in which case fix that task's code and make a new commit. Do not amend.

- [ ] **Step 1: Run the deterministic suite**

```bash
.venv/bin/python -m pytest -m "not real_tool and not real_llm" -q
.venv/bin/python -m ruff check .
git diff --check
```

Expected: pytest passes, ruff passes, diff check prints nothing.

- [ ] **Step 2: Confirm the Langfuse package is not imported by the suite**

```bash
.venv/bin/python -c "import iac_agent.app.composition, iac_agent.app.service, iac_agent.intent.service, iac_agent.graph.workflow"
```

Expected: success on a environment that does not have `langfuse` installed. Do not `pip install langfuse`.

- [ ] **Step 3: Confirm git status is clean**

```bash
git status -sb
```

Expected: the branch is ahead of `9dbc7f2` by the Task 1–8 commits only, working tree clean.

---

### Task 10: Optional Langfuse adapter

**Files:**
- Modify: `pyproject.toml` optional-dependencies only
- Create: `src/iac_agent/observability/adapters/__init__.py`
- Create: `src/iac_agent/observability/adapters/langfuse.py`
- Modify: `src/iac_agent/app/composition.py` `build_observability`
- Test: `tests/unit/observability/test_langfuse_adapter.py`
- Test: `tests/unit/observability/test_import_isolation.py`
- Modify: `tests/unit/app/test_observability_config.py` for the factory seam

**Interfaces:**
- Produces: `LangfuseObservability`, `build_observability(settings, *, env=None, adapter_factory=None)`

Do not change `.github/workflows/ci.yml`. The new tests must pass without the `langfuse` distribution installed.

`pyproject.toml` addition, beside the `openai` extra:

```toml
langfuse = [
    "langfuse>=4,<5",
]
```

`LangfuseObservability.__init__(self, client) -> None` stores the client. It does not construct one.

Methods:

- `record_generation`: `trace_id = self._client.create_trace_id(seed=event.request_id)`. Start a generation observation named `intent.interpret`. Pass only the dataclass fields as metadata/usage. Usage is `{"input": event.input_tokens, "output": event.output_tokens}` only for keys whose value is not `None`. Do not pass a prompt or completion argument.
- `record_resolution`: same `create_trace_id(seed=event.request_id)`, event named `intent.resolve`, metadata from the dataclass fields.
- `record_workflow`: same seed, event name `workflow.{kind}`.
- `flush`: `self._client.flush()`.

The fake client in the test records every `create_trace_id` seed and every observation payload. Assert:

- two calls with the same `request_id` pass the same seed
- a generation payload has no attribute or dict key named `input`, `prompt`, `completion`, or `output` when token counts are `None` (the usage dict is omitted entirely)
- when tokens are present, usage contains those integers and still has no prompt
- `flush` is forwarded
- the adapter does not catch exceptions. `FailOpenObservability` remains the catcher. A test wraps the adapter's client that raises on `flush` and asserts the wrapper returns.

`build_observability`:

```python
def build_observability(settings, *, env=None, adapter_factory=None):
    if settings.mode is not ObservabilityMode.LANGFUSE:
        return FailOpenObservability(NoOpObservability())
    source = os.environ if env is None else env
    public = source.get("LANGFUSE_PUBLIC_KEY")
    secret = source.get("LANGFUSE_SECRET_KEY")
    if not public or not secret:
        return FailOpenObservability(NoOpObservability())
    factory = adapter_factory if adapter_factory is not None else _default_langfuse_factory
    try:
        inner = factory(source)
    except Exception:
        return FailOpenObservability(NoOpObservability())
    if inner is None:
        return FailOpenObservability(NoOpObservability())
    return FailOpenObservability(inner)
```

`_default_langfuse_factory` is the only function that imports Langfuse:

```python
def _default_langfuse_factory(env: Mapping[str, str]):
    from langfuse import Langfuse

    return LangfuseObservability(
        Langfuse(
            public_key=env["LANGFUSE_PUBLIC_KEY"],
            secret_key=env["LANGFUSE_SECRET_KEY"],
            base_url=env.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        )
    )
```

Unit tests always pass `adapter_factory` and never call `_default_langfuse_factory`. Missing keys return NoOp without calling the factory. A factory that raises returns NoOp.

Replace the Gate A rejection of `ObservabilityMode.LANGFUSE` with the factory seam. With mode `LANGFUSE` and both keys set, a factory that returns a sentinel is used. Assert the sentinel is what `build_observability` wraps. With the keys absent, the factory is not called and the result is NoOp. A missing key is not the same as `IAC_AGENT_OBSERVABILITY=langfuse` while the adapter is unimplemented: Gate A rejects the latter; Gate B treats missing keys as disabled.

`tests/unit/observability/test_import_isolation.py` parses AST:

- `src/iac_agent/app/service.py`, `src/iac_agent/intent/service.py`, `src/iac_agent/graph/workflow.py`, `src/iac_agent/cli/main.py`, and `src/iac_agent/observability/port.py` contain no `langfuse` import
- `src/iac_agent/app/composition.py` and `src/iac_agent/observability/adapters/langfuse.py` may import `langfuse` only inside a function, never at module level

`adapters/__init__.py` is a docstring only. It must not import the adapter module at import time, so `import iac_agent.observability` stays vendor-free.

- [ ] **Step 1: Write the failing adapter and isolation tests**

- [ ] **Step 2: Run and confirm failure**

- [ ] **Step 3: Implement the adapter, the extra, and the factory**

Do not `pip install langfuse`.

- [ ] **Step 4: Re-run**

```bash
.venv/bin/python -m pytest tests/unit/observability tests/unit/app/test_observability_config.py -q
.venv/bin/python -c "import iac_agent.app.composition"
```

Expected: pass, and the import succeeds without the Langfuse distribution.

- [ ] **Step 5: Commit**

Message: `feat(observability): add an optional Langfuse adapter`

---

### Task 11: Document the boundary

**Files:**
- Create: `docs/observability.md`
- Modify: `docs/roadmap.md` (the paragraph under Batch 27 that says Langfuse is not implemented)

**Interfaces:** none

`docs/observability.md` states, in prose:

- Observability is off unless `IAC_AGENT_OBSERVABILITY=langfuse` and both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set and the `langfuse` extra is installed.
- The base URL defaults to `https://cloud.langfuse.com`. Self-hosting is not the portfolio path.
- The correlation key is `request_id`. Resume recomputes the vendor trace id from that seed.
- The document lists the allowlist and the denylist from the spec, including the prohibition on prompts and model output.
- Langfuse does not block Terraform. Checkov and platform policies do.
- A telemetry failure does not change the workflow result.
- Normal tests do not call Langfuse. There is no `real_observability` marker in this batch.

Replace the roadmap sentences that say the capability is future and unimplemented with a pointer to `docs/observability.md` and the spec. Keep the sentence that Langfuse is not Checkov, not a platform policy, and not AWS monitoring.

- [ ] **Step 1: Write the doc and the roadmap edit**

- [ ] **Step 2: Gate B verification**

```bash
.venv/bin/python -m pytest -m "not real_tool and not real_llm" -q
.venv/bin/python -m ruff check .
git diff --check
```

Expected: pass. Do not run `pytest -m real_llm`. Do not run `pytest -m real_tool` as a requirement of this batch. Do not install Langfuse.

- [ ] **Step 3: Commit**

Message: `docs: document the optional Langfuse observability boundary`

---

## Gate C

No task. A live Langfuse Cloud call is a later human-authorized experiment. It would need a project, keys, and network, and it would not prove allowlisting beyond Task 10's fake client. If it is ever added, it gets its own pytest marker, it is excluded from `pytest -m "not real_tool and not real_llm"`, and it still must not send a prompt or model output. Do not add that marker in this plan.

## Spec coverage

| Spec requirement | Task |
|---|---|
| Request-id uniqueness, legacy ids still valid, `--request-id` unchanged | 1 |
| Allowlisted models and projection | 2 |
| Defense-in-depth sanitation after projection | 3 |
| Port, NoOp, fail-open, timeout, flush, SDK-style exceptions | 4 |
| Token counts only when the provider sent them | 5, 6 |
| Interpret, resolve, clarification, unsupported, interpreter error re-raised | 6 |
| Submit, resume, terminal, get_state silence, BLOCK, ERROR, reject, fresh process | 7 |
| Default off, no secrets on `ApplicationConfig` | 8 |
| Optional adapter, deterministic seed, import isolation, no CI install | 10 |
| Operator documentation | 11 |
| Golden datasets unchanged | no task edits `evals/datasets/` |
| Graph nodes uninstrumented | no task edits `graph/workflow.py` |
| Live vendor call | Gate C, not tasked |
