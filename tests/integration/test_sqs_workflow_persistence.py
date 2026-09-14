"""Integration proof: durable SQLite checkpointing over the real pipeline.

SQSResourceSpec -> real LangGraph workflow (real renderer, real
Terraform, real trusted module, real plan analyzer, real platform
policy, real Checkov, real security gate) -> SQLite checkpoint -> CLOSE
-> new checkpointer + new compiled graph against the SAME database file
-> get_state(same thread config) -> recovered interrupted state.

The original saver and graph objects are never reused for recovery —
this is what makes the test a genuine simulation of process
reconstruction, not just "the graph remembered it in memory".

Batch 13: a clean PASS result now durably pauses at the human approval
gate rather than reaching a terminal state by itself, so recovery here
proves the *interrupted* AWAITING_APPROVAL state survives
reconstruction. The full interrupt -> reconstruct -> resume -> APPROVED
sequence (the one real-tool durable *approval* integration test) lives
in tests/integration/test_sqs_workflow_hitl.py; this test keeps its
original Batch 12 purpose of proving durability of the real pipeline's
output up to that point.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyEvaluation, SecurityGateResult
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_sqs_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.security.checkov import CheckovAdapter, CheckovScanResult

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None or shutil.which("checkov") is None,
    reason="terraform and/or checkov binary not available on PATH",
)


def _build_real_graph(workspace_root: Path, checkpointer):
    return build_sqs_workflow(
        renderer=TerraformCompositionRenderer(),
        terraform_runner=TerraformRunner(),
        checkov_adapter=CheckovAdapter(),
        workspace_root=workspace_root,
        checkpointer=checkpointer,
    )


def test_real_workflow_state_survives_sqlite_checkpointer_and_graph_reconstruction(tmp_path):
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    spec = SQSResourceSpec(
        name="order-events",
        dlq=DlqSpec(enabled=True, max_receive_count=5),
        tags={"Service": "orders"},
    )
    request_id = "req-durable-001"
    config = workflow_config(request_id)

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_real_graph(workspace_root, saver)
        first_result = graph.invoke({"request_id": request_id, "resource_spec": spec}, config)

    assert first_result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert first_result["current_stage"] is WorkflowStage.APPROVAL
    assert "__interrupt__" in first_result

    # `saver` and `graph` above are now out of scope / their SQLite
    # connection is closed. Recovery below uses entirely new objects
    # against the same database file — this is the actual proof of
    # durability, not merely re-reading the same in-memory graph.
    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_real_graph(workspace_root, saver2)
        recovered = graph2.get_state(config).values

    assert recovered["request_id"] == request_id
    assert isinstance(recovered["resource_spec"], SQSResourceSpec)
    assert recovered["resource_spec"].name == "order-events"

    plan_summary = recovered["plan_summary"]
    assert isinstance(plan_summary, PlanSummary)
    assert plan_summary.add_count == 2
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
