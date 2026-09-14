"""Integration proof: the real durable human-in-the-loop approval gate
(Batch 13).

This is the one real-tool durable *approval* integration test for this
batch: real TerraformCompositionRenderer, real TerraformRunner (real
Terraform binary), the real trusted terraform/modules/sqs module, real
plan analysis, real platform policies, the real CheckovAdapter (real
Checkov binary), the real security gate, real LangGraph orchestration,
and real SQLite checkpointing — end to end, through an interrupt,
through saver/graph reconstruction, through a resume, to a final
durable APPROVED state.

Every other Batch 13 scenario (WARN, BLOCK, ERROR, REJECT, invalid
resume values, payload-content checks) is covered with fakes in
tests/unit/graph/test_workflow.py — those do not need real Terraform or
Checkov, and duplicating them here would only double this test suite's
real-tool runtime cost for no additional evidence.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from langgraph.types import Command

from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_sqs_workflow
from iac_agent.persistence.checkpoints import open_sqlite_checkpointer, workflow_config
from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.security.checkov import CheckovAdapter

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


def test_real_pipeline_durable_approval_survives_reconstruction_and_resume(tmp_path):
    # 1-3: create DB, open checkpointer, build graph with checkpointer.
    db_path = tmp_path / "checkpoints.sqlite3"
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()

    spec = SQSResourceSpec(
        name="order-events",
        dlq=DlqSpec(enabled=True, max_receive_count=5),
        tags={"Service": "orders"},
    )
    request_id = "req-hitl-durable-001"
    config = workflow_config(request_id)

    with open_sqlite_checkpointer(db_path) as saver:
        graph = _build_real_graph(workspace_root, saver)

        # 4: invoke a valid PASS workflow.
        first_result = graph.invoke({"request_id": request_id, "resource_spec": spec}, config)

        # 5-6: graph reaches the approval interrupt; state says
        # AWAITING_APPROVAL.
        assert "__interrupt__" in first_result
        assert first_result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
        assert first_result["current_stage"] is WorkflowStage.APPROVAL
        assert first_result["security_gate"].overall_status.value == "pass"

        interrupt_payload = first_result["__interrupt__"][0].value
        assert interrupt_payload["request_id"] == request_id
        assert interrupt_payload["resource"] == "order-events"
        assert interrupt_payload["security_status"] == "pass"
        assert interrupt_payload["plan"] == {"add": 2, "change": 0, "destroy": 0}

    # 7-8: close saver, destroy graph object. `saver`/`graph` above are
    # out of scope now; the objects below are never reused.
    del graph, saver

    # 9-11: open a NEW saver against the same DB, build a NEW graph,
    # retrieve the same thread's state.
    with open_sqlite_checkpointer(db_path) as saver2:
        graph2 = _build_real_graph(workspace_root, saver2)
        snapshot = graph2.get_state(config)

        # 12: confirm still awaiting approval.
        assert snapshot.values["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
        assert snapshot.values["current_stage"] is WorkflowStage.APPROVAL
        assert snapshot.next == ("approval_gate",)

        # 13: resume with APPROVE.
        resumed_result = graph2.invoke(Command(resume=ApprovalDecision.APPROVE.value), config)

        # 14: confirm final APPROVED state.
        assert resumed_result["workflow_status"] is WorkflowStatus.APPROVED
        assert resumed_result["current_stage"] is WorkflowStage.COMPLETE
        assert resumed_result["approval_decision"] is ApprovalDecision.APPROVE
        # Human approval never rewrites the security evidence.
        assert resumed_result["security_gate"].overall_status.value == "pass"

    # 15-16: close again, reopen a NEW saver / NEW graph.
    del graph2, saver2

    with open_sqlite_checkpointer(db_path) as saver3:
        graph3 = _build_real_graph(workspace_root, saver3)

        # 17: retrieve final state.
        final_snapshot = graph3.get_state(config)
        final_values = final_snapshot.values

        # 18: confirm APPROVED persisted.
        assert final_values["workflow_status"] is WorkflowStatus.APPROVED
        assert final_values["current_stage"] is WorkflowStage.COMPLETE
        assert final_values["approval_decision"] is ApprovalDecision.APPROVE
        assert final_values["security_gate"].overall_status.value == "pass"
        assert final_snapshot.next == ()

    # No GitHub action, no terraform apply — nothing in this codebase
    # can do either (see the graph module and TerraformRunner).
    assert "terraform_plan_json" not in final_values
