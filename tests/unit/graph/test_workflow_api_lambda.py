"""Unit tests proving the generalized LangGraph workflow works for an
`ApiLambdaSpec` composition request exactly as it does for a single AWS
resource or the SQS -> Lambda -> DynamoDB composition (see
test_workflow.py, test_workflow_lambda.py,
test_workflow_serverless_worker.py).

Deliberately NOT a full re-run of every SQS-side scenario —
`terraform_execute`, `plan_analysis`, and `approval_gate` never inspect
the request spec's type at all, so that behavior is already proven
once, generically, by the SQS suite. This file instead proves the
api_lambda-specific seams: `render_terraform` dispatches to the
api_lambda renderer via `IacRenderer`, the composition's own platform
policies route PASS/WARN/BLOCK correctly, `checkov_scan` selects the
composition's own approved Checkov profile, and `source_control`
produces api_lambda-labeled PR/commit text — via `build_iac_workflow`
directly, no new graph node.

All external boundaries (renderer, Terraform runner, Checkov adapter,
source control) are fakes — no real Terraform or Checkov binary is
required. Real-tool behavior is proven separately by
tests/integration/test_api_lambda_workflow_integration.py.
"""

from __future__ import annotations

from langgraph.types import Command

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.composition import CompositionType
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
from iac_agent.execution.terraform_runner import CommandResult
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.policies.composition import (
    API_LAMBDA_INVOKE_PERMISSION_REQUIRED,
    API_LAMBDA_NO_WILDCARD_PRINCIPAL,
    API_LAMBDA_ROUTE_EXPLICIT,
)
from iac_agent.policies.platform import (
    LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
    LAMBDA_TRACING_RECOMMENDED,
)
from iac_agent.policies.shared import TF_NO_DESTRUCTIVE_CHANGES
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.terraform_render import GeneratedTerraformComposition
from iac_agent.security.checkov import CheckovScanResult
from iac_agent.security.composition_checkov_profiles import composition_checkov_profile_for

# ---------------------------------------------------------------------------
# Fakes (deliberately duplicated from the other workflow test files — same
# precedent as every resource-specific/composition-specific workflow test
# file owning its own fixtures).
# ---------------------------------------------------------------------------

_DEFAULT_API_LAMBDA_PLAN_JSON = {
    "terraform_version": "1.16.1",
    "resource_changes": [
        {
            "address": address,
            "change": {"actions": ["create"], "before": None, "after": {}},
        }
        for address in (
            "module.api.aws_apigatewayv2_api.this",
            "module.api.aws_apigatewayv2_stage.default",
            "module.function.aws_cloudwatch_log_group.this",
            "module.function.aws_iam_role.this",
            "module.function.aws_iam_role_policy.logs",
            "module.function.aws_lambda_function.this",
            "aws_apigatewayv2_integration.lambda",
            "aws_apigatewayv2_route.this",
            "aws_lambda_permission.api_gateway",
        )
    ],
}

_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=41, failed_checks=0, skipped_checks=7, scanner_version="3.3.13"
)


class FakeRenderer:
    def __init__(self, *, raise_exc: Exception | None = None):
        self.render_calls: list[dict] = []
        self._raise_exc = raise_exc

    def render(self, spec, *, module_sources):
        self.render_calls.append({"spec": spec, "module_sources": module_sources})
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
    def __init__(self, *, plan_json=None):
        self.calls: list[str] = []
        self._plan_json = plan_json if plan_json is not None else _DEFAULT_API_LAMBDA_PLAN_JSON

    def fmt(self, workspace, **kwargs):
        self.calls.append("fmt")
        return _ok_result("terraform", "fmt")

    def init(self, workspace, **kwargs):
        self.calls.append("init")
        return _ok_result("terraform", "init")

    def validate(self, workspace, **kwargs):
        self.calls.append("validate")
        return _ok_result("terraform", "validate")

    def plan(self, workspace, plan_filename="tfplan", **kwargs):
        self.calls.append("plan")
        return _ok_result("terraform", "plan")

    def show_json(self, workspace, plan_filename="tfplan", **kwargs):
        self.calls.append("show_json")
        return self._plan_json


class FakeCheckovAdapter:
    def __init__(self, *, result=None):
        self.scan_calls: list = []
        self.profiles_seen: list = []
        self._result = result if result is not None else _CLEAN_CHECKOV_RESULT

    def scan(self, workspace, *, profile=None):
        self.scan_calls.append(workspace)
        self.profiles_seen.append(profile)
        return self._result


class FakeSourceControl:
    def __init__(self, *, pr_number: int = 1):
        self.calls: list[dict] = []
        self._pr_number = pr_number

    def publish_change(
        self, *, request_id, base_branch, branch_name, files, commit_message, pr_title, pr_body
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
        return PullRequestResult(
            number=self._pr_number,
            url=f"https://example.invalid/pull/{self._pr_number}",
            branch=branch_name,
            base_branch=base_branch,
        )


def _spec(**overrides) -> ApiLambdaSpec:
    defaults = {
        "name": "orders-api-worker",
        "api": ApiGatewayResourceSpec(name="orders-api"),
        "function": LambdaResourceSpec(name="orders-handler", handler="app.handler"),
        "route": RouteSpec(method=HttpMethod.POST, path="/orders"),
    }
    defaults.update(overrides)
    return ApiLambdaSpec(**defaults)


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

    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        api_lambda_renderer=renderer,
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
    result = graph.invoke({"request_id": "req-api-001", "resource_spec": _spec()})

    assert tf.calls == ["fmt", "init", "validate", "plan", "show_json"]
    assert len(renderer.render_calls) == 1
    assert len(checkov.scan_calls) == 1
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["current_stage"] is WorkflowStage.APPROVAL


def test_renderer_called_once_with_correct_spec(tmp_path):
    graph, renderer, _, _, _ = _build(tmp_path)
    spec = _spec()
    graph.invoke({"request_id": "req-api-001", "resource_spec": spec})

    assert len(renderer.render_calls) == 1
    assert renderer.render_calls[0]["spec"] == spec


def test_render_uses_both_constituent_trusted_module_dirs(tmp_path):
    graph, renderer, _, _, _ = _build(tmp_path)
    graph.invoke({"request_id": "req-api-001", "resource_spec": _spec()})

    module_sources = renderer.render_calls[0]["module_sources"]
    assert "api_gateway" in module_sources.api
    assert "lambda" in module_sources.function


def test_plan_summary_is_propagated(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-api-001", "resource_spec": _spec()})

    plan_summary = result["plan_summary"]
    assert plan_summary is not None
    assert plan_summary.add_count == 9
    assert plan_summary.destructive_change_detected is False


def test_platform_evaluation_contains_all_six_api_lambda_policies(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    spec = _spec(
        function=LambdaResourceSpec(
            name="orders-handler", handler="app.handler", reserved_concurrency=5
        )
    )
    result = graph.invoke({"request_id": "req-api-001", "resource_spec": spec})

    policy_ids = {finding.policy_id for finding in result["platform_evaluation"].findings}
    assert policy_ids == {
        API_LAMBDA_INVOKE_PERMISSION_REQUIRED,
        API_LAMBDA_NO_WILDCARD_PRINCIPAL,
        API_LAMBDA_ROUTE_EXPLICIT,
        LAMBDA_TRACING_RECOMMENDED,
        LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
        TF_NO_DESTRUCTIVE_CHANGES,
    }
    assert result["platform_evaluation"].overall_status is PolicyStatus.PASS


def test_reserved_concurrency_omitted_gives_warn_but_still_routes_to_approval(tmp_path):
    graph, _, _, _, _ = _build(tmp_path)
    result = graph.invoke({"request_id": "req-api-001", "resource_spec": _spec()})

    assert result["platform_evaluation"].overall_status is PolicyStatus.WARN
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL


def test_api_lambda_request_gets_its_own_approved_checkov_profile(tmp_path):
    graph, _, _, checkov, _ = _build(tmp_path)
    graph.invoke({"request_id": "req-api-001", "resource_spec": _spec()})

    expected = composition_checkov_profile_for(CompositionType.API_GATEWAY_LAMBDA)
    assert len(checkov.profiles_seen) == 1
    assert checkov.profiles_seen[0] == expected
    assert "CKV_AWS_119" not in checkov.profiles_seen[0].skipped_checks


def test_checkov_block_routes_to_blocked_with_no_interrupt(tmp_path):
    block_result = CheckovScanResult(
        findings=(
            SecurityFinding(
                policy_id="CKV_AWS_309",
                severity=SecuritySeverity.HIGH,
                status=PolicyStatus.BLOCK,
                resource="aws_apigatewayv2_route.this",
                message="Checkov CKV_AWS_309 failed.",
                source=FindingSource.CHECKOV,
            ),
        ),
        passed_checks=40,
        failed_checks=1,
        skipped_checks=6,
        scanner_version="3.3.13",
    )
    graph, _, _, _, _ = _build(tmp_path, checkov_adapter=FakeCheckovAdapter(result=block_result))
    result = graph.invoke({"request_id": "req-api-001", "resource_spec": _spec()})

    assert result["workflow_status"] is WorkflowStatus.BLOCKED
    assert result["current_stage"] is WorkflowStage.COMPLETE
    assert "__interrupt__" not in result


# ---------------------------------------------------------------------------
# Resume through source_control (api_lambda-labeled PR/commit text)
# ---------------------------------------------------------------------------


def _invoke_to_interrupt(workspace_root, saver, request_id, spec, **overrides):
    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        api_lambda_renderer=overrides.get("renderer") or FakeRenderer(),
        terraform_runner=overrides.get("terraform_runner") or FakeTerraformRunner(),
        checkov_adapter=overrides.get("checkov_adapter") or FakeCheckovAdapter(),
        source_control_port=overrides.get("source_control_port") or FakeSourceControl(),
        workspace_root=workspace_root,
        checkpointer=saver,
    )
    config = workflow_config(request_id)
    graph.invoke({"request_id": request_id, "resource_spec": spec}, config)
    return graph, config


def test_approve_resume_gives_pr_created(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-api-approve", _spec(), source_control_port=source_control
        )
        result = graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert result["workflow_status"] is WorkflowStatus.PR_CREATED
    assert result["current_stage"] is WorkflowStage.COMPLETE
    assert result["pull_request"] is not None
    assert len(source_control.calls) == 1


def test_reject_resume_gives_rejected_status(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(workspace_root, saver, "req-api-reject", _spec())
        result = graph.invoke(Command(resume=ApprovalDecision.REJECT.value), config)

    assert result["workflow_status"] is WorkflowStatus.REJECTED
    assert result["current_stage"] is WorkflowStage.COMPLETE


def test_pr_body_states_composition_type_api_and_route(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-api-body", _spec(), source_control_port=source_control
        )
        graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    pr_body = source_control.calls[0]["pr_body"]
    assert "Composition type: api_gateway_lambda" in pr_body
    assert "API: orders-api" in pr_body
    assert "Route: POST /orders" in pr_body
    assert "Lambda: orders-handler" in pr_body
    assert "Resource type:" not in pr_body
    assert 'resource "aws_' not in pr_body


def test_commit_message_says_api_lambda(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    source_control = FakeSourceControl()

    with open_sqlite_checkpointer(db_path) as saver:
        graph, config = _invoke_to_interrupt(
            workspace_root, saver, "req-api-commit", _spec(), source_control_port=source_control
        )
        graph.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    commit_message = source_control.calls[0]["commit_message"]
    assert commit_message == "feat(iac): add API Lambda proposal req-api-commit"


# ---------------------------------------------------------------------------
# Durable round-trip (real SQLite, fake Terraform/Checkov)
# ---------------------------------------------------------------------------


def test_interrupted_api_lambda_state_round_trips_through_real_sqlite(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    config = workflow_config("req-api-durable-001")

    with open_sqlite_checkpointer(db_path) as saver:
        graph = build_iac_workflow(
            renderer=AWSResourceRenderer(),
            api_lambda_renderer=FakeRenderer(),
            terraform_runner=FakeTerraformRunner(),
            checkov_adapter=FakeCheckovAdapter(),
            source_control_port=FakeSourceControl(),
            workspace_root=workspace_root,
            checkpointer=saver,
        )
        first_result = graph.invoke(
            {"request_id": "req-api-durable-001", "resource_spec": _spec()}, config
        )
        assert first_result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
        assert "__interrupt__" in first_result

    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = build_iac_workflow(
            renderer=AWSResourceRenderer(),
            api_lambda_renderer=FakeRenderer(),
            terraform_runner=FakeTerraformRunner(),
            checkov_adapter=FakeCheckovAdapter(),
            source_control_port=FakeSourceControl(),
            workspace_root=workspace_root,
            checkpointer=saver2,
        )
        recovered = graph2.get_state(config).values

    assert recovered["request_id"] == "req-api-durable-001"
    assert isinstance(recovered["resource_spec"], ApiLambdaSpec)
    assert isinstance(recovered["plan_summary"], PlanSummary)
    assert isinstance(recovered["platform_evaluation"], PolicyEvaluation)
    assert isinstance(recovered["checkov_result"], CheckovScanResult)
    assert isinstance(recovered["security_gate"], SecurityGateResult)
    assert recovered["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert "terraform_plan_json" not in recovered
