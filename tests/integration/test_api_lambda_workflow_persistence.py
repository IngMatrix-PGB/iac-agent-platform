"""Integration proof: durable SQLite checkpointing over the real
api_lambda composition pipeline (Batch 20).

ApiLambdaSpec -> real LangGraph workflow (real `IacRenderer`
dispatching to the real api_lambda renderer, real Terraform, the two
real trusted modules, real plan analyzer, real composition policy,
real Checkov, real security gate) -> SQLite checkpoint -> CLOSE -> new
checkpointer + new compiled graph against the SAME database file ->
get_state(same thread config) -> recovered interrupted state.

Mirrors tests/integration/test_serverless_worker_workflow_persistence.py
exactly, via `build_iac_workflow`. The original saver and graph objects
are never reused for recovery — this is what makes the test a genuine
simulation of process reconstruction, not just "the graph remembered it
in memory".
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyEvaluation, SecurityGateResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.security.checkov import CheckovAdapter, CheckovScanResult

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None or shutil.which("checkov") is None,
        reason="terraform and/or checkov binary not available on PATH",
    ),
]


class _NeverCalledSourceControl:
    """This test never resumes past the approval interrupt, so
    `publish_change` must never be invoked."""

    def publish_change(self, **kwargs):
        raise AssertionError("publish_change must not be called in this test")


def _build_real_graph(workspace_root: Path, checkpointer, terraform_test_env: dict[str, str]):
    return build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=TerraformRunner(base_env=terraform_test_env),
        checkov_adapter=CheckovAdapter(),
        source_control_port=_NeverCalledSourceControl(),
        workspace_root=workspace_root,
        checkpointer=checkpointer,
    )


def test_real_workflow_state_survives_sqlite_checkpointer_and_graph_reconstruction(
    tmp_path, terraform_test_env
):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    spec = ApiLambdaSpec(
        name="orders-api-worker",
        api=ApiGatewayResourceSpec(name="orders-api"),
        function=LambdaResourceSpec(
            name="orders-handler", handler="app.handler", reserved_concurrency=5
        ),
        route=RouteSpec(method=HttpMethod.POST, path="/orders"),
    )
    request_id = "req-api-lambda-durable-001"
    config = workflow_config(request_id)

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_real_graph(workspace_root, saver, terraform_test_env)
        first_result = graph.invoke({"request_id": request_id, "resource_spec": spec}, config)

    assert first_result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert first_result["current_stage"] is WorkflowStage.APPROVAL
    assert "__interrupt__" in first_result

    # `saver` and `graph` above are now out of scope / their SQLite
    # connection is closed. Recovery below uses entirely new objects
    # against the same database file.
    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_real_graph(workspace_root, saver2, terraform_test_env)
        recovered = graph2.get_state(config).values

    assert recovered["request_id"] == request_id
    assert isinstance(recovered["resource_spec"], ApiLambdaSpec)
    assert recovered["resource_spec"].name == "orders-api-worker"
    assert recovered["resource_spec"].api.name == "orders-api"
    assert recovered["resource_spec"].function.name == "orders-handler"
    assert recovered["resource_spec"].route.route_key == "POST /orders"

    plan_summary = recovered["plan_summary"]
    assert isinstance(plan_summary, PlanSummary)
    assert plan_summary.add_count == 9
    assert plan_summary.change_count == 0
    assert plan_summary.destroy_count == 0
    assert plan_summary.destructive_change_detected is False

    assert isinstance(recovered["platform_evaluation"], PolicyEvaluation)
    assert recovered["platform_evaluation"].overall_status.value == "pass"

    assert isinstance(recovered["checkov_result"], CheckovScanResult)

    security_gate = recovered["security_gate"]
    assert isinstance(security_gate, SecurityGateResult)
    assert security_gate.overall_status.value == "pass"

    assert recovered["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert recovered["current_stage"] is WorkflowStage.APPROVAL

    # The raw Terraform plan JSON field must never exist, checkpointed
    # or not.
    assert "terraform_plan_json" not in recovered
