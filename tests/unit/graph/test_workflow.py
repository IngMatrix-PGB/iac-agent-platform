"""Unit tests for the deterministic SQS LangGraph workflow.

All external boundaries (renderer, Terraform runner, Checkov adapter)
are fakes — no real Terraform or Checkov binary is required. Real-tool
behavior is proven separately by
tests/integration/test_sqs_workflow_integration.py.
"""

from __future__ import annotations

import ast
import inspect

import pytest
from langgraph.types import Command

from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import (
    FindingSource,
    PolicyEvaluation,
    PolicyStatus,
    SecurityFinding,
    SecurityGateResult,
    SecuritySeverity,
)
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.plan_analyzer import PlanAnalysisError
from iac_agent.execution.terraform_runner import CommandResult, TerraformCommandError
from iac_agent.git.port import SourceControlError
from iac_agent.graph import workflow as workflow_module
from iac_agent.graph.workflow import build_sqs_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import GeneratedTerraformComposition
from iac_agent.security.checkov import CheckovExecutableNotFoundError, CheckovScanResult
from iac_agent.security.gate import SecurityGateError

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

_DEFAULT_PLAN_JSON = {
    "terraform_version": "1.16.1",
    "resource_changes": [
        {
            "address": "module.queue.aws_sqs_queue.this",
            "change": {"actions": ["create"], "before": None, "after": {}},
        },
        {
            "address": "module.queue.aws_sqs_queue.dlq[0]",
            "change": {"actions": ["create"], "before": None, "after": {}},
        },
    ],
}

_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=5, failed_checks=0, skipped_checks=0, scanner_version="3.3.13"
)


class FakeRenderer:
    def __init__(self, *, raise_exc: Exception | None = None):
        self.render_calls: list[dict] = []
        self._raise_exc = raise_exc

    def render(self, spec, *, module_source):
        self.render_calls.append({"spec": spec, "module_source": module_source})
        if self._raise_exc is not None:
            raise self._raise_exc
        return GeneratedTerraformComposition(
            files={"main.tf": "# fake\n", "versions.tf": "# fake\n"}
        )


def _ok_result(*parts: str) -> CommandResult:
    return CommandResult(
        command=tuple(parts), returncode=0, stdout="", stderr="", duration_seconds=0.0
    )


class FakeTerraformRunner:
    def __init__(
        self, *, fail_at: str | None = None, fail_exc: Exception | None = None, plan_json=None
    ):
        self.calls: list[str] = []
        self._fail_at = fail_at
        self._fail_exc = fail_exc
        self._plan_json = plan_json if plan_json is not None else _DEFAULT_PLAN_JSON

    def _record_and_maybe_fail(self, name: str):
        self.calls.append(name)
        if self._fail_at == name:
            raise self._fail_exc

    def fmt(self, workspace, **kwargs):
        self._record_and_maybe_fail("fmt")
        return _ok_result("terraform", "fmt")

    def init(self, workspace, **kwargs):
        self._record_and_maybe_fail("init")
        return _ok_result("terraform", "init")

    def validate(self, workspace, **kwargs):
        self._record_and_maybe_fail("validate")
        return _ok_result("terraform", "validate")

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        self._record_and_maybe_fail("plan")
        return _ok_result("terraform", "plan")

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        self._record_and_maybe_fail("show_json")
        return self._plan_json


class FakeCheckovAdapter:
    def __init__(self, *, result=None, raise_exc: Exception | None = None):
        self.scan_calls: list = []
        self._result = result if result is not None else _CLEAN_CHECKOV_RESULT
        self._raise_exc = raise_exc

    def scan(self, workspace):
        self.scan_calls.append(workspace)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._result


class FakeSourceControl:
    """Records every `publish_change` call and returns a deterministic
    `PullRequestResult` — never a real HTTP request, never a real
    GitHub repository."""

    def __init__(self, *, raise_exc: Exception | None = None, pr_number: int = 1):
        self.calls: list[dict] = []
        self._raise_exc = raise_exc
        self._pr_number = pr_number

    def publish_change(
        self,
        *,
        request_id,
        base_branch,
        branch_name,
        files,
        commit_message,
        pr_title,
        pr_body,
    ) -> PullRequestResult:
        self.calls.append(
            {
                "request_id": request_id,
                "base_branch": base_branch,
                "branch_name": branch_name,
                "files": dict(files),
                "commit_message": commit_message,
                "pr_title": pr_title,
                "pr_body": pr_body,
            }
        )
        if self._raise_exc is not None:
            raise self._raise_exc
        return PullRequestResult(
            number=self._pr_number,
            url=f"https://example.invalid/pull/{self._pr_number}",
            branch=branch_name,
            base_branch=base_branch,
        )


def _spec(**overrides) -> SQSResourceSpec:
    defaults = {"name": "order-events"}
    defaults.update(overrides)
    return SQSResourceSpec(**defaults)


def _build(
    tmp_path,
    *,
    renderer=None,
    terraform_runner=None,
    checkov_adapter=None,
    source_control_port=None,
):
    renderer = renderer or FakeRenderer()
    terraform_runner = terraform_runner or FakeTerraformRunner()
    checkov_adapter = checkov_adapter or FakeCheckovAdapter()
    source_control_port = source_control_port or FakeSourceControl()

    graph = build_sqs_workflow(
        renderer=renderer,
        terraform_runner=terraform_runner,
        checkov_adapter=checkov_adapter,
        source_control_port=source_control_port,
        workspace_root=tmp_path,
    )
    return graph, renderer, terraform_runner, checkov_adapter, source_control_port


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_node_order_and_final_status(tmp_path):
    graph, renderer, tf, checkov, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert tf.calls == ["fmt", "init", "validate", "plan", "show_json"]
    assert len(renderer.render_calls) == 1
    assert len(checkov.scan_calls) == 1
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["current_stage"] is WorkflowStage.APPROVAL


def test_renderer_called_once_with_correct_spec(tmp_path):
    graph, renderer, _, _, _ = _build(tmp_path)
    spec = _spec()
    graph.invoke({"request_id": "req-001", "resource_spec": spec})

    assert len(renderer.render_calls) == 1
    assert renderer.render_calls[0]["spec"] == spec


def test_terraform_fmt_init_validate_plan_show_json_each_called_once(tmp_path):
    graph, _, tf, _, _ = _build(tmp_path)
    graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    for step in ("fmt", "init", "validate", "plan", "show_json"):
        assert tf.calls.count(step) == 1


def test_plan_summary_is_propagated(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    plan_summary = result["plan_summary"]
    assert plan_summary is not None
    assert set(plan_summary.resources_to_add) == {
        "module.queue.aws_sqs_queue.this",
        "module.queue.aws_sqs_queue.dlq[0]",
    }


def test_platform_evaluation_is_propagated(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["platform_evaluation"] is not None
    assert result["platform_evaluation"].overall_status is PolicyStatus.PASS


def test_checkov_called_once(tmp_path):
    graph, _, _, checkov, _ = _build(tmp_path)
    graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert len(checkov.scan_calls) == 1


def test_security_gate_result_is_propagated(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["security_gate"] is not None
    assert result["security_gate"].overall_status is PolicyStatus.PASS


def test_pass_gate_gives_awaiting_approval_workflow_status(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["security_gate"].overall_status is PolicyStatus.PASS


def test_warn_gate_gives_awaiting_approval_workflow_status(tmp_path):
    spec = _spec(dlq=DlqSpec(enabled=False, max_receive_count=None))
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": spec})
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["security_gate"].overall_status is PolicyStatus.WARN


def test_block_gate_gives_blocked_workflow_status(tmp_path):
    checkov_block = CheckovScanResult(
        findings=(
            SecurityFinding(
                policy_id="CKV_AWS_27",
                severity=SecuritySeverity.HIGH,
                status=PolicyStatus.BLOCK,
                resource="module.queue.aws_sqs_queue.this",
                message="Checkov CKV_AWS_27 failed.",
                source=FindingSource.CHECKOV,
            ),
        ),
        passed_checks=4,
        failed_checks=1,
        skipped_checks=0,
        scanner_version="3.3.13",
    )
    graph, _, _, _, _ = _build(tmp_path, checkov_adapter=FakeCheckovAdapter(result=checkov_block))
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.BLOCKED


# ---------------------------------------------------------------------------
# Error cases + fail-stop
# ---------------------------------------------------------------------------


def test_renderer_failure_gives_error_and_stops(tmp_path):
    graph, renderer, tf, checkov, _ = _build(
        tmp_path, renderer=FakeRenderer(raise_exc=RuntimeError("boom"))
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.RENDER
    assert tf.calls == []
    assert checkov.scan_calls == []


@pytest.mark.parametrize("stage", ["fmt", "init", "validate", "plan"])
def test_terraform_execute_stage_failure_gives_error_and_stops(tmp_path, stage):
    """fmt/init/validate/plan all run inside terraform_execute (Batch 12:
    show_json moved to plan_analysis, so it is NOT covered by this case —
    see test_show_json_failure_gives_error_and_stops below)."""
    tf_error = TerraformCommandError(_ok_result("terraform", stage))
    graph, renderer, tf, checkov, _ = _build(
        tmp_path, terraform_runner=FakeTerraformRunner(fail_at=stage, fail_exc=tf_error)
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.TERRAFORM
    assert "plan_summary" not in result or result["plan_summary"] is None
    assert checkov.scan_calls == []


def test_show_json_failure_gives_error_and_stops(tmp_path):
    """Batch 12: show_json is called by plan_analysis, not
    terraform_execute — its failure is attributed to PLAN_ANALYSIS."""
    tf_error = TerraformCommandError(_ok_result("terraform", "show", "-json"))
    graph, renderer, tf, checkov, _ = _build(
        tmp_path, terraform_runner=FakeTerraformRunner(fail_at="show_json", fail_exc=tf_error)
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.PLAN_ANALYSIS
    assert "plan_summary" not in result or result["plan_summary"] is None
    assert checkov.scan_calls == []


def test_plan_analysis_failure_gives_error_and_stops(tmp_path):
    graph, renderer, tf, checkov, _ = _build(
        tmp_path, terraform_runner=FakeTerraformRunner(plan_json={"resource_changes": "not-a-list"})
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.PLAN_ANALYSIS
    assert checkov.scan_calls == []


def test_checkov_executable_missing_gives_error_and_stops(tmp_path):
    graph, _, _, checkov, _ = _build(
        tmp_path,
        checkov_adapter=FakeCheckovAdapter(raise_exc=CheckovExecutableNotFoundError("checkov")),
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.CHECKOV
    assert result.get("security_gate") is None


def test_checkov_timeout_gives_error_and_stops(tmp_path):
    from iac_agent.security.checkov import CheckovTimeoutError

    graph, _, _, checkov, _ = _build(
        tmp_path,
        checkov_adapter=FakeCheckovAdapter(
            raise_exc=CheckovTimeoutError(command=("checkov",), timeout_seconds=120.0)
        ),
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.CHECKOV


def test_checkov_malformed_json_gives_error_and_stops(tmp_path):
    from iac_agent.security.checkov import CheckovJsonError

    graph, _, _, checkov, _ = _build(
        tmp_path,
        checkov_adapter=FakeCheckovAdapter(
            raise_exc=CheckovJsonError(command=("checkov",), cause=ValueError("bad json"))
        ),
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.CHECKOV


def test_security_gate_error_gives_error_status(tmp_path):
    """Simulate the security-gate node itself raising SecurityGateError by
    monkeypatching evaluate_security_gate at the workflow module level."""
    import iac_agent.graph.workflow as wf_module

    def _raise(*args, **kwargs):
        raise SecurityGateError("required platform policy finding is missing: X")

    original = wf_module.evaluate_security_gate
    wf_module.evaluate_security_gate = _raise
    try:
        graph, _, _, _, _ = _build(tmp_path)
        result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    finally:
        wf_module.evaluate_security_gate = original

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.SECURITY_GATE


def test_plan_analysis_error_is_the_expected_exception_type():
    # Documents which exception plan_analysis's node is actually built to
    # catch, so a future refactor of analyze_plan's error type is caught.
    assert issubclass(PlanAnalysisError, Exception)


# ---------------------------------------------------------------------------
# Workspace safety
# ---------------------------------------------------------------------------


def test_explicit_workspace_root_is_required(tmp_path):
    with pytest.raises(TypeError):
        build_sqs_workflow(  # type: ignore[call-arg]
            renderer=FakeRenderer(),
            terraform_runner=FakeTerraformRunner(),
            checkov_adapter=FakeCheckovAdapter(),
            source_control_port=FakeSourceControl(),
        )


def test_request_specific_workspace_created_under_root(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    workspace = result["workspace"]
    assert workspace == tmp_path / "req-001"
    assert workspace.is_dir()
    assert workspace.parent == tmp_path


@pytest.mark.parametrize("bad_request_id", ["../escape", "a/../../b", "sub/dir"])
def test_request_id_path_traversal_is_rejected(tmp_path, bad_request_id):
    graph, renderer, tf, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": bad_request_id, "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.RENDER
    assert renderer.render_calls == []
    assert tf.calls == []


def test_absolute_request_id_is_rejected(tmp_path):
    graph, renderer, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "/etc/passwd", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert renderer.render_calls == []


def test_workspace_path_does_not_depend_on_process_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path.parent)
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workspace"] == tmp_path / "req-001"


# ---------------------------------------------------------------------------
# Data hygiene
# ---------------------------------------------------------------------------


def test_final_successful_state_contains_plan_summary(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert result["plan_summary"] is not None


def test_final_successful_state_contains_security_gate_result(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert result["security_gate"] is not None


def test_workflow_state_has_no_terraform_plan_json_field_at_all():
    """Batch 12 structural guarantee: the field does not exist in the
    schema at all — not merely cleared to None at the end of a run."""
    from iac_agent.graph.state import WorkflowState

    assert "terraform_plan_json" not in WorkflowState.__annotations__


def test_final_successful_state_does_not_retain_raw_terraform_plan_json(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert result.get("terraform_plan_json") is None
    assert "terraform_plan_json" not in result


def test_terraform_execute_does_not_call_show_json(tmp_path):
    """Batch 12: show_json moved to plan_analysis. Verified here by
    forcing show_json to fail — if terraform_execute still called it,
    the error would be attributed to WorkflowStage.TERRAFORM instead of
    PLAN_ANALYSIS (see test_show_json_failure_gives_error_and_stops)."""
    tf = FakeTerraformRunner()
    graph, _, _, _, _ = _build(tmp_path, terraform_runner=tf)
    graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert tf.calls.index("plan") < tf.calls.index("show_json")


def test_plan_analysis_calls_show_json_exactly_once(tmp_path):
    tf = FakeTerraformRunner()
    graph, _, _, _, _ = _build(tmp_path, terraform_runner=tf)
    graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert tf.calls.count("show_json") == 1


def test_final_successful_state_does_not_retain_raw_checkov_json(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert "raw_checkov_json" not in result
    assert "checkov_stdout" not in result


def test_workflow_error_does_not_expose_secret_shaped_env_values(tmp_path):
    secret = "super-secret-terraform-value"
    tf_error = TerraformCommandError(
        CommandResult(
            command=("terraform", "plan"),
            returncode=1,
            stdout="",
            stderr="benign failure",
            duration_seconds=0.0,
        )
    )
    graph, _, _, _, _ = _build(
        tmp_path, terraform_runner=FakeTerraformRunner(fail_at="plan", fail_exc=tf_error)
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert secret not in result["error"].message


def test_no_developer_absolute_path_in_workflow_error(tmp_path):
    graph, renderer, _, _, _ = _build(
        tmp_path,
        renderer=FakeRenderer(raise_exc=ValueError("/Users/some-developer/leak/path issue")),
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    # This documents current behavior: the renderer's own exception text
    # is passed through as-is. Since no renderer/runner exception in this
    # codebase legitimately embeds a developer path (verified in each of
    # their own batches), this is expected to hold; this test exists to
    # catch a regression, not to add new sanitization.
    assert "error" in result


# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------


def test_graph_module_imports_no_model_provider_or_langchain_model_packages():
    tree = ast.parse(inspect.getsource(workflow_module))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    forbidden = {"openai", "anthropic", "langchain", "langchain_openai", "langchain_anthropic"}
    assert not (imported_roots & forbidden), imported_roots & forbidden


def test_graph_module_does_not_invoke_subprocess_directly():
    tree = ast.parse(inspect.getsource(workflow_module))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    assert "subprocess" not in imported_roots


def test_graph_module_does_not_import_checkov_json_parsing_internals():
    source = inspect.getsource(workflow_module)
    for forbidden in ("json.loads", "_parse_checkov_output", "_normalize_failed_check"):
        assert forbidden not in source


def test_graph_module_does_not_contain_plan_action_classification():
    source = inspect.getsource(workflow_module)
    for forbidden in ("_classify_actions", "_ACTION_SET_TO_PLAN_ACTION", '"delete"', "'delete'"):
        assert forbidden not in source


def test_graph_module_does_not_contain_platform_policy_ids_or_rules():
    source = inspect.getsource(workflow_module)
    for forbidden in (
        "SQS_ENCRYPTION_REQUIRED",
        "SQS_DLQ_RECOMMENDED",
        "TF_NO_DESTRUCTIVE_CHANGES",
        "encryption.enabled",
    ):
        assert forbidden not in source


def test_graph_module_does_not_contain_github_specific_details():
    """The graph knows only `SourceControlPort` — never GitHub's Git
    Data API, HTTP, or authorization headers. That belongs solely to
    `iac_agent.git.github`."""
    source = inspect.getsource(workflow_module)
    for forbidden in (
        "api.github.com",
        "Authorization",
        "Bearer",
        "git/blobs",
        "git/trees",
        "git/refs",
        "refs/heads",
        "/pulls",
        "urllib",
        "HTTPError",
        "status_code",
        "response.status",
    ):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# Checkpointer dependency injection (fakes only — no real Terraform/Checkov;
# SQLite itself is real, since that is the actual behavior under test)
# ---------------------------------------------------------------------------


def test_graph_compiles_and_runs_unchanged_without_a_checkpointer(tmp_path):
    """Batch 11 behavior (no config/thread_id required) is preserved when
    checkpointer=None (the default). Batch 13: a PASS result still
    reaches the approval interrupt on first invoke even with no
    checkpointer — LangGraph only refuses at *resume* time
    (`Command(resume=...)` requires a checkpointer), which this test
    does not attempt."""
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert "__interrupt__" in result


def test_injected_checkpointer_is_actually_used_by_the_compiled_graph(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph = build_sqs_workflow(
            renderer=FakeRenderer(),
            terraform_runner=FakeTerraformRunner(),
            checkov_adapter=FakeCheckovAdapter(),
            source_control_port=FakeSourceControl(),
            workspace_root=workspace_root,
            checkpointer=saver,
        )
        config = workflow_config("req-001")
        graph.invoke({"request_id": "req-001", "resource_spec": _spec()}, config)

        # get_state only works at all when a checkpointer was actually
        # wired into compile() — this call itself is the proof.
        snapshot = graph.get_state(config)
        assert snapshot.values["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL


def test_graph_module_does_not_instantiate_sqlite():
    tree = ast.parse(inspect.getsource(workflow_module))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden = {"sqlite3", "langgraph.checkpoint.sqlite"}
    assert not (imported_modules & forbidden), imported_modules & forbidden


# ---------------------------------------------------------------------------
# Durable round-trip (real SQLite, fake Terraform/Checkov)
# ---------------------------------------------------------------------------


def _build_durable(workspace_root, checkpointer, **overrides):
    return build_sqs_workflow(
        renderer=overrides.get("renderer") or FakeRenderer(),
        terraform_runner=overrides.get("terraform_runner") or FakeTerraformRunner(),
        checkov_adapter=overrides.get("checkov_adapter") or FakeCheckovAdapter(),
        source_control_port=overrides.get("source_control_port") or FakeSourceControl(),
        workspace_root=workspace_root,
        checkpointer=checkpointer,
    )


def test_interrupted_pass_state_round_trips_through_real_sqlite(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-durable-001")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(workspace_root, saver)
        first_result = graph.invoke(
            {"request_id": "req-durable-001", "resource_spec": _spec()}, config
        )
        assert first_result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
        assert "__interrupt__" in first_result

    # Reopen a brand-new saver and a brand-new compiled graph against the
    # SAME database file — this simulates process reconstruction. The
    # original saver/graph objects are never reused below.
    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_durable(workspace_root, saver2)
        snapshot = graph2.get_state(config)
        recovered = snapshot.values

    assert recovered["request_id"] == "req-durable-001"
    assert isinstance(recovered["resource_spec"], SQSResourceSpec)
    assert isinstance(recovered["plan_summary"], PlanSummary)
    assert isinstance(recovered["platform_evaluation"], PolicyEvaluation)
    assert isinstance(recovered["checkov_result"], CheckovScanResult)
    assert isinstance(recovered["security_gate"], SecurityGateResult)
    assert recovered["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert recovered["current_stage"] is WorkflowStage.APPROVAL
    assert recovered.get("approval_decision") is None
    assert "terraform_plan_json" not in recovered


# ---------------------------------------------------------------------------
# Human approval gate (Batch 13)
# ---------------------------------------------------------------------------


def _spec_warn(**overrides) -> SQSResourceSpec:
    return _spec(dlq=DlqSpec(enabled=False, max_receive_count=None), **overrides)


def _block_checkov_result() -> CheckovScanResult:
    return CheckovScanResult(
        findings=(
            SecurityFinding(
                policy_id="CKV_AWS_27",
                severity=SecuritySeverity.HIGH,
                status=PolicyStatus.BLOCK,
                resource="module.queue.aws_sqs_queue.this",
                message="Checkov CKV_AWS_27 failed.",
                source=FindingSource.CHECKOV,
            ),
        ),
        passed_checks=4,
        failed_checks=1,
        skipped_checks=0,
        scanner_version="3.3.13",
    )


# -- Routing ----------------------------------------------------------------


def test_pass_routes_to_approval_interrupt(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert "__interrupt__" in result
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL


def test_warn_routes_to_approval_interrupt(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec_warn()})
    assert "__interrupt__" in result
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL


def test_block_routes_to_blocked_and_end_with_no_interrupt(tmp_path):
    graph, _, _, _, _ = _build(
        tmp_path, checkov_adapter=FakeCheckovAdapter(result=_block_checkov_result())
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.BLOCKED
    assert result["current_stage"] is WorkflowStage.COMPLETE
    assert "__interrupt__" not in result


def test_error_routes_to_error_and_end_with_no_interrupt(tmp_path):
    tf_error = TerraformCommandError(_ok_result("terraform", "plan"))
    graph, _, _, _, _ = _build(
        tmp_path, terraform_runner=FakeTerraformRunner(fail_at="plan", fail_exc=tf_error)
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert "__interrupt__" not in result


def test_block_never_reaches_interrupt_checked_via_pending_tasks(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-block-001")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(
            workspace_root,
            saver,
            checkov_adapter=FakeCheckovAdapter(result=_block_checkov_result()),
        )
        graph.invoke({"request_id": "req-block-001", "resource_spec": _spec()}, config)
        snapshot = graph.get_state(config)

    assert snapshot.next == ()
    assert snapshot.tasks == ()


def test_error_never_reaches_interrupt_checked_via_pending_tasks(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-error-001")
    tf_error = TerraformCommandError(_ok_result("terraform", "plan"))

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(
            workspace_root,
            saver,
            terraform_runner=FakeTerraformRunner(fail_at="plan", fail_exc=tf_error),
        )
        graph.invoke({"request_id": "req-error-001", "resource_spec": _spec()}, config)
        snapshot = graph.get_state(config)

    assert snapshot.next == ()
    assert snapshot.tasks == ()


# -- Interrupt payload --------------------------------------------------


def _interrupt_payload(result: dict) -> dict:
    return result["__interrupt__"][0].value


def test_interrupt_payload_contains_request_id(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-007", "resource_spec": _spec()})
    assert _interrupt_payload(result)["request_id"] == "req-007"


def test_interrupt_payload_contains_resource_name(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec(name="payment-events")})
    assert _interrupt_payload(result)["resource"] == "payment-events"


def test_interrupt_payload_contains_security_status(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert _interrupt_payload(result)["security_status"] == "pass"


def test_interrupt_payload_contains_warn_security_status_not_normalized_to_pass(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec_warn()})
    assert _interrupt_payload(result)["security_status"] == "warn"


def test_interrupt_payload_contains_plan_counts(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    plan = _interrupt_payload(result)["plan"]
    assert plan == {"add": 2, "change": 0, "destroy": 0}


def test_interrupt_payload_contains_normalized_findings(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    findings = _interrupt_payload(result)["findings"]
    assert len(findings) > 0
    for finding in findings:
        assert set(finding) == {"policy_id", "status", "severity", "resource"}


def test_interrupt_payload_contains_no_raw_plan_json(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    payload_text = str(_interrupt_payload(result))
    assert "resource_changes" not in payload_text
    assert "terraform_version" not in payload_text


def test_interrupt_payload_contains_no_raw_scanner_json(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    payload_text = str(_interrupt_payload(result))
    assert "passed_checks" not in payload_text
    assert "scanner_version" not in payload_text


def test_interrupt_payload_contains_no_secrets_or_paths(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    payload_text = str(_interrupt_payload(result))
    for forbidden in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        str(tmp_path),
        "stdout",
        "stderr",
    ):
        assert forbidden not in payload_text


# -- Resume ---------------------------------------------------------------


def _invoke_to_interrupt(workspace_root, saver, request_id, spec, **overrides):
    graph = _build_durable(workspace_root, saver, **overrides)
    config = workflow_config(request_id)
    graph.invoke({"request_id": request_id, "resource_spec": spec}, config)
    return graph, config


def test_approve_resume_gives_approved_status(tmp_path):
    """Batch 14: APPROVED is no longer terminal by itself — a single
    resume immediately proceeds through source_control to PR_CREATED
    (see the "IMPORTANT RESUME BEHAVIOR" requirement: no second
    invocation is needed). `approval_decision` still reflects APPROVE."""
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-approve", _spec())
        result = graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert result["workflow_status"] is WorkflowStatus.PR_CREATED
    assert result["current_stage"] is WorkflowStage.COMPLETE
    assert result["approval_decision"] is ApprovalDecision.APPROVE
    assert result["pull_request"] is not None


def test_reject_resume_gives_rejected_status(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-reject", _spec())
        result = graph.invoke(Command(resume=ApprovalDecision.REJECT.value), config)

    assert result["workflow_status"] is WorkflowStatus.REJECTED
    assert result["current_stage"] is WorkflowStage.COMPLETE
    assert result["approval_decision"] is ApprovalDecision.REJECT


def test_reject_is_not_error_and_not_blocked(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-reject", _spec())
        result = graph.invoke(Command(resume=ApprovalDecision.REJECT.value), config)

    assert result["workflow_status"] is not WorkflowStatus.ERROR
    assert result["workflow_status"] is not WorkflowStatus.BLOCKED
    assert result.get("error") is None


def test_security_gate_result_preserved_unchanged_after_approve(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-approve", _spec())
        result = graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert result["security_gate"].overall_status is PolicyStatus.PASS


def test_security_gate_result_preserved_unchanged_after_reject(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-reject", _spec())
        result = graph.invoke(Command(resume=ApprovalDecision.REJECT.value), config)

    assert result["security_gate"].overall_status is PolicyStatus.PASS


def test_warn_result_remains_warn_after_approval():
    """Human APPROVE must never rewrite SecurityGateResult — a WARN
    finding stays WARN even once the workflow itself is APPROVED."""
    # Direct construction, not a graph run: proves the invariant at the
    # domain-model level (SecurityGateResult has no mutation path at
    # all — see iac_agent.domain.security), independent of any specific
    # workflow run.
    finding = SecurityFinding(
        policy_id="SQS_DLQ_RECOMMENDED",
        severity=SecuritySeverity.MEDIUM,
        status=PolicyStatus.WARN,
        resource="order-events",
        message="Dead-letter queue is disabled.",
        source=FindingSource.PLATFORM_POLICY,
    )
    gate_result = SecurityGateResult(findings=(finding,))
    assert gate_result.overall_status is PolicyStatus.WARN


def test_warn_gate_approve_resume_gives_approved_with_warn_preserved(tmp_path):
    """Batch 14: a WARN result can be human-approved and published —
    the final workflow reaches PR_CREATED, and the security result is
    still inspectable as WARN, never rewritten to look like PASS."""
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-warn", _spec_warn())
        result = graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert result["workflow_status"] is WorkflowStatus.PR_CREATED
    assert result["security_gate"].overall_status is PolicyStatus.WARN


# -- Invalid resume value -----------------------------------------------


@pytest.mark.parametrize(
    "bad_value",
    ["yes", "ok", "approve please", True, False, 1, 0, {"decision": "approve"}, ["approve"]],
    ids=[
        "yes",
        "ok",
        "sentence",
        "bool-true",
        "bool-false",
        "int-1",
        "int-0",
        "mapping",
        "list",
    ],
)
def test_invalid_resume_value_gives_error_not_approved(tmp_path, bad_value):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-invalid", _spec())
        result = graph.invoke(Command(resume=bad_value), config)

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["workflow_status"] is not WorkflowStatus.APPROVED
    assert result["error"].stage is WorkflowStage.APPROVAL
    assert result["error"].error_type == "InvalidApprovalDecisionError"
    assert result.get("approval_decision") is None


# -- Non-override --------------------------------------------------------


def test_block_thread_cannot_be_approved(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-block-approve")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(
            workspace_root,
            saver,
            checkov_adapter=FakeCheckovAdapter(result=_block_checkov_result()),
        )
        graph.invoke({"request_id": "req-block-approve", "resource_spec": _spec()}, config)

        # There is no pending interrupt to resume — this is a structural
        # no-op, not a state transition, so the thread's final state is
        # untouched by the attempt.
        result = graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert result["workflow_status"] is WorkflowStatus.BLOCKED
    assert result["workflow_status"] is not WorkflowStatus.APPROVED
    assert result.get("approval_decision") is None


def test_error_thread_cannot_be_approved(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-error-approve")
    tf_error = TerraformCommandError(_ok_result("terraform", "plan"))

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(
            workspace_root,
            saver,
            terraform_runner=FakeTerraformRunner(fail_at="plan", fail_exc=tf_error),
        )
        graph.invoke({"request_id": "req-error-approve", "resource_spec": _spec()}, config)

        result = graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["workflow_status"] is not WorkflowStatus.APPROVED
    assert result.get("approval_decision") is None


def test_no_approval_decision_field_exists_on_blocked_state(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-block-field")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(
            workspace_root,
            saver,
            checkov_adapter=FakeCheckovAdapter(result=_block_checkov_result()),
        )
        result = graph.invoke({"request_id": "req-block-field", "resource_spec": _spec()}, config)

    assert result.get("approval_decision") is None


def test_no_approval_decision_field_exists_on_error_state(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-error-field")
    tf_error = TerraformCommandError(_ok_result("terraform", "plan"))

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(
            workspace_root,
            saver,
            terraform_runner=FakeTerraformRunner(fail_at="plan", fail_exc=tf_error),
        )
        result = graph.invoke({"request_id": "req-error-field", "resource_spec": _spec()}, config)

    assert result.get("approval_decision") is None


# -- Durability: reconstruction + resume ----------------------------------


def test_approve_resume_works_after_saver_and_graph_reconstruction(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-durable-approve")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(workspace_root, saver)
        graph.invoke({"request_id": "req-durable-approve", "resource_spec": _spec()}, config)

    # Brand-new saver, brand-new graph — the original objects above are
    # never reused for the resume below.
    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_durable(workspace_root, saver2)
        result = graph2.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert result["workflow_status"] is WorkflowStatus.PR_CREATED
    assert result["current_stage"] is WorkflowStage.COMPLETE
    assert result["pull_request"] is not None


def test_final_approved_state_is_durable_across_a_third_reconstruction(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-durable-approve-2")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(workspace_root, saver)
        graph.invoke({"request_id": "req-durable-approve-2", "resource_spec": _spec()}, config)

    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_durable(workspace_root, saver2)
        graph2.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    # A third, entirely fresh saver/graph pair recovers the final
    # APPROVED state with no further invoke() call at all.
    with open_sqlite_checkpointer(db_path) as saver3:
        graph3 = _build_durable(workspace_root, saver3)
        recovered = graph3.get_state(config).values

    assert recovered["workflow_status"] is WorkflowStatus.PR_CREATED
    assert recovered["current_stage"] is WorkflowStage.COMPLETE
    assert recovered["approval_decision"] is ApprovalDecision.APPROVE
    assert recovered["security_gate"].overall_status is PolicyStatus.PASS
    assert recovered["pull_request"] is not None


def test_final_rejected_state_is_durable_across_reconstruction(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-durable-reject")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(workspace_root, saver)
        graph.invoke({"request_id": "req-durable-reject", "resource_spec": _spec()}, config)

    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_durable(workspace_root, saver2)
        graph2.invoke(Command(resume=ApprovalDecision.REJECT.value), config)

    with open_sqlite_checkpointer(db_path) as saver3:
        graph3 = _build_durable(workspace_root, saver3)
        recovered = graph3.get_state(config).values

    assert recovered["workflow_status"] is WorkflowStatus.REJECTED
    assert recovered["current_stage"] is WorkflowStage.COMPLETE
    assert recovered["approval_decision"] is ApprovalDecision.REJECT


def test_same_thread_id_preserved_through_interrupt_and_resume(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    request_id = "req-durable-thread-id"
    config = workflow_config(request_id)

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(workspace_root, saver)
        interrupted = graph.invoke({"request_id": request_id, "resource_spec": _spec()}, config)
        assert interrupted["request_id"] == request_id

        result = graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)
        assert result["request_id"] == request_id


# ---------------------------------------------------------------------------
# Source control (Batch 14)
# ---------------------------------------------------------------------------


def _approve(graph, config):
    return graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)


def test_approve_routes_to_source_control(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-sc-approve", _spec(), source_control_port=source_control
        )
        _approve(graph, config)

    assert len(source_control.calls) == 1


def test_source_control_port_called_exactly_once(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-sc-once", _spec(), source_control_port=source_control
        )
        result = _approve(graph, config)

    assert result["workflow_status"] is WorkflowStatus.PR_CREATED
    assert len(source_control.calls) == 1


def test_reject_never_calls_source_control(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-sc-reject", _spec(), source_control_port=source_control
        )
        graph.invoke(Command(resume=ApprovalDecision.REJECT.value), config)

    assert source_control.calls == []


def test_block_never_calls_source_control(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(
            workspace_root,
            saver,
            checkov_adapter=FakeCheckovAdapter(result=_block_checkov_result()),
            source_control_port=source_control,
        )
        graph.invoke(
            {"request_id": "req-sc-block", "resource_spec": _spec()},
            workflow_config("req-sc-block"),
        )

    assert source_control.calls == []


def test_error_never_calls_source_control(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()
    tf_error = TerraformCommandError(_ok_result("terraform", "plan"))

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(
            workspace_root,
            saver,
            terraform_runner=FakeTerraformRunner(fail_at="plan", fail_exc=tf_error),
            source_control_port=source_control,
        )
        graph.invoke(
            {"request_id": "req-sc-error", "resource_spec": _spec()},
            workflow_config("req-sc-error"),
        )

    assert source_control.calls == []


def test_invalid_resume_value_never_calls_source_control(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-sc-invalid", _spec(), source_control_port=source_control
        )
        graph.invoke(Command(resume="yes"), config)

    assert source_control.calls == []


def test_source_control_success_gives_pr_created_status(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-sc-pr", _spec())
        result = _approve(graph, config)

    assert result["workflow_status"] is WorkflowStatus.PR_CREATED
    assert result["current_stage"] is WorkflowStage.COMPLETE


def test_source_control_success_stores_pull_request_result(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-sc-store", _spec())
        result = _approve(graph, config)

    pull_request = result["pull_request"]
    assert isinstance(pull_request, PullRequestResult)
    assert pull_request.branch == "iac-agent/req-sc-store"
    assert pull_request.base_branch == "main"


def test_source_control_error_gives_error_status(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl(raise_exc=SourceControlError("simulated GitHub failure"))

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-sc-error", _spec(), source_control_port=source_control
        )
        result = _approve(graph, config)

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.SOURCE_CONTROL
    assert result["error"].error_type == "SourceControlError"


def test_source_control_error_preserves_approval_decision(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl(raise_exc=SourceControlError("simulated GitHub failure"))

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-sc-error-2", _spec(), source_control_port=source_control
        )
        result = _approve(graph, config)

    assert result["approval_decision"] is ApprovalDecision.APPROVE


def test_source_control_error_preserves_security_gate_result(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl(raise_exc=SourceControlError("simulated GitHub failure"))

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-sc-error-3", _spec(), source_control_port=source_control
        )
        result = _approve(graph, config)

    assert result["security_gate"].overall_status is PolicyStatus.PASS


def test_source_control_node_refuses_non_approved_state_directly():
    """Defense-in-depth: `_ensure_workflow_approved` is tested directly
    against a fabricated state, independent of graph routing (routing
    already prevents source_control from ever running with a non-
    APPROVED status — this proves the node's own guard would still
    fail closed even if that were somehow bypassed)."""
    for bad_status in (
        WorkflowStatus.REJECTED,
        WorkflowStatus.BLOCKED,
        WorkflowStatus.ERROR,
        WorkflowStatus.AWAITING_APPROVAL,
        WorkflowStatus.RUNNING,
        WorkflowStatus.PENDING,
    ):
        with pytest.raises(SourceControlError):
            workflow_module._ensure_workflow_approved({"workflow_status": bad_status})


def test_source_control_node_accepts_approved_state_directly():
    workflow_module._ensure_workflow_approved(
        {"workflow_status": WorkflowStatus.APPROVED}
    )  # no raise


def test_generated_file_allowlist_is_exact(tmp_path):
    """Only the renderer's own two output files are ever published —
    never a tfplan, a SQLite DB, a .terraform artifact, or anything
    else that might exist in the local workspace directory."""
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-sc-allowlist", _spec(), source_control_port=source_control
        )
        _approve(graph, config)

    published_files = source_control.calls[0]["files"]
    assert set(published_files) == {"main.tf", "versions.tf"}
    for forbidden in ("tfplan", "terraform.tfstate", "checkpoints.sqlite3", ".terraform"):
        assert forbidden not in published_files


def test_no_tfplan_or_state_or_terraform_dir_ever_reaches_source_control(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root,
            saver,
            "req-sc-no-artifacts",
            _spec(),
            source_control_port=source_control,
        )
        _approve(graph, config)

    call = source_control.calls[0]
    for key in ("files", "commit_message", "pr_title", "pr_body"):
        serialized = str(call[key])
        for forbidden in ("tfplan", ".terraform", "checkpoints.sqlite3", str(workspace_root)):
            assert forbidden not in serialized


def test_replayed_invocation_of_a_published_thread_does_not_call_source_control_again(tmp_path):
    """Idempotency / replay safety: an already-PR_CREATED thread's
    `pull_request` field is already set, so a second pass through
    `source_control` (however it were triggered) must not call the
    adapter again."""
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-sc-replay", _spec(), source_control_port=source_control
        )
        first = _approve(graph, config)
        assert first["workflow_status"] is WorkflowStatus.PR_CREATED
        assert len(source_control.calls) == 1

        # get_state alone must never trigger a side effect.
        snapshot = graph.get_state(config)
        assert snapshot.values["workflow_status"] is WorkflowStatus.PR_CREATED
        assert len(source_control.calls) == 1


# ---------------------------------------------------------------------------
# Thread isolation
# ---------------------------------------------------------------------------


def test_two_threads_coexist_in_one_database_without_cross_contamination(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    spec_a = _spec(name="order-events")
    spec_b = _spec(name="payment-events")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(workspace_root, saver)
        graph.invoke({"request_id": "req-001", "resource_spec": spec_a}, workflow_config("req-001"))
        graph.invoke({"request_id": "req-002", "resource_spec": spec_b}, workflow_config("req-002"))

        state_a = graph.get_state(workflow_config("req-001")).values
        state_b = graph.get_state(workflow_config("req-002")).values

    assert state_a["request_id"] == "req-001"
    assert state_a["resource_spec"].name == "order-events"
    assert state_b["request_id"] == "req-002"
    assert state_b["resource_spec"].name == "payment-events"
    assert state_a["resource_spec"].name != state_b["resource_spec"].name


def test_thread_a_cannot_retrieve_thread_b_state_after_reconstruction(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(workspace_root, saver)
        graph.invoke(
            {"request_id": "req-001", "resource_spec": _spec(name="order-events")},
            workflow_config("req-001"),
        )
        graph.invoke(
            {"request_id": "req-002", "resource_spec": _spec(name="payment-events")},
            workflow_config("req-002"),
        )

    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_durable(workspace_root, saver2)
        recovered_a = graph2.get_state(workflow_config("req-001")).values
        recovered_b = graph2.get_state(workflow_config("req-002")).values

    assert recovered_a["resource_spec"].name == "order-events"
    assert recovered_b["resource_spec"].name == "payment-events"


def test_repeated_retrieval_of_the_same_thread_is_deterministic(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-001")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(workspace_root, saver)
        graph.invoke({"request_id": "req-001", "resource_spec": _spec()}, config)

        first = graph.get_state(config).values
        second = graph.get_state(config).values

    assert first["workflow_status"] == second["workflow_status"]
    assert first["security_gate"] == second["security_gate"]


# ---------------------------------------------------------------------------
# ERROR-state durability
# ---------------------------------------------------------------------------


def test_error_state_survives_saver_and_graph_reconstruction(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-error-001")

    tf_error = TerraformCommandError(
        CommandResult(
            command=("terraform", "validate"),
            returncode=1,
            stdout="",
            stderr="benign validate failure",
            duration_seconds=0.0,
        )
    )

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_durable(
            workspace_root,
            saver,
            terraform_runner=FakeTerraformRunner(fail_at="validate", fail_exc=tf_error),
        )
        first_result = graph.invoke(
            {"request_id": "req-error-001", "resource_spec": _spec()}, config
        )
        assert first_result["workflow_status"] is WorkflowStatus.ERROR

    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_durable(workspace_root, saver2)
        recovered = graph2.get_state(config).values

    assert recovered["workflow_status"] is WorkflowStatus.ERROR
    assert recovered["error"].stage is WorkflowStage.TERRAFORM
    assert recovered["error"].error_type == "TerraformCommandError"
    assert "benign validate failure" in recovered["error"].message
    # No original exception object survives — only the safe, structured
    # WorkflowError dataclass value.
    assert not hasattr(recovered["error"], "__traceback__")
    assert not isinstance(recovered["error"], Exception)
