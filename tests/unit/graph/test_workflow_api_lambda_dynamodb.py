"""Unit tests proving the generalized LangGraph workflow correctly
presents and dispatches an `ApiLambdaDynamoDbSpec` composition request
(Batch 26).

Split by what's actually provable at Gate A vs. what genuinely needs
Gate B:

- `_pr_body()` and `_resource_kind_of()` are pure, module-level
  functions — testable directly, no graph invocation needed.
- `platform_policy` runs *before* `checkov_scan` in the graph, so its
  dispatch is provable via a real `graph.invoke()` even though this
  composition's Checkov profile does not exist until Gate B (Task 16).
- `checkov_scan`/`security_gate`'s dispatch is proven via
  `graph.invoke()` too, but only by monkeypatching
  `composition_checkov_profile_for` for the duration of one test — a
  test-only substitute, never a profile written to production code.
  This proves the *dispatch mechanics* (composition path taken, not
  the single-resource fallback) without inventing or freezing the real,
  empirically-derived skip list, which stays exclusively Gate B's job.
"""

from __future__ import annotations

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyStatus, SecurityGateResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import CommandResult
from iac_agent.graph.workflow import _pr_body, _resource_kind_of, build_iac_workflow
from iac_agent.policies.composition import (
    API_LAMBDA_DYNAMODB_INVOKE_PERMISSION_REQUIRED,
    API_LAMBDA_DYNAMODB_NO_WILDCARD_IAM,
    API_LAMBDA_DYNAMODB_NO_WILDCARD_PRINCIPAL,
    API_LAMBDA_DYNAMODB_ROUTE_EXPLICIT,
    API_LAMBDA_DYNAMODB_WRITE_SCOPE_REQUIRED,
)
from iac_agent.policies.platform import (
    DDB_DELETION_PROTECTION_RECOMMENDED,
    DDB_PITR_RECOMMENDED,
    LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
    LAMBDA_TRACING_RECOMMENDED,
)
from iac_agent.policies.shared import TF_NO_DESTRUCTIVE_CHANGES
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.terraform_render import GeneratedTerraformComposition
from iac_agent.security.checkov import CheckovScanProfile, CheckovScanResult

_DEFAULT_PLAN_JSON = {
    "terraform_version": "1.16.1",
    "resource_changes": [
        {
            "address": address,
            "change": {"actions": ["create"], "before": None, "after": {}},
        }
        for address in (
            "module.api.aws_apigatewayv2_api.this",
            "module.function.aws_lambda_function.this",
            "module.table.aws_dynamodb_table.this",
            "aws_apigatewayv2_integration.lambda",
            "aws_lambda_permission.api_gateway",
            "aws_iam_role_policy.dynamodb_write",
        )
    ],
}

_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=41, failed_checks=0, skipped_checks=7, scanner_version="3.3.13"
)


def _spec(**overrides) -> ApiLambdaDynamoDbSpec:
    defaults = {
        "name": "orders-api-worker",
        "api": ApiGatewayResourceSpec(name="orders-api"),
        "function": LambdaResourceSpec(name="orders-handler", handler="app.handler"),
        "route": RouteSpec(method=HttpMethod.POST, path="/orders"),
        "table": DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="id", type="S")
        ),
    }
    defaults.update(overrides)
    return ApiLambdaDynamoDbSpec(**defaults)


# ---------------------------------------------------------------------------
# _resource_kind_of — the extracted, testable commit-message helper
# ---------------------------------------------------------------------------


def test_resource_kind_of_api_lambda_dynamodb_spec():
    assert _resource_kind_of(_spec()) == "api lambda dynamodb"


def test_resource_kind_of_existing_compositions_unchanged():
    """Backward-compat proof: extracting this into a module-level
    function must not change either existing composition's value."""
    worker_spec = ServerlessWorkerSpec(
        name="orders-worker",
        queue=SQSResourceSpec(name="orders-queue"),
        function=LambdaResourceSpec(name="orders-processor", handler="app.handler"),
        table=DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
    )
    api_lambda_spec = ApiLambdaSpec(
        name="orders-api",
        api=ApiGatewayResourceSpec(name="orders-api-gw"),
        function=LambdaResourceSpec(name="orders-fn", handler="app.handler"),
        route=RouteSpec(method=HttpMethod.GET, path="/orders"),
    )
    assert _resource_kind_of(worker_spec) == "serverless worker"
    assert _resource_kind_of(api_lambda_spec) == "API Lambda"


def test_resource_kind_of_single_resource_spec_unchanged():
    assert _resource_kind_of(SQSResourceSpec(name="orders-queue")) == "SQS"


# ---------------------------------------------------------------------------
# _pr_body
# ---------------------------------------------------------------------------


def _pr_body_state(spec: ApiLambdaDynamoDbSpec) -> dict:
    return {
        "request_id": "req-001",
        "resource_spec": spec,
        "security_gate": SecurityGateResult(findings=()),
        "plan_summary": PlanSummary(
            resource_changes=(),
            resources_to_add=("a", "b"),
            resources_to_change=(),
            resources_to_destroy=(),
            destructive_change_detected=False,
        ),
        "approval_decision": ApprovalDecision.APPROVE,
    }


def test_pr_body_states_composition_type_api_route_lambda_and_table():
    body = _pr_body(_pr_body_state(_spec()))
    assert "Composition type: api_gateway_lambda_dynamodb" in body
    assert "API: orders-api" in body
    assert "Route: POST /orders" in body
    assert "Lambda: orders-handler" in body
    assert "Table: orders-table" in body


def test_pr_body_never_leaks_raw_terraform_or_checkov_json():
    body = _pr_body(_pr_body_state(_spec()))
    for forbidden in ("resource_changes", "passed_checks", "workspace", "Traceback"):
        assert forbidden not in body


# ---------------------------------------------------------------------------
# Full-graph dispatch proof (Gate A: platform_policy only — provable
# without a real Checkov profile, since it runs before checkov_scan)
# ---------------------------------------------------------------------------


class _FakeRenderer:
    def __init__(self):
        self.render_calls: list[dict] = []

    def render(self, spec, *, module_sources):
        self.render_calls.append({"spec": spec, "module_sources": module_sources})
        return GeneratedTerraformComposition(
            files={"main.tf": "# fake\n", "versions.tf": "# fake\n"}
        )


def _ok_result(*parts: str) -> CommandResult:
    return CommandResult(
        command=tuple(parts), returncode=0, stdout="", stderr="", duration_seconds=0.0
    )


class _FakeTerraformRunner:
    def __init__(self, *, plan_json=None):
        self.calls: list[str] = []
        self._plan_json = plan_json if plan_json is not None else _DEFAULT_PLAN_JSON

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


class _FakeCheckovAdapter:
    def __init__(self, *, result=None):
        self.scan_calls: list = []
        self.profiles_seen: list = []
        self._result = result if result is not None else _CLEAN_CHECKOV_RESULT

    def scan(self, workspace, *, profile=None):
        self.scan_calls.append(workspace)
        self.profiles_seen.append(profile)
        return self._result


class _FakeSourceControl:
    def publish_change(self, **kwargs):
        raise AssertionError("source_control must never be reached in these tests")


def _build(tmp_path, *, renderer=None, terraform_runner=None, checkov_adapter=None):
    renderer = renderer or _FakeRenderer()
    terraform_runner = terraform_runner or _FakeTerraformRunner()
    checkov_adapter = checkov_adapter or _FakeCheckovAdapter()

    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        api_lambda_dynamodb_renderer=renderer,
        terraform_runner=terraform_runner,
        checkov_adapter=checkov_adapter,
        source_control_port=_FakeSourceControl(),
        workspace_root=tmp_path,
    )
    return graph, renderer, terraform_runner, checkov_adapter


def test_platform_policy_takes_the_composition_path_not_the_single_resource_fallback(tmp_path):
    """The exact "grouped OR-arm forgotten" regression the design
    flagged: if ApiLambdaDynamoDbSpec fell through to the single-
    resource `case _` arm, this would raise inside `resource_type_of`
    instead of producing the nine composition policy findings."""
    graph, _, _, _ = _build(tmp_path)
    result = graph.invoke(
        {
            "request_id": "req-001",
            "resource_spec": _spec(
                function=LambdaResourceSpec(
                    name="orders-handler", handler="app.handler", reserved_concurrency=5
                )
            ),
        }
    )

    assert "platform_evaluation" in result
    policy_ids = {finding.policy_id for finding in result["platform_evaluation"].findings}
    assert policy_ids == {
        API_LAMBDA_DYNAMODB_INVOKE_PERMISSION_REQUIRED,
        API_LAMBDA_DYNAMODB_NO_WILDCARD_PRINCIPAL,
        API_LAMBDA_DYNAMODB_ROUTE_EXPLICIT,
        API_LAMBDA_DYNAMODB_WRITE_SCOPE_REQUIRED,
        API_LAMBDA_DYNAMODB_NO_WILDCARD_IAM,
        LAMBDA_TRACING_RECOMMENDED,
        LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
        DDB_PITR_RECOMMENDED,
        DDB_DELETION_PROTECTION_RECOMMENDED,
        TF_NO_DESTRUCTIVE_CHANGES,
    }
    assert result["platform_evaluation"].overall_status is PolicyStatus.PASS


def test_render_uses_all_three_constituent_trusted_module_dirs(tmp_path):
    graph, renderer, _, _ = _build(tmp_path)
    graph.invoke({"request_id": "req-001", "resource_spec": _spec()})

    module_sources = renderer.render_calls[0]["module_sources"]
    assert "api_gateway" in module_sources.api
    assert "lambda" in module_sources.function
    assert "dynamodb" in module_sources.table


# ---------------------------------------------------------------------------
# checkov_scan / security_gate dispatch proof — test-only monkeypatch of
# composition_checkov_profile_for (never a production/Gate-B profile)
# ---------------------------------------------------------------------------


def test_checkov_scan_and_security_gate_take_the_composition_path(tmp_path, monkeypatch):
    """Proves checkov_scan/security_gate route this spec through the
    *composition* dispatch (composition_checkov_profile_for,
    required_policy_ids=) rather than the single-resource fallback
    (checkov_profile_for/resource_type_of) — without inventing or
    freezing the real, empirically-derived skip list (that stays
    exclusively Gate B's job, Task 16)."""
    fake_profile = CheckovScanProfile(skipped_checks=())

    def _fake_profile_for(composition_type):
        return fake_profile

    monkeypatch.setattr(
        "iac_agent.graph.workflow.composition_checkov_profile_for", _fake_profile_for
    )

    checkov = _FakeCheckovAdapter()
    graph, _, _, _ = _build(tmp_path, checkov_adapter=checkov)
    result = graph.invoke(
        {
            "request_id": "req-001",
            "resource_spec": _spec(
                function=LambdaResourceSpec(
                    name="orders-handler", handler="app.handler", reserved_concurrency=5
                )
            ),
        }
    )

    assert checkov.profiles_seen == [fake_profile]
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["current_stage"] is WorkflowStage.APPROVAL
    gate_result = result["security_gate"]
    assert gate_result.overall_status is PolicyStatus.PASS
