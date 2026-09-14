"""Integration proof: the real LangGraph workflow over the real pipeline.

SQSResourceSpec -> build_sqs_workflow(...).invoke(...) using the real
TerraformCompositionRenderer, the real TerraformRunner (real Terraform
binary), the real trusted terraform/modules/sqs module, and the real
CheckovAdapter (real Checkov binary). No AWS credentials, no
`terraform apply`.
"""

from __future__ import annotations

import shutil

import pytest

from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_sqs_workflow
from iac_agent.providers.aws.sqs.contract import DlqSpec, SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.security.checkov import CheckovAdapter

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None or shutil.which("checkov") is None,
    reason="terraform and/or checkov binary not available on PATH",
)


def test_real_workflow_passes_for_a_secure_dlq_enabled_request(tmp_path):
    spec = SQSResourceSpec(
        name="order-events",
        dlq=DlqSpec(enabled=True, max_receive_count=5),
        tags={"Service": "orders"},
    )

    graph = build_sqs_workflow(
        renderer=TerraformCompositionRenderer(),
        terraform_runner=TerraformRunner(),
        checkov_adapter=CheckovAdapter(),
        workspace_root=tmp_path,
    )

    result = graph.invoke({"request_id": "req-001", "resource_spec": spec})

    # Batch 13: a clean PASS security result is no longer terminal by
    # itself — it durably pauses for human approval. This call has no
    # checkpointer, so it cannot be resumed (see
    # tests/integration/test_sqs_workflow_hitl.py for the full
    # interrupt -> reconstruct -> resume -> APPROVED proof); it only
    # needs to reach the interrupt correctly here.
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["current_stage"] is WorkflowStage.APPROVAL
    assert result.get("error") is None
    assert "__interrupt__" in result

    plan_summary = result["plan_summary"]
    assert plan_summary.add_count == 2
    assert plan_summary.change_count == 0
    assert plan_summary.destroy_count == 0
    assert plan_summary.destructive_change_detected is False

    assert result["platform_evaluation"].overall_status.value == "pass"

    checkov_result = result["checkov_result"]
    assert checkov_result.failed_checks == 0
    assert checkov_result.findings == ()

    assert result["security_gate"].overall_status.value == "pass"

    # Batch 12: the raw plan JSON field does not exist in WorkflowState at
    # all (not merely cleared) — structurally impossible to retain it.
    assert result.get("terraform_plan_json") is None
    assert "terraform_plan_json" not in result

    assert result["workspace"] == tmp_path / "req-001"
