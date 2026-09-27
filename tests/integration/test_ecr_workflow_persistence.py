"""Fresh-process durable HITL proof for a standalone ECR repository.

Real graph, real Terraform, real Checkov with the frozen profile, SQLite
checkpoint, then a new checkpointer and a new graph. Resume uses a fake
source-control adapter. No GitHub call.
"""

from __future__ import annotations

import shutil

import pytest
from langgraph.types import Command

from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyEvaluation, SecurityGateResult
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.providers.aws.ecr.contract import EcrResourceSpec
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


class _NeverCalledSourceControl:
    def publish_change(self, **kwargs):
        raise AssertionError("publish_change must not be called before resume")


def _build_real_graph(workspace_root, checkpointer, terraform_test_env, source_control_port):
    return build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=TerraformRunner(base_env=terraform_test_env),
        checkov_adapter=CheckovAdapter(),
        source_control_port=source_control_port,
        workspace_root=workspace_root,
        checkpointer=checkpointer,
    )


def test_ecr_spec_survives_fresh_process_checkpoint_reconstruction_and_resume(
    tmp_path, terraform_test_env
):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    spec = EcrResourceSpec(name="orders")
    request_id = "req-ecr-durable-001"
    config = workflow_config(request_id)

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_real_graph(
            workspace_root, saver, terraform_test_env, _NeverCalledSourceControl()
        )
        first_result = graph.invoke({"request_id": request_id, "resource_spec": spec}, config)

    assert first_result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert first_result["current_stage"] is WorkflowStage.APPROVAL
    assert "__interrupt__" in first_result

    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_real_graph(
            workspace_root, saver2, terraform_test_env, _NeverCalledSourceControl()
        )
        recovered = graph2.get_state(config).values

    assert type(recovered["resource_spec"]) is EcrResourceSpec
    assert type(recovered["resource_spec"]) is not dict
    assert recovered["resource_spec"].name == "orders"

    plan_summary = recovered["plan_summary"]
    assert isinstance(plan_summary, PlanSummary)
    assert plan_summary.add_count == 1
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
    assert "terraform_plan_json" not in recovered

    fake_source_control = _FakeSourceControl()
    with open_sqlite_checkpointer(db_path) as saver3:
        graph3 = _build_real_graph(
            workspace_root, saver3, terraform_test_env, fake_source_control
        )
        final_result = graph3.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

    assert final_result["workflow_status"] is WorkflowStatus.PR_CREATED
    assert final_result["current_stage"] is WorkflowStage.COMPLETE
    assert final_result["approval_decision"] is ApprovalDecision.APPROVE
    assert len(fake_source_control.calls) == 1
    assert type(final_result["resource_spec"]) is EcrResourceSpec
    assert type(final_result["resource_spec"]) is not dict
