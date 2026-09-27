"""Integration proof: durable SQLite checkpointing over the real
api_lambda_dynamodb composition pipeline, including a full fresh-
process resume through to a completed proposal (Batch 26, Gate B, Task
18).

`ApiLambdaDynamoDbSpec` -> real LangGraph workflow (real `IacRenderer`
dispatching to the real renderer, real Terraform, all three real
trusted modules, real plan analyzer, real composition policy, real
Checkov with the now-frozen empirically-derived profile, real security
gate) -> SQLite checkpoint -> CLOSE -> new checkpointer + new compiled
graph against the SAME database file -> `get_state` (recovered
interrupted state) -> resume with APPROVE -> `source_control` (a fake
adapter — no GitHub publication is authorized in this batch).

This is the concrete, mandatory proof for the checkpoint-allowlist
entry added in Gate A (Task 7): without it, this test would fail here,
not silently pass. `type(...) is ApiLambdaDynamoDbSpec` is used
throughout, never `isinstance`, to also rule out an accidental
subclass or a silent widening to `ApiLambdaSpec`/a raw `dict`. The
original saver and graph objects are never reused for recovery — this
is what makes the test a genuine simulation of process reconstruction,
not just "the graph remembered it in memory".
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from langgraph.types import Command

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyEvaluation, SecurityGateResult
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
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


class _FakeSourceControl:
    """Never a real GitHub call — this batch does not authorize GitHub
    publication. Only used to prove the resume path reaches
    `source_control` and completes."""

    def __init__(self):
        self.calls: list[dict] = []

    def publish_change(self, **kwargs) -> PullRequestResult:
        self.calls.append(kwargs)
        return PullRequestResult(
            number=1,
            url="https://example.invalid/pull/1",
            branch=kwargs["branch_name"],
            base_branch=kwargs["base_branch"],
        )


def _build_real_graph(
    workspace_root: Path, checkpointer, terraform_test_env: dict[str, str], source_control_port
):
    return build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=TerraformRunner(base_env=terraform_test_env),
        checkov_adapter=CheckovAdapter(),
        source_control_port=source_control_port,
        workspace_root=workspace_root,
        checkpointer=checkpointer,
    )


class _NeverCalledSourceControl:
    def publish_change(self, **kwargs):
        raise AssertionError("publish_change must not be called before resume")


def test_api_lambda_dynamodb_spec_survives_fresh_process_checkpoint_reconstruction_and_resume(
    tmp_path, terraform_test_env
):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    spec = ApiLambdaDynamoDbSpec(
        name="orders-api-worker",
        api=ApiGatewayResourceSpec(name="orders-api"),
        function=LambdaResourceSpec(
            name="orders-handler", handler="app.handler", reserved_concurrency=5
        ),
        route=RouteSpec(method=HttpMethod.POST, path="/orders"),
        table=DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="id", type="S")
        ),
    )
    request_id = "req-api-lambda-dynamodb-durable-001"
    config = workflow_config(request_id)

    # --- Process 1: submit through to the real HITL interrupt ---
    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_real_graph(
            workspace_root, saver, terraform_test_env, _NeverCalledSourceControl()
        )
        first_result = graph.invoke({"request_id": request_id, "resource_spec": spec}, config)

    assert first_result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert first_result["current_stage"] is WorkflowStage.APPROVAL
    assert "__interrupt__" in first_result

    # `saver` and `graph` above are now out of scope / their SQLite
    # connection is closed. Reconstruction below uses entirely new
    # objects against the same database file — a real process-restart
    # simulation, not a same-process re-read.
    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_real_graph(
            workspace_root, saver2, terraform_test_env, _NeverCalledSourceControl()
        )
        recovered = graph2.get_state(config).values

    # The critical dispatch-boundary proof (Gate A Task 7's allowlist
    # entry): exact type, never merely isinstance.
    assert type(recovered["resource_spec"]) is ApiLambdaDynamoDbSpec
    assert type(recovered["resource_spec"]) is not ApiLambdaSpec
    assert not isinstance(recovered["resource_spec"], dict)

    assert recovered["request_id"] == request_id
    assert recovered["resource_spec"].name == "orders-api-worker"
    assert recovered["resource_spec"].api.name == "orders-api"
    assert recovered["resource_spec"].function.name == "orders-handler"
    assert recovered["resource_spec"].table.name == "orders-table"
    assert recovered["resource_spec"].route.route_key == "POST /orders"

    plan_summary = recovered["plan_summary"]
    assert isinstance(plan_summary, PlanSummary)
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
    assert "terraform_plan_json" not in recovered

    # --- Process 2 (continued): resume with APPROVE through to
    # source_control -- proves the full HITL round trip, not just
    # reconstruction. No real GitHub call: _FakeSourceControl only.
    fake_source_control = _FakeSourceControl()
    with open_sqlite_checkpointer(db_path) as saver3:
        graph3 = _build_real_graph(
            workspace_root, saver3, terraform_test_env, fake_source_control
        )
        final_result = graph3.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert final_result["workflow_status"] is WorkflowStatus.PR_CREATED
    assert final_result["current_stage"] is WorkflowStage.COMPLETE
    assert final_result["pull_request"] is not None
    assert len(fake_source_control.calls) == 1

    # The concrete type survived the entire round trip, including the
    # resume step.
    assert type(final_result["resource_spec"]) is ApiLambdaDynamoDbSpec
