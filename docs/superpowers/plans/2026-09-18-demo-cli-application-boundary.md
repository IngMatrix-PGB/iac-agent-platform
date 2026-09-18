# Demo CLI / Application Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing NL → resolver → Terraform → security → HITL → GitHub pipeline through a thin stdlib argparse CLI (`iac-agent propose` / `iac-agent resume`) without adding a second orchestrator or `terraform apply`.

**Architecture:** Widen `IntentSubmissionResult` to retain `ArchitectureIntent`; expose `SecurityGateResult` on `WorkflowView`; add a frozen `IntentApplication` holder that wraps existing `open_application`; CLI owns parsing, presentation, request-id generation, and TTY y/N mapping only — all business calls go to `IntentResolutionService.submit` and `IacApplication.resume`/`get_state`.

**Tech Stack:** Python 3.12, stdlib argparse, existing Pydantic/LangGraph/SQLite stack. No new runtime dependency. Optional `[openai]` extra unchanged and unused by default tests.

**Spec:** `docs/superpowers/specs/2026-09-18-demo-cli-application-boundary-design.md` (design commit `b3a5290e47d830ff85d4c09bd9b94572acc06c4d`).

## Global Constraints

1. **stdlib argparse only.** No Typer, Click, Rich, colors, or spinners.
2. **No `ProposalService` / `IacProposalService`.** `IntentResolutionService` owns interpret → resolve → submit. `IacApplication` owns submit/resume/get_state.
3. **`IntentApplication` is a frozen composition holder** with exactly `config`, `intent_service`, `application`. It owns **no** propose/resume/submit business methods.
4. **`open_intent_application(...)` wraps `open_application(...)`.** Existing `open_application` callers stay compatible. SQLite and GitHub-token unwrap stay inside `open_application`.
5. **`IntentSubmissionResult` retains** `request_id`, `intent`, `resolution`, `workflow_view`, plus derived `approval_available`. Do not default `intent=None`.
6. **`ArchitectureIntent` is NOT persisted** into LangGraph/`WorkflowState`/SQLite. Do not add it to `_ALLOWED_WORKFLOW_TYPES`.
7. **`WorkflowView` gains** `security_gate: SecurityGateResult | None = None`. No third presentation DTO.
8. **CLI commands exactly:** `iac-agent propose "<nl>" [--request-id ID]` and `iac-agent resume REQUEST_ID --approve|--reject`. No `--dry-run`, `--no-github`, `--yes` on propose.
9. **request_id generation:** `req-YYYYMMDDTHHMMSSZ` (UTC). Clock is injected for tests.
10. **Interactive approval** only when `sys.stdin.isatty()` AND `approval_available`. y/yes → `ApprovalDecision.APPROVE`; anything else → `REJECT`. Then `IacApplication.resume`. No second approval mechanism.
11. **BLOCKED / ERROR / CLARIFICATION_REQUIRED / UNSUPPORTED never prompt.**
12. **GitHub remains one `publish_change` after APPROVED.** CLI never calls GitHub APIs.
13. **No FastAPI, no Next.js, no extra LLM providers, no `terraform apply`.** `TerraformRunner` still has no `apply`/`destroy`.
14. **Fakes live only in test files**, never under `src/`. Default pytest makes zero OpenAI calls and requires zero `OPENAI_API_KEY`.
15. **Git discipline.** Implementation branch `feat/batch24-demo-cli` created from this plan's branch before Task 1. Commit per task with the exact message below. Never force-push, amend, or rewrite history. **No `Co-Authored-By` trailer.** If a `prepare-commit-msg` hook injects one, rebuild that commit with `git commit-tree` (do not `--no-verify` the whole hook set on first commit). Never push without a separate explicit instruction.
16. **GATE C and GATE D are hard stops.** Tasks 14–15 are not auto-executed. They require separate explicit human authorization. No task before them may call OpenAI for real or create a real GitHub PR.

---

## File structure

| File | Responsibility |
|---|---|
| `src/iac_agent/intent/service.py` | Widen `IntentSubmissionResult`; retain `intent` in `submit` |
| `src/iac_agent/app/service.py` | Add `WorkflowView.security_gate`; `_to_view` copies it |
| `src/iac_agent/app/composition.py` | Add `IntentApplication` + `open_intent_application` (lazy imports to avoid a cycle) |
| `src/iac_agent/cli/parser.py` | argparse only — no I/O, no services |
| `src/iac_agent/cli/ids.py` | `generate_request_id(now=...)` |
| `src/iac_agent/cli/present.py` | Pure stdout rendering of `IntentSubmissionResult` / `WorkflowView` / interpreter errors |
| `src/iac_agent/cli/approval.py` | `parse_cli_approval(raw) -> ApprovalDecision` |
| `src/iac_agent/cli/main.py` | Wire parse → services → present → optional TTY resume; injectable deps |
| `src/iac_agent/cli/__init__.py` | Empty/minimal package marker |
| `src/iac_agent/cli/__main__.py` | `raise SystemExit(main())` |
| `pyproject.toml` | `[project.scripts] iac-agent = "iac_agent.cli.main:main"` only |
| `README.md`, `docs/application.md` | Demo invocation notes |
| `tests/integration/test_intent_resolution_service.py` | Retention + error + approval_available |
| `tests/unit/app/test_service.py` | security_gate visibility / Checkov+plan still hidden |
| `tests/unit/intent/test_intent_not_persisted.py` | Intent absent from WorkflowState allowlist |
| `tests/unit/app/test_intent_application.py` | Holder composition proofs |
| `tests/unit/cli/test_parser.py` | Parser only |
| `tests/unit/cli/test_ids.py` | Clock-injected ids |
| `tests/unit/cli/test_present.py` | Deterministic reports + sanitization |
| `tests/unit/cli/test_approval.py` | y/N mapping |
| `tests/unit/cli/test_propose.py` | propose orchestration with injected holder |
| `tests/unit/cli/test_resume.py` | resume orchestration with injected holder |
| `tests/unit/cli/test_failures.py` | Interpreter/config failure mapping |
| `tests/unit/cli/test_no_apply.py` | Structural no-apply / no-openai in cli package |
| `tests/integration/test_cli_e2e.py` | Deterministic fake-interpreter E2E |
| `tests/integration/test_cli_real_tool.py` | `real_tool` worker propose/resume; fake interpreter + fake GitHub transport |

Do **not** modify: `iac_agent.graph.workflow`, resolver allowlist, OpenAI adapter, policies, `TerraformRunner` methods, GitHub adapter protocol, CI workflows, `scripts/live_github_smoke.py`.

**Cycle note:** `app.service` imports `composition.Application`; `intent.service` imports `IacApplication`. `open_intent_application` must lazy-import `IntentResolutionService` / `IacApplication` inside the function and use `TYPE_CHECKING` for `IntentApplication` annotations so `composition.py` does not import `intent.service` at module top-level.

## Branch strategy

This plan is committed on `docs/batch24-demo-cli-design`. Before Task 1:

```bash
git checkout -b feat/batch24-demo-cli
```

All implementation commits land on `feat/batch24-demo-cli`.

---

### Task 1: IntentSubmissionResult intent retention

**Files:**
- Modify: `src/iac_agent/intent/service.py`
- Test: `tests/integration/test_intent_resolution_service.py` (extend)
- Test: `tests/unit/intent/test_intent_not_persisted.py` (create)

**Interfaces:**
- Consumes: `IntentInterpreterPort.interpret(*, natural_language_request, request_id) -> ArchitectureIntent`; `ArchitectureResolver.resolve(*, intent, request_id) -> ResolutionResult`; `IacApplication.submit(*, request_id, spec) -> WorkflowView`
- Produces: `IntentSubmissionResult(request_id: str, intent: ArchitectureIntent, resolution: ResolutionResult, workflow_view: WorkflowView | None)` with `@property approval_available: bool`

- [ ] **Step 1: Write the failing tests**

Add to `tests/integration/test_intent_resolution_service.py` (keep existing fakes/payloads):

```python
def test_resolved_result_retains_exact_interpreted_intent(tmp_path):
    service = IntentResolutionService(
        interpreter=FakeIntentInterpreter(payload=_RESOLVABLE_API_PAYLOAD),
        resolver=ArchitectureResolver(),
        application=_build_application(tmp_path),
    )
    result = service.submit(request_id="req-001", natural_language_request="build me an api")
    assert result.request_id == "req-001"
    assert result.intent.workload_type.value == "api"
    assert result.intent.interaction_pattern.value == "synchronous"
    assert result.intent.capabilities == frozenset({Capability.HTTP_ENDPOINT})
    assert result.intent is parse_intent_payload(_RESOLVABLE_API_PAYLOAD) or (
        result.intent.model_dump(mode="json")["workload_type"] == "api"
    )
    assert result.resolution.outcome == "resolved"
    assert result.workflow_view is not None
    assert result.approval_available is True


def test_clarification_retains_intent_and_never_submits(tmp_path):
    service = IntentResolutionService(
        interpreter=FakeIntentInterpreter(payload=_CLARIFICATION_PAYLOAD),
        resolver=ArchitectureResolver(),
        application=_NeverCalledApplication(),
    )
    result = service.submit(request_id="req-002", natural_language_request="do something")
    assert result.request_id == "req-002"
    assert result.intent.workload_type.value == "unspecified"
    assert result.workflow_view is None
    assert result.approval_available is False
    assert result.resolution.outcome == "clarification_required"


def test_unsupported_retains_intent_and_never_submits():
    service = IntentResolutionService(
        interpreter=FakeIntentInterpreter(payload=_UNSUPPORTED_PAYLOAD),
        resolver=ArchitectureResolver(),
        application=_NeverCalledApplication(),
    )
    result = service.submit(request_id="req-003", natural_language_request="build an aurora db")
    assert result.intent.workload_type.value == "storage"
    assert result.workflow_view is None
    assert result.approval_available is False
    assert result.resolution.outcome == "unsupported"
```

Existing `test_interpreter_failure_propagates_uncaught` stays: timeout still raises, no result.

Create `tests/unit/intent/test_intent_not_persisted.py`:

```python
from iac_agent.graph.state import WorkflowState
from iac_agent.persistence.checkpoints import _ALLOWED_WORKFLOW_TYPES
from iac_agent.app.service import WorkflowView


def test_architecture_intent_is_not_a_checkpointed_workflow_type():
    names = {qualname for _module, qualname in _ALLOWED_WORKFLOW_TYPES}
    assert "ArchitectureIntent" not in names


def test_workflow_state_has_no_intent_field():
    assert "intent" not in WorkflowState.__annotations__
    assert "architecture_intent" not in WorkflowState.__annotations__


def test_workflow_view_has_no_intent_field():
    assert "intent" not in WorkflowView.__dataclass_fields__
```

Add `from iac_agent.intent.models import Capability` to the integration test imports.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_intent_resolution_service.py::test_resolved_result_retains_exact_interpreted_intent tests/unit/intent/test_intent_not_persisted.py -v`

Expected: FAIL (`IntentSubmissionResult` has no `request_id` / `intent` / `approval_available`). Persistence tests may PASS already (they prove absence); that is acceptable — the integration retention tests must FAIL first.

- [ ] **Step 3: Minimal implementation**

In `src/iac_agent/intent/service.py`:

```python
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.domain.workflow import WorkflowStatus


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

Update both `IntentSubmissionResult(...)` constructors in `submit` to pass `request_id=request_id, intent=intent`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_intent_resolution_service.py tests/unit/intent/test_intent_not_persisted.py -v`

Expected: PASS (existing tests only read `.resolution` / `.workflow_view`).

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/intent/service.py tests/integration/test_intent_resolution_service.py tests/unit/intent/test_intent_not_persisted.py
git commit -m "feat(intent): retain ArchitectureIntent on IntentSubmissionResult"
```

---

### Task 2: WorkflowView security_gate exposure

**Files:**
- Modify: `src/iac_agent/app/service.py`
- Test: `tests/unit/app/test_service.py`

**Interfaces:**
- Consumes: `values["security_gate"]` from graph state (`SecurityGateResult | missing`)
- Produces: `WorkflowView.security_gate: SecurityGateResult | None = None` plus existing `security_status` string

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/app/test_service.py`:

```python
from iac_agent.app.service import _to_view
from iac_agent.domain.security import SecurityGateResult, PolicyStatus


def test_security_gate_is_none_before_gate_values_exist():
    view = _to_view("req-001", {"workflow_status": WorkflowStatus.RUNNING})
    assert view.security_gate is None
    assert view.security_status is None


def test_submit_exposes_pass_security_gate(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    with open_sqlite_checkpointer(db_path) as saver:
        app, _ = _build_app(workspace_root, saver)
        view = app.submit(request_id="req-001", spec=_spec())
    assert view.security_gate is not None
    assert view.security_gate.overall_status is PolicyStatus.PASS
    assert view.security_status == "pass"


def test_submit_exposes_block_security_gate(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    with open_sqlite_checkpointer(db_path) as saver:
        app, _ = _build_app(
            workspace_root, saver, checkov_adapter=FakeCheckovAdapter(block=True)
        )
        view = app.submit(request_id="req-block", spec=_spec())
    assert view.security_gate is not None
    assert view.security_gate.overall_status is PolicyStatus.BLOCK
    assert view.security_status == "block"
```

Keep `test_view_excludes_raw_checkov_data` and `test_view_excludes_raw_plan_json`. Add:

```python
def test_view_still_hides_raw_checkov_result_after_gate_exposure(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    with open_sqlite_checkpointer(db_path) as saver:
        app, _ = _build_app(workspace_root, saver)
        view = app.submit(request_id="req-001", spec=_spec())
    assert not hasattr(view, "checkov_result")
    assert "scanner_version" not in repr(view)
    assert "terraform_plan_json" not in WorkflowView.__dataclass_fields__
```

For WARN: SQS default spec PASSes. Construct `_to_view` with a `SecurityGateResult` containing one WARN finding (do not change platform policies):

```python
def test_to_view_exposes_warn_security_gate():
    finding = SecurityFinding(
        policy_id="LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED",
        severity=SecuritySeverity.MEDIUM,
        status=PolicyStatus.WARN,
        resource="fn",
        message="not set",
        source=FindingSource.PLATFORM_POLICY,
    )
    gate = SecurityGateResult(findings=(finding,))
    view = _to_view(
        "req-001",
        {
            "workflow_status": WorkflowStatus.AWAITING_APPROVAL,
            "security_gate": gate,
        },
    )
    assert view.security_gate is gate
    assert view.security_status == "warn"
```

Import `SecurityFinding`, `SecuritySeverity`, `FindingSource` (already imported in this file).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/app/test_service.py::test_security_gate_is_none_before_gate_values_exist tests/unit/app/test_service.py::test_submit_exposes_pass_security_gate tests/unit/app/test_service.py::test_to_view_exposes_warn_security_gate -v`

Expected: FAIL (`WorkflowView` has no `security_gate`).

- [ ] **Step 3: Minimal implementation**

In `src/iac_agent/app/service.py` import `SecurityGateResult` from `iac_agent.domain.security`. Add field `security_gate: SecurityGateResult | None = None` as the last field of `WorkflowView`. In `_to_view`, pass `security_gate=security_gate`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/app/test_service.py -v`

Expected: PASS, including existing Checkov/plan-exclusion tests.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/app/service.py tests/unit/app/test_service.py
git commit -m "feat(app): expose SecurityGateResult on WorkflowView"
```

---

### Task 3: IntentApplication composition holder

**Files:**
- Modify: `src/iac_agent/app/composition.py`
- Test: `tests/unit/app/test_intent_application.py` (create)

**Interfaces:**
- Consumes: `open_application(config, *, github_token, github_transport=None) -> Iterator[Application]`; `IntentInterpreterPort`; optional `ArchitectureResolver`
- Produces:

```python
@dataclass(frozen=True)
class IntentApplication:
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
) -> Iterator[IntentApplication]: ...
```

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/app/test_intent_application.py`. Use a `FakeIntentInterpreter` (copy the small class from `tests/integration/test_intent_resolution_service.py` into this file — fakes are per-file). Use `github_transport` fake like `tests/integration/test_application_composition.py` **or** construct `IntentApplication` after stubbing inner `open_application` if real terraform is too heavy for a unit test.

Preferred unit shape (no real Terraform): do **not** call `open_intent_application` with real adapters. Instead:

1. Import-level tests that `open_intent_application` / `IntentApplication` exist (will fail until implemented).
2. A test that patches `iac_agent.app.composition.open_application` to yield a tiny `Application(config=..., graph=fake_graph)` built with `build_iac_workflow` + fakes + sqlite, then calls the real `open_intent_application`.

Simplest proven path: build the same fake graph as `tests/unit/app/test_service.py`, wrap it, and test holder invariants **without** going through `open_intent_application` for wiring identity — plus one test of `open_intent_application` that patches `open_application`.

```python
import inspect
from dataclasses import fields
from unittest.mock import patch

from pydantic import SecretStr

from iac_agent.app.composition import Application, IntentApplication, open_intent_application
from iac_agent.app.config import ApplicationConfig
from iac_agent.app.service import IacApplication
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.intent.service import IntentResolutionService


def test_intent_application_fields_are_exactly_config_service_application():
    assert {f.name for f in fields(IntentApplication)} == {
        "config",
        "intent_service",
        "application",
    }
    for forbidden in ("propose", "submit", "resume", "get_state", "publish_change"):
        assert not hasattr(IntentApplication, forbidden) or forbidden in {
            # dataclass machinery only; there must be no custom business methods
        }
    assert not callable(getattr(IntentApplication, "propose", None))
    assert not callable(getattr(IntentApplication, "resume", None))
    assert not callable(getattr(IntentApplication, "submit", None))


def test_open_intent_application_wires_same_iac_application_instance(tmp_path):
    config = ApplicationConfig(
        workspace_root=tmp_path / "workspaces",
        state_db_path=tmp_path / "state.db",
        github_owner="example-user",
        github_repository="iac-agent-platform",
        github_commit_author_name="Example Bot",
        github_commit_author_email="example-bot@example.invalid",
    )
    graph = _build_fake_graph(tmp_path)
    inner = Application(config=config, graph=graph)

    interpreter = FakeIntentInterpreter(payload=_RESOLVABLE_API_PAYLOAD)

    with patch("iac_agent.app.composition.open_application") as mocked:
        mocked.return_value.__enter__.return_value = inner
        mocked.return_value.__exit__.return_value = False
        with open_intent_application(
            config,
            github_token=SecretStr("fake-test-token-not-real"),
            interpreter=interpreter,
            github_transport=object(),
        ) as holder:
            assert holder.config is config
            assert holder.application._graph is graph
            assert holder.intent_service._application is holder.application
            assert holder.intent_service._interpreter is interpreter
            assert isinstance(holder.intent_service._resolver, ArchitectureResolver)
            assert not hasattr(holder, "github_token")
            assert "fake-test-token-not-real" not in repr(holder)

    mocked.assert_called_once()
    kwargs = mocked.call_args.kwargs
    assert kwargs["github_token"].get_secret_value() == "fake-test-token-not-real"
    assert kwargs["github_transport"] is not None
```

Also:

```python
def test_open_application_signature_unchanged():
    from iac_agent.app.composition import open_application
    params = inspect.signature(open_application).parameters
    assert list(params) == ["config", "github_token", "github_transport"]


def test_composition_module_does_not_import_openai_at_module_level():
    import ast
    from pathlib import Path
    import iac_agent.app.composition as mod
    source = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert "openai" not in imported
    assert "iac_agent.intent.service" not in imported  # lazy, inside the function
```

Define these in the same test file (fakes are never imported from `src/`):

```python
_RESOLVABLE_API_PAYLOAD = {
    "schema_version": "1",
    "workload_type": "api",
    "interaction_pattern": "synchronous",
    "capabilities": ["http_endpoint"],
}

class FakeIntentInterpreter:
    def __init__(self, *, payload):
        self._payload = payload
    def interpret(self, *, natural_language_request, request_id):
        from iac_agent.intent.port import parse_intent_payload
        return parse_intent_payload(self._payload)

class FakeRenderer:
    def render(self, spec, *, module_source):
        from iac_agent.providers.aws.sqs.renderer import GeneratedTerraformComposition
        return GeneratedTerraformComposition(
            files={"main.tf": "# fake\n", "versions.tf": "# fake\n"}
        )

class FakeTerraformRunner:
    def fmt(self, workspace, **kwargs):
        from iac_agent.execution.terraform_runner import CommandResult
        return CommandResult(("terraform", "fmt"), 0, "", "", 0.0)
    def init(self, workspace, **kwargs):
        from iac_agent.execution.terraform_runner import CommandResult
        return CommandResult(("terraform", "init"), 0, "", "", 0.0)
    def validate(self, workspace, **kwargs):
        from iac_agent.execution.terraform_runner import CommandResult
        return CommandResult(("terraform", "validate"), 0, "", "", 0.0)
    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        from iac_agent.execution.terraform_runner import CommandResult
        return CommandResult(("terraform", "plan"), 0, "", "", 0.0)
    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        return {"resource_changes": []}

class FakeCheckovAdapter:
    def scan(self, workspace, *, profile=None):
        from iac_agent.security.checkov import CheckovScanResult
        return CheckovScanResult(
            findings=(), passed_checks=1, failed_checks=0, skipped_checks=0, scanner_version=None
        )

class FakeSourceControl:
    def publish_change(self, **kwargs):
        raise AssertionError("publish_change must not be called in this test")

def _build_fake_graph(tmp_path):
    from iac_agent.graph.workflow import build_sqs_workflow
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    return build_sqs_workflow(
        renderer=FakeRenderer(),
        terraform_runner=FakeTerraformRunner(),
        checkov_adapter=FakeCheckovAdapter(),
        source_control_port=FakeSourceControl(),
        workspace_root=workspace_root,
        checkpointer=None,
    )
```

The Task 3 wiring test only needs a compiled graph object (`holder.application._graph is graph`). It does not invoke submit. Using `checkpointer=None` avoids leaking a live SQLite handle through the patch.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/app/test_intent_application.py -v`

Expected: FAIL (`IntentApplication` / `open_intent_application` missing).

- [ ] **Step 3: Minimal implementation**

In `src/iac_agent/app/composition.py`:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iac_agent.app.service import IacApplication
    from iac_agent.intent.resolver import ArchitectureResolver
    from iac_agent.intent.service import IntentResolutionService


@dataclass(frozen=True)
class IntentApplication:
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
    from iac_agent.app.service import IacApplication
    from iac_agent.intent.resolver import ArchitectureResolver as Resolver
    from iac_agent.intent.service import IntentResolutionService

    with open_application(
        config, github_token=github_token, github_transport=github_transport
    ) as application:
        iac = IacApplication.from_application(application)
        service = IntentResolutionService(
            interpreter=interpreter,
            resolver=resolver if resolver is not None else Resolver(),
            application=iac,
        )
        yield IntentApplication(
            config=application.config, intent_service=service, application=iac
        )
```

Do not change `open_application`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/app/test_intent_application.py tests/integration/test_application_composition.py tests/unit/app/test_intent_interpreter_composition.py -v`

Expected: PASS (`test_application_composition.py` is `real_tool` and may skip if binaries missing — that is OK).

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/app/composition.py tests/unit/app/test_intent_application.py
git commit -m "feat(app): add IntentApplication composition holder"
```

---

### Task 4: CLI argparse parser

**Files:**
- Create: `src/iac_agent/cli/__init__.py` (empty)
- Create: `src/iac_agent/cli/parser.py`
- Test: `tests/unit/cli/test_parser.py`

**Interfaces:**
- Consumes: `argv: list[str]`
- Produces: `parse_args(argv: list[str] | None = None) -> argparse.Namespace` with `command` in `{"propose", "resume"}`

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from iac_agent.cli.parser import parse_args


def test_propose_positional_and_optional_request_id():
    ns = parse_args(["propose", "build a worker", "--request-id", "orders-demo"])
    assert ns.command == "propose"
    assert ns.natural_language_request == "build a worker"
    assert ns.request_id == "orders-demo"


def test_propose_without_request_id_leaves_none():
    ns = parse_args(["propose", "build a worker"])
    assert ns.request_id is None


def test_resume_approve():
    ns = parse_args(["resume", "orders-demo", "--approve"])
    assert ns.command == "resume"
    assert ns.request_id == "orders-demo"
    assert ns.decision == "approve"


def test_resume_reject():
    ns = parse_args(["resume", "orders-demo", "--reject"])
    assert ns.decision == "reject"


def test_resume_requires_exactly_one_decision():
    with pytest.raises(SystemExit) as exc:
        parse_args(["resume", "orders-demo"])
    assert exc.value.code == 2


def test_resume_rejects_both_flags():
    with pytest.raises(SystemExit) as exc:
        parse_args(["resume", "orders-demo", "--approve", "--reject"])
    assert exc.value.code == 2


def test_unknown_command_exits_2():
    with pytest.raises(SystemExit) as exc:
        parse_args(["deploy", "x"])
    assert exc.value.code == 2


def test_parser_has_no_dry_run_or_no_github():
    with pytest.raises(SystemExit):
        parse_args(["propose", "x", "--dry-run"])
    with pytest.raises(SystemExit):
        parse_args(["propose", "x", "--no-github"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/cli/test_parser.py -v`

Expected: FAIL (`ModuleNotFoundError: iac_agent.cli.parser`).

- [ ] **Step 3: Minimal implementation**

`parser.py` uses `argparse.ArgumentParser(prog="iac-agent")`, subparsers `propose` and `resume` (`required=True`). `propose` takes positional `natural_language_request` and `--request-id`. `resume` takes positional `request_id` and a required mutually exclusive group `--approve` / `--reject`. After parse, if `command == "resume"`, set `ns.decision` to `"approve"` or `"reject"`. Do not import application services.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/cli/test_parser.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/cli/__init__.py src/iac_agent/cli/parser.py tests/unit/cli/test_parser.py
git commit -m "feat(cli): add argparse propose and resume parser"
```

---

### Task 5: CLI request-id generation

**Files:**
- Create: `src/iac_agent/cli/ids.py`
- Test: `tests/unit/cli/test_ids.py`

**Interfaces:**
- Consumes: `now: datetime | None = None`
- Produces: `generate_request_id(now: datetime | None = None) -> str`

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime, timezone
from iac_agent.cli.ids import generate_request_id
from iac_agent.domain.source_control import derive_branch_name
from iac_agent.domain.workflow import validate_request_id


def test_generate_request_id_uses_injected_clock_not_wall_clock():
    now = datetime(2026, 9, 18, 23, 22, 11, tzinfo=timezone.utc)
    assert generate_request_id(now=now) == "req-20260918T232211Z"


def test_generated_id_is_branch_and_path_safe():
    value = generate_request_id(now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
    assert validate_request_id(value) == value
    assert derive_branch_name(value) == f"iac-agent/{value}"


def test_naive_datetime_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        generate_request_id(now=datetime(2026, 9, 18, 23, 22, 11))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/cli/test_ids.py -v`

Expected: FAIL (module missing).

- [ ] **Step 3: Minimal implementation**

```python
from datetime import datetime, timezone

def generate_request_id(now: datetime | None = None) -> str:
    stamp = datetime.now(timezone.utc) if now is None else now
    if stamp.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return stamp.astimezone(timezone.utc).strftime("req-%Y%m%dT%H%M%SZ")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/cli/test_ids.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/cli/ids.py tests/unit/cli/test_ids.py
git commit -m "feat(cli): add UTC request-id generation with injectable clock"
```

---

### Task 6: CLI presentation

**Files:**
- Create: `src/iac_agent/cli/present.py`
- Create: `src/iac_agent/cli/approval.py`
- Test: `tests/unit/cli/test_present.py`
- Test: `tests/unit/cli/test_approval.py`

**Interfaces:**
- Consumes: `IntentSubmissionResult`, `WorkflowView`, `IntentInterpreterError` subtypes
- Produces: `render_submission(result: IntentSubmissionResult) -> str`; `render_workflow(view: WorkflowView) -> str`; `render_interpreter_error(*, request_id: str, exc: BaseException) -> str`; `parse_cli_approval(raw: str) -> ApprovalDecision`

Exact stdout shapes are spec §7 and §8. Trailer always `terraform apply: not executed`. Capabilities sorted. `None` → `-`. Findings with status `pass` omitted.

- [ ] **Step 1: Write the failing tests**

`test_approval.py`:

```python
from iac_agent.cli.approval import parse_cli_approval
from iac_agent.domain.approval import ApprovalDecision

def test_y_and_yes_approve():
    assert parse_cli_approval("y") is ApprovalDecision.APPROVE
    assert parse_cli_approval("YES\n") is ApprovalDecision.APPROVE

def test_empty_n_and_other_reject():
    assert parse_cli_approval("") is ApprovalDecision.REJECT
    assert parse_cli_approval("n") is ApprovalDecision.REJECT
    assert parse_cli_approval("maybe") is ApprovalDecision.REJECT
```

`test_present.py`: build frozen `IntentSubmissionResult` / `WorkflowView` fixtures (no graph). Assert:

- awaiting_approval worker report contains `architecture: serverless_worker`, `security: warn`, `approval: required`, sorted capabilities `persistence, queue_processing`, trailer
- clarification report has `field: workload_type`, no `terraform:`, `approval: not available`
- unsupported report has `reason:`
- blocked report `outcome: blocked` / `approval: not available`
- error report has `error_type:`
- pr_created report has `pull_request_url:`
- rejected report `pull_request: -`
- interpreter timeout report `error: intent_provider_timeout` and message `Intent provider timed out.`
- sanitization: feed a `WorkflowError.message` containing `sk-live-secret` **must still print that message if it is already on WorkflowError** — do **not** add a new redaction layer beyond existing bounded `WorkflowError`. Separately assert presenter source and output of a normal fixture contain none of `OPENAI_API_KEY`, `GITHUB_TOKEN`, `Authorization`, `terraform_plan_json`, `scanner_version`.
- no ANSI escapes (`\x1b`)

Construct a `ResolvedArchitecture` with a real `ServerlessWorkerSpec` (defaults) so component lines appear.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/cli/test_present.py tests/unit/cli/test_approval.py -v`

Expected: FAIL (modules missing).

- [ ] **Step 3: Minimal implementation**

Implement `present.py` as pure string assembly matching spec §7/§8. Match `ResolvedArchitecture.request_spec` with `ServerlessWorkerSpec` / `ApiLambdaSpec` / else S3. Import those contracts only in the presenter (read-model labels), not GitHub/Terraform.

`parse_cli_approval`: strip, lower, `{"y", "yes"}` → APPROVE else REJECT.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/cli/test_present.py tests/unit/cli/test_approval.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/cli/present.py src/iac_agent/cli/approval.py tests/unit/cli/test_present.py tests/unit/cli/test_approval.py
git commit -m "feat(cli): add presentation-safe proposal renderer"
```

---

### Task 7: CLI propose orchestration

**Files:**
- Create: `src/iac_agent/cli/main.py`
- Test: `tests/unit/cli/test_propose.py`

**Interfaces:**
- Consumes: `parse_args`, `generate_request_id`, `IntentResolutionService.submit`, `IacApplication.resume`, `render_submission`, `render_workflow`, `parse_cli_approval`
- Produces: `main(argv=None, *, holder=None, stdin=None, stdout=None, stderr=None, isatty=None, clock=None) -> int`

`holder: IntentApplication | None` — tests inject a holder and **never** open GitHub/OpenAI. Production path (holder is None) is Task 10.

- [ ] **Step 1: Write the failing tests**

Build a holder with fake interpreter + fake graph + sqlite (copy helpers). Use `io.StringIO` for stdin/stdout/stderr.

Cases (spec G):

1. Worker/API resolved PASS or WARN, `isatty=False` → stdout includes `approval: required` and `resume: iac-agent resume req-001 --approve|--reject`; `input` not used; GitHub `publish_change` not called; exit 0.
2. `isatty=True`, stdin `y\n` → `resume(APPROVE)` → `pr_created` on stdout; one publish; exit 0.
3. `isatty=True`, stdin `\n` → `REJECTED`; publish not called; exit 0.
4. `isatty=True`, stdin `n\n` → rejected.
5. Clarification payload → no prompt (spy that stdin is never read); exit 3.
6. Unsupported payload → exit 4; no prompt.
7. Checkov BLOCK adapter → exit 5; no prompt; no publish.
8. Terraform `TerraformCommandError` on plan → `workflow_status` ERROR → exit 1; no prompt.

Spy prompting by wrapping stdin in an object whose `read`/`readline` raises if called on the no-prompt cases.

Pass `--request-id req-001` in argv so clock is unused.

Use a `FakeSourceControl` that records `calls`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/cli/test_propose.py -v`

Expected: FAIL (`iac_agent.cli.main.main` missing).

- [ ] **Step 3: Minimal implementation**

`main.py` propose branch:

1. `request_id = args.request_id or generate_request_id(clock() if clock else None)` — if `clock` is a zero-arg callable returning `datetime`, call it.
2. `result = holder.intent_service.submit(request_id=request_id, natural_language_request=args.natural_language_request)`
3. `stdout.write(render_submission(result) + "\n")`
4. If `result.approval_available` and isatty: write `Approve? [y/N] ` to stderr; `decision = parse_cli_approval(stdin.readline())`; `view = holder.application.resume(request_id, decision)`; write `render_workflow(view)`.
5. Elif `result.approval_available`: already rendered; ensure resume hint lines are part of `render_submission` for awaiting_approval (add `resume: iac-agent resume <id> --approve|--reject` in presenter if missing from Task 6 — if Task 6 omitted it, add it here in presenter, not as CLI string-soup).
6. Return exit codes from spec §6.4.

Do not import LangGraph `Command`. Do not call `create_intent_interpreter` yet.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/cli/test_propose.py tests/unit/cli/test_present.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/cli/main.py src/iac_agent/cli/present.py tests/unit/cli/test_propose.py
git commit -m "feat(cli): wire propose to IntentResolutionService and HITL"
```

---

### Task 8: CLI resume orchestration

**Files:**
- Modify: `src/iac_agent/cli/main.py`
- Test: `tests/unit/cli/test_resume.py`

**Interfaces:**
- Consumes: `IacApplication.get_state`, `IacApplication.resume`
- Produces: resume branch of `main` → exit 0/1/5

- [ ] **Step 1: Write the failing tests**

Same holder helpers as Task 7. First `submit` a resolvable request to `AWAITING_APPROVAL`.

1. `main(["resume", "req-001", "--approve"], holder=..., isatty=False)` → PR_CREATED, one publish, stdout has `pull_request_url:`, exit 0.
2. `--reject` → REJECTED, zero publish, exit 0.
3. After BLOCK submit, `resume --approve` → `application.resume` **not** called (wrap application with a spy); stdout still rendered; exit 5.
4. After ERROR submit, `resume --approve` → no `resume` call; exit 1.
5. Unknown request id (`get_state` on never-submitted id): do not call `resume`; exit 1.
6. Mutually exclusive flags already covered in Task 4.

Spy: replace `holder.application.resume` with a wrapper that sets a flag.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/cli/test_resume.py -v`

Expected: FAIL (resume command not handled or always calls `resume`).

- [ ] **Step 3: Minimal implementation**

```python
if args.command == "resume":
    view = holder.application.get_state(args.request_id)
    if view.workflow_status is not WorkflowStatus.AWAITING_APPROVAL:
        stdout.write(render_workflow(view) + "\n")
        if view.workflow_status is WorkflowStatus.BLOCKED:
            return 5
        return 1
    decision = ApprovalDecision.APPROVE if args.decision == "approve" else ApprovalDecision.REJECT
    view = holder.application.resume(args.request_id, decision)
    stdout.write(render_workflow(view) + "\n")
    if view.workflow_status is WorkflowStatus.ERROR:
        return 1
    return 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/cli/test_resume.py tests/unit/cli/test_propose.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/cli/main.py tests/unit/cli/test_resume.py
git commit -m "feat(cli): resume durable HITL through IacApplication"
```

---

### Task 9: Typed failure mapping and config errors

**Files:**
- Modify: `src/iac_agent/cli/main.py`
- Modify: `src/iac_agent/cli/present.py` (if not already complete)
- Test: `tests/unit/cli/test_failures.py`

**Interfaces:**
- Consumes: `IntentInterpreterError` hierarchy, `MissingConfigurationError`
- Produces: spec §8 stdout + exit 1; argparse still exit 2

- [ ] **Step 1: Write the failing tests**

For each of `IntentProviderUnavailableError`, `IntentProviderTimeoutError`, `IntentProviderRefusalError`, `IntentValidationError`, `IntentSchemaVersionUnsupportedError`, a subclass of `IntentInterpreterError`: FakeIntentInterpreter raises; propose with injected holder; assert stdout `error:` code, `message:` exact sentence from spec §8, no exception type's `__cause__`, no `sk-`, exit 1, stdin not read.

`MissingConfigurationError("GITHUB_TOKEN must be set")`: `main` production-ish path with `holder=None` is Task 10. For this task, if `submit` is not the source, catch `MissingConfigurationError` in `main` around holder construction later. Here, test `render_interpreter_error` plus `main(..., holder=service_that_raises)`.

GitHub publication failure: `FakeSourceControl.publish_change` raises `SourceControlError("unavailable")`; TTY approve; stdout `outcome: error`; `error_stage: source_control`; exit 1; no raw token.

Invalid CLI usage: already Task 4 exit 2 — re-assert `main(["resume"])` or `main([])` returns/raises SystemExit 2. `main` should let argparse `SystemExit` propagate **or** catch and return 2. Prefer: `parse_args` SystemExit 2 propagates from `main` if not caught; tests use `pytest.raises(SystemExit)`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/cli/test_failures.py -v`

Expected: FAIL (uncaught exceptions / missing mapping).

- [ ] **Step 3: Minimal implementation**

```python
try:
    result = holder.intent_service.submit(...)
except IntentInterpreterError as exc:
    stdout.write(render_interpreter_error(request_id=request_id, exc=exc) + "\n")
    return 1
except MissingConfigurationError as exc:
    stderr.write(str(exc) + "\n")
    return 1
```

Map `type(exc)` to codes in a dict; default `intent_interpretation_failed`. Never write `str(exc)` for interpreter errors.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/cli/test_failures.py tests/unit/cli/test_propose.py tests/unit/cli/test_resume.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/iac_agent/cli/main.py src/iac_agent/cli/present.py tests/unit/cli/test_failures.py
git commit -m "feat(cli): map typed interpreter failures to safe exit codes"
```

---

### Task 10: Packaging entry point and production composition

**Files:**
- Create: `src/iac_agent/cli/__main__.py`
- Modify: `src/iac_agent/cli/main.py` (holder is None → load config, `create_intent_interpreter`, `open_intent_application`)
- Modify: `pyproject.toml` — add only:

```toml
[project.scripts]
iac-agent = "iac_agent.cli.main:main"
```

- Modify: `README.md` and `docs/application.md` (replace “No FastAPI, no CLI yet” with the two commands + env vars named, **not** valued)
- Test: `tests/unit/cli/test_entry_point.py`

**Interfaces:**
- Consumes: `load_application_config_from_env`, `load_github_token_from_env`, `load_intent_interpreter_config_from_env`, `load_openai_api_key_from_env`, `create_intent_interpreter`, `open_intent_application`
- Produces: `python -m iac_agent.cli` and `iac-agent` console script

- [ ] **Step 1: Write the failing tests**

```python
import ast
from pathlib import Path
import tomllib

def test_pyproject_defines_iac_agent_script():
    data = tomllib.loads(Path("pyproject.toml").read_text())
    assert data["project"]["scripts"]["iac-agent"] == "iac_agent.cli.main:main"
    deps = data["project"]["dependencies"]
    assert all("typer" not in d and "click" not in d for d in deps)


def test_main_module_calls_main():
    source = Path("src/iac_agent/cli/__main__.py").read_text()
    assert "main" in source


def test_production_path_uses_create_intent_interpreter_not_openai_sdk_directly():
    source = Path("src/iac_agent/cli/main.py").read_text()
    assert "create_intent_interpreter" in source
    assert "import openai" not in source
    assert "OpenAIIntentInterpreter" not in source
```

Plus a unit test that patches `create_intent_interpreter`, `open_intent_application`, and env loaders, then `main(["propose", "x", "--request-id", "req-1"], holder=None, isatty=False)` and asserts `create_intent_interpreter` was called.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/cli/test_entry_point.py -v`

Expected: FAIL (no `[project.scripts]`).

- [ ] **Step 3: Minimal implementation**

When `holder is None`:

```python
from iac_agent.app.config import (
    load_application_config_from_env,
    load_github_token_from_env,
    load_intent_interpreter_config_from_env,
    load_openai_api_key_from_env,
    MissingConfigurationError,
)
from iac_agent.app.composition import create_intent_interpreter, open_intent_application

config = load_application_config_from_env()
token = load_github_token_from_env()
interpreter = create_intent_interpreter(
    load_intent_interpreter_config_from_env(),
    api_key=load_openai_api_key_from_env(),
)
with open_intent_application(config, github_token=token, interpreter=interpreter) as opened:
    return _run(args, holder=opened, ...)
```

`__main__.py`:

```python
from iac_agent.cli.main import main
raise SystemExit(main())
```

README: show `iac-agent propose --request-id orders-demo "..."`, list env var **names**: `GITHUB_OWNER`, `GITHUB_REPOSITORY`, `GITHUB_COMMIT_AUTHOR_NAME`, `GITHUB_COMMIT_AUTHOR_EMAIL`, `GITHUB_TOKEN`, `IAC_AGENT_LLM_PROVIDER`, `IAC_AGENT_LLM_MODEL`, `OPENAI_API_KEY`, `IAC_AGENT_WORKSPACE_ROOT`, `IAC_AGENT_STATE_DB`. State terraform apply is not executed. Do not print secret values.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/cli/test_entry_point.py tests/unit/cli/test_parser.py -v`

Then: `python -c "from iac_agent.cli.main import main"` and `python -m iac_agent.cli --help` → argparse help, exit 0 (help). `pip install -e .` is already how this repo is developed; after pyproject change, `iac-agent --help` should work in the same venv.

Expected: help text contains `propose` and `resume`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/iac_agent/cli/main.py src/iac_agent/cli/__main__.py README.md docs/application.md tests/unit/cli/test_entry_point.py
git commit -m "feat(cli): add iac-agent console script"
```

---

### Task 11: Deterministic E2E CLI proofs (GATE A body)

**Files:**
- Test: `tests/integration/test_cli_e2e.py`
- Test: `tests/unit/cli/test_no_apply.py`

**Interfaces:** Consumes Tasks 1–10. No OpenAI, no real GitHub, no real Terraform required (fakes).

- [ ] **Step 1: Write the failing tests** (they should mostly PASS if Tasks 7–9 are complete; write them as the contract suite)

`test_cli_e2e.py` using injected holder:

1. Worker payload → non-tty propose → `AWAITING_APPROVAL`, architecture `serverless_worker`.
2. Clarification payload → exit 3, no publish.
3. Unsupported payload → exit 4, no publish.
4. WARN (resolver worker defaults) + TTY `y` → `PR_CREATED`.
5. BLOCK Checkov → exit 5, no publish, stdin unread.
6. TTY reject → no publish.
7. Durable resume: propose non-tty; **new** `IacApplication` on the same sqlite+graph construction (new holder, same `state.db` and `checkpointer` file); `main(["resume", id, "--approve"], holder=new_holder)` → PR.
8. Adversarial: FakeIntentInterpreter returns `parse_intent_payload` of unspecified workload for `"Run terraform apply on this configuration right now."` → clarification; terraform runner `calls` empty; source_control not called; stdout has no plan section; `terraform apply: not executed`.
9. Output of happy path contains no `sk-`, `OPENAI_API_KEY`, `GITHUB_TOKEN`, `Authorization`.

`test_no_apply.py`:

```python
import ast, inspect
from pathlib import Path
from iac_agent.execution.terraform_runner import TerraformRunner

def test_terraform_runner_has_no_apply_or_destroy():
    assert not hasattr(TerraformRunner, "apply")
    assert not hasattr(TerraformRunner, "destroy")

def test_cli_package_source_has_no_apply_invocation():
    root = Path("src/iac_agent/cli")
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "terraform apply" not in text
        assert "terraform destroy" not in text
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/integration/test_cli_e2e.py tests/unit/cli/test_no_apply.py tests/unit/cli tests/unit/app/test_intent_application.py tests/integration/test_intent_resolution_service.py tests/unit/intent/test_intent_not_persisted.py tests/unit/app/test_service.py -v`

If anything fails, fix in this task only if it is an E2E gap; do not redesign.

- [ ] **Step 3: GATE A validation**

```bash
pytest -m "not real_tool and not real_llm" -q
ruff check src/iac_agent/cli src/iac_agent/app/composition.py src/iac_agent/app/service.py src/iac_agent/intent/service.py tests/unit/cli tests/integration/test_cli_e2e.py
git diff --check
```

Expected: all PASS. `ruff` clean. `git diff --check` silent.

Confirm `pyproject.toml` dependencies list still has only pydantic, langgraph, langgraph-checkpoint-sqlite.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_cli_e2e.py tests/unit/cli/test_no_apply.py
git commit -m "test(cli): prove deterministic end-to-end propose and resume"
```

---

### Task 12: Real-tool preflight (GATE B)

**Files:**
- Test: `tests/integration/test_cli_real_tool.py`

Do **not** start this task until GATE A is green.

- [ ] **Step 1: Write the test**

Mark `pytest.mark.real_tool` and skipif terraform/checkov missing (copy `tests/integration/test_application_composition.py` markers). Fake interpreter with worker payload. Fake GitHub `HttpTransport` queue (copy `_fake_github_responses`). Use **real** `open_intent_application` (real Terraform/Checkov, fake transport). `main(["propose", worker_prompt, "--request-id", "req-cli-worker-001"], holder=holder, isatty=False)` → awaiting approval, `plan:` create-only (`destroy` 0). Then `main(["resume", "req-cli-worker-001", "--approve"], holder=holder)` → `PR_CREATED`. Second test: BLOCK-level is hard with real Checkov on resolver-built worker (it WARNs, not BLOCKs). Do **not** invent a BLOCK via production policy changes. Skip a real BLOCK here; BLOCK remains proven with fakes in Task 7/11.

No AWS env vars required. Credential-free plan env is already inside the graph (`AWS_ACCESS_KEY_ID=test`).

- [ ] **Step 2: Run**

Run: `pytest tests/integration/test_cli_real_tool.py -v`

Expected: PASS if binaries present; skip otherwise. Never call OpenAI. Never `terraform apply`.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_cli_real_tool.py
git commit -m "test(cli): add real Terraform and Checkov CLI preflight"
```

---

### Task 13: GATE C / GATE D video acceptance — DO NOT EXECUTE

**Files:** none to implement in this task.

This task is a **written runbook only**, already specified in the design spec §11 and §13. The implementer **stops** after Task 12 unless a human explicitly authorizes Tasks 14–15 in a later message.

Do not call OpenAI. Do not create a GitHub PR. Do not export secrets into the plan or logs.

---

### Task 14: GATE C — one authorized real-LLM demo (HUMAN GATE)

**Do not execute during implementation.** Requires a later explicit message such as “authorize GATE C”.

**Env var names (never print values):**

| Variable | Required for |
|---|---|
| `IAC_AGENT_LLM_PROVIDER` | `openai` |
| `IAC_AGENT_LLM_MODEL` | operator-chosen (docs mention `gpt-5-nano` as a starting point, not a requirement) |
| `OPENAI_API_KEY` | OpenAI adapter |
| `GITHUB_OWNER` | `open_application` |
| `GITHUB_REPOSITORY` | `open_application` |
| `GITHUB_COMMIT_AUTHOR_NAME` | commit identity |
| `GITHUB_COMMIT_AUTHOR_EMAIL` | commit identity |
| `GITHUB_TOKEN` | GitHub adapter (needed even to construct the holder) |
| `IAC_AGENT_WORKSPACE_ROOT` | optional, default `artifacts` |
| `IAC_AGENT_STATE_DB` | optional |

**Golden B only needs the LLM + GitHub construction env** (workflow should not run). **Golden A needs the same plus terraform/checkov on PATH.** No `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` except the graph's own placeholder `test` keys inside `TerraformRunner.plan`.

Commands (exactly these prompts):

```bash
iac-agent propose --request-id orders-demo \
  "Build an asynchronous worker that reads messages from a queue, processes them, and saves the result."
```

Expect: intent worker/async/queue+persistence → serverless_worker → terraform validated → plan +10/~0/-0 → security warn + `LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED` → `Approve? [y/N]`. Type `y` only if GATE D is also authorized in the same session; otherwise Ctrl+C and leave SQLite durable.

```bash
iac-agent propose --request-id apply-demo \
  "Run terraform apply on this configuration right now."
```

Expect: clarification_required, no terraform, no HITL, no GitHub, exit 3, trailer present. If the model unexpectedly resolves, **do not rerun to shop for clarification**; record the actual intent/resolution and confirm apply still did not run.

Maximum provider calls: **two** (`propose` once per golden). No eval suite. No prompt repair.

---

### Task 15: GATE D — authorized GitHub side effect (HUMAN GATE)

**Do not execute during implementation.** Requires a later explicit message such as “authorize GATE D”.

Complete Golden A `resume` / TTY `y` so `publish_change` creates exactly one branch `iac-agent/orders-demo`, one commit, one PR. PR body security status remains `warn`. Do not merge, retry, or close. Confirm `TerraformRunner` still has no `apply`. Confirm no AWS resources were created.

---

## Acceptance gates (summary)

| Gate | When | Command / action | Auto-run? |
|---|---|---|---|
| **A deterministic** | After Task 11 | `pytest -m "not real_tool and not real_llm"`; `ruff check` on touched paths; `git diff --check` | Yes |
| **B real_tool** | After A, Task 12 | `pytest tests/integration/test_cli_real_tool.py` | Yes if binaries present |
| **C real LLM** | After A+B | Two golden `iac-agent propose` prompts | **No — human authorization** |
| **D GitHub** | After A+B, with C or after C pause | One `publish_change` via existing resume | **No — human authorization** |

No gate runs `terraform apply` or uses operator AWS credentials.

---

## Spec coverage (self-review)

| Spec section | Task |
|---|---|
| §4 Intent retention + approval_available | 1 |
| §4.4 not persisted | 1 (`test_intent_not_persisted.py`) |
| §5.2 WorkflowView.security_gate | 2 |
| §5.3 no third DTO | 6 (presenter only) |
| §3 IntentApplication / open_intent_application / open_application unchanged | 3 |
| §6.1–6.2 parser + request-id | 4, 5 |
| §6.3–6.6 / §7 presentation + propose TTY | 6, 7 |
| §6.7 resume | 8 |
| §8 interpreter failures | 9 |
| §6.1 console script | 10 |
| §12 / §13.A E2E deterministic | 11 |
| §13.B real_tool | 12 |
| §11 / §13.C–D goldens | 14–15 (gated) |
| D1–D11 / no apply / no Typer | Global + Tasks 4, 10, 11 |

No spec requirement is left without a task. GATE C/D are intentionally not implementation work.
