"""Integration proof: durable SQLite checkpointing over the real S3 pipeline.

S3ResourceSpec -> real LangGraph workflow (real `AWSResourceRenderer`
dispatching to the real S3 renderer, real Terraform, the real trusted
`terraform/modules/s3` module, real plan analyzer, real platform
policy, real Checkov, real security gate) -> SQLite checkpoint -> CLOSE
-> new checkpointer + new compiled graph against the SAME database file
-> get_state(same thread config) -> recovered interrupted state.

Mirrors tests/integration/test_sqs_workflow_persistence.py exactly, via
`build_iac_workflow` (not the SQS-only `build_sqs_workflow` wrapper).
The original saver and graph objects are never reused for recovery —
this is what makes the test a genuine simulation of process
reconstruction, not just "the graph remembered it in memory".
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyEvaluation, SecurityGateResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.security.checkov import CheckovAdapter, CheckovScanResult

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None or shutil.which("checkov") is None,
    reason="terraform and/or checkov binary not available on PATH",
)


class _NeverCalledSourceControl:
    """This test never resumes past the approval interrupt, so
    `publish_change` must never be invoked."""

    def publish_change(self, **kwargs):
        raise AssertionError("publish_change must not be called in this test")


def _build_real_graph(workspace_root: Path, checkpointer):
    return build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=TerraformRunner(),
        checkov_adapter=CheckovAdapter(),
        source_control_port=_NeverCalledSourceControl(),
        workspace_root=workspace_root,
        checkpointer=checkpointer,
    )


def test_real_workflow_state_survives_sqlite_checkpointer_and_graph_reconstruction(tmp_path):
    db_path = tmp_path / "state.db"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    spec = S3ResourceSpec(name="order-events-bucket", tags={"Service": "orders"})
    request_id = "req-s3-durable-001"
    config = workflow_config(request_id)

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_real_graph(workspace_root, saver)
        first_result = graph.invoke({"request_id": request_id, "resource_spec": spec}, config)

    assert first_result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert first_result["current_stage"] is WorkflowStage.APPROVAL
    assert "__interrupt__" in first_result

    # `saver` and `graph` above are now out of scope / their SQLite
    # connection is closed. Recovery below uses entirely new objects
    # against the same database file.
    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_real_graph(workspace_root, saver2)
        recovered = graph2.get_state(config).values

    assert recovered["request_id"] == request_id
    assert isinstance(recovered["resource_spec"], S3ResourceSpec)
    assert recovered["resource_spec"].name == "order-events-bucket"

    plan_summary = recovered["plan_summary"]
    assert isinstance(plan_summary, PlanSummary)
    assert plan_summary.add_count == 5
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
