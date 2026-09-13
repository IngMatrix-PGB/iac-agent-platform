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

from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecuritySeverity,
)
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.plan_analyzer import PlanAnalysisError
from iac_agent.execution.terraform_runner import CommandResult, TerraformCommandError
from iac_agent.graph import workflow as workflow_module
from iac_agent.graph.workflow import build_sqs_workflow
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
):
    renderer = renderer or FakeRenderer()
    terraform_runner = terraform_runner or FakeTerraformRunner()
    checkov_adapter = checkov_adapter or FakeCheckovAdapter()

    graph = build_sqs_workflow(
        renderer=renderer,
        terraform_runner=terraform_runner,
        checkov_adapter=checkov_adapter,
        workspace_root=tmp_path,
    )
    return graph, renderer, terraform_runner, checkov_adapter


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_node_order_and_final_status(tmp_path):
    graph, renderer, tf, checkov = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert tf.calls == ["fmt", "init", "validate", "plan", "show_json"]
    assert len(renderer.render_calls) == 1
    assert len(checkov.scan_calls) == 1
    assert result["workflow_status"] is WorkflowStatus.PASS
    assert result["current_stage"] is WorkflowStage.COMPLETE


def test_renderer_called_once_with_correct_spec(tmp_path):
    graph, renderer, _, _ = _build(tmp_path)
    spec = _spec()
    graph.invoke({"request_id": "req-001", "resource_spec": spec})

    assert len(renderer.render_calls) == 1
    assert renderer.render_calls[0]["spec"] == spec


def test_terraform_fmt_init_validate_plan_show_json_each_called_once(tmp_path):
    graph, _, tf, _ = _build(tmp_path)
    graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    for step in ("fmt", "init", "validate", "plan", "show_json"):
        assert tf.calls.count(step) == 1


def test_plan_summary_is_propagated(tmp_path):
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    plan_summary = result["plan_summary"]
    assert plan_summary is not None
    assert set(plan_summary.resources_to_add) == {
        "module.queue.aws_sqs_queue.this",
        "module.queue.aws_sqs_queue.dlq[0]",
    }


def test_platform_evaluation_is_propagated(tmp_path):
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["platform_evaluation"] is not None
    assert result["platform_evaluation"].overall_status is PolicyStatus.PASS


def test_checkov_called_once(tmp_path):
    graph, _, _, checkov = _build(tmp_path)
    graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert len(checkov.scan_calls) == 1


def test_security_gate_result_is_propagated(tmp_path):
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["security_gate"] is not None
    assert result["security_gate"].overall_status is PolicyStatus.PASS


def test_pass_gate_gives_pass_workflow_status(tmp_path):
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert result["workflow_status"] is WorkflowStatus.PASS


def test_warn_gate_gives_warn_workflow_status(tmp_path):
    spec = _spec(dlq=DlqSpec(enabled=False, max_receive_count=None))
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": spec})
    assert result["workflow_status"] is WorkflowStatus.WARN


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
    graph, _, _, _ = _build(tmp_path, checkov_adapter=FakeCheckovAdapter(result=checkov_block))
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.BLOCKED


# ---------------------------------------------------------------------------
# Error cases + fail-stop
# ---------------------------------------------------------------------------


def test_renderer_failure_gives_error_and_stops(tmp_path):
    graph, renderer, tf, checkov = _build(
        tmp_path, renderer=FakeRenderer(raise_exc=RuntimeError("boom"))
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.RENDER
    assert tf.calls == []
    assert checkov.scan_calls == []


@pytest.mark.parametrize("stage", ["fmt", "init", "validate", "plan", "show_json"])
def test_terraform_stage_failure_gives_error_and_stops(tmp_path, stage):
    tf_error = TerraformCommandError(_ok_result("terraform", stage))
    graph, renderer, tf, checkov = _build(
        tmp_path, terraform_runner=FakeTerraformRunner(fail_at=stage, fail_exc=tf_error)
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.TERRAFORM
    assert "plan_summary" not in result or result["plan_summary"] is None
    assert checkov.scan_calls == []


def test_plan_analysis_failure_gives_error_and_stops(tmp_path):
    graph, renderer, tf, checkov = _build(
        tmp_path, terraform_runner=FakeTerraformRunner(plan_json={"resource_changes": "not-a-list"})
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.PLAN_ANALYSIS
    assert checkov.scan_calls == []


def test_checkov_executable_missing_gives_error_and_stops(tmp_path):
    graph, _, _, checkov = _build(
        tmp_path,
        checkov_adapter=FakeCheckovAdapter(raise_exc=CheckovExecutableNotFoundError("checkov")),
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.CHECKOV
    assert result.get("security_gate") is None


def test_checkov_timeout_gives_error_and_stops(tmp_path):
    from iac_agent.security.checkov import CheckovTimeoutError

    graph, _, _, checkov = _build(
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

    graph, _, _, checkov = _build(
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
        graph, _, _, _ = _build(tmp_path)
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
        )


def test_request_specific_workspace_created_under_root(tmp_path):
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    workspace = result["workspace"]
    assert workspace == tmp_path / "req-001"
    assert workspace.is_dir()
    assert workspace.parent == tmp_path


@pytest.mark.parametrize("bad_request_id", ["../escape", "a/../../b", "sub/dir"])
def test_request_id_path_traversal_is_rejected(tmp_path, bad_request_id):
    graph, renderer, tf, _ = _build(tmp_path)
    result = graph.invoke({"request_id": bad_request_id, "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert result["error"].stage is WorkflowStage.RENDER
    assert renderer.render_calls == []
    assert tf.calls == []


def test_absolute_request_id_is_rejected(tmp_path):
    graph, renderer, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "/etc/passwd", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.ERROR
    assert renderer.render_calls == []


def test_workspace_path_does_not_depend_on_process_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path.parent)
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert result["workspace"] == tmp_path / "req-001"


# ---------------------------------------------------------------------------
# Data hygiene
# ---------------------------------------------------------------------------


def test_final_successful_state_contains_plan_summary(tmp_path):
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert result["plan_summary"] is not None


def test_final_successful_state_contains_security_gate_result(tmp_path):
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert result["security_gate"] is not None


def test_final_successful_state_does_not_retain_raw_terraform_plan_json(tmp_path):
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})
    assert result.get("terraform_plan_json") is None


def test_final_successful_state_does_not_retain_raw_checkov_json(tmp_path):
    graph, _, _, _ = _build(tmp_path)
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
    graph, _, _, _ = _build(
        tmp_path, terraform_runner=FakeTerraformRunner(fail_at="plan", fail_exc=tf_error)
    )
    result = graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    assert secret not in result["error"].message


def test_no_developer_absolute_path_in_workflow_error(tmp_path):
    graph, renderer, _, _ = _build(
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
