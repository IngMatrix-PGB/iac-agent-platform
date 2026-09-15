"""Integration proof: the real LangGraph workflow over the real DynamoDB
pipeline (Batch 17).

DynamoDBResourceSpec -> build_iac_workflow(...).invoke(...) using the
real `AWSResourceRenderer` (dispatching to
`DynamoDBTerraformCompositionRenderer`), the real `TerraformRunner`
(real Terraform binary), the real trusted `terraform/modules/dynamodb`
module, and the real `CheckovAdapter` (real Checkov binary; the
graph's `checkov_scan` node selects the approved DynamoDB
`CheckovScanProfile` via `checkov_profile_for` — see
`docs/resources/dynamodb.md` for why the one skipped check is a
documented Phase 2 scope exclusion, not a suppressed security
weakness). No AWS credentials, no `terraform apply`.

Mirrors tests/integration/test_s3_workflow_integration.py exactly,
using `build_iac_workflow` directly — proving the generalized entry
point works end-to-end for a third resource type with no
DynamoDB-specific branch anywhere except rendering.
"""

from __future__ import annotations

import shutil

import pytest

from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.security.checkov import CheckovAdapter

pytestmark = [
    pytest.mark.real_tool,
    pytest.mark.skipif(
        shutil.which("terraform") is None or shutil.which("checkov") is None,
        reason="terraform and/or checkov binary not available on PATH",
    ),
]


class _NeverCalledSourceControl:
    """This test never resumes past the approval interrupt, so
    `publish_change` must never be invoked — calling it is a test
    failure, not a fallback."""

    def publish_change(self, **kwargs):
        raise AssertionError("publish_change must not be called in this test")


def test_real_workflow_passes_for_a_secure_default_table_request(tmp_path, terraform_test_env):
    spec = DynamoDBResourceSpec(
        name="orders-events-table",
        partition_key=DynamoDBKeySpec(name="order_id", type=DynamoDBKeyType.STRING),
        tags={"Service": "orders"},
    )

    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=TerraformRunner(base_env=terraform_test_env),
        checkov_adapter=CheckovAdapter(),
        source_control_port=_NeverCalledSourceControl(),
        workspace_root=tmp_path,
    )

    result = graph.invoke({"request_id": "req-ddb-001", "resource_spec": spec})

    # As with SQS/S3: a clean PASS security result durably pauses for
    # human approval rather than terminating by itself. No checkpointer
    # here, so it cannot be resumed — see
    # test_dynamodb_workflow_persistence.py for the full interrupt ->
    # reconstruct -> resume proof.
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["current_stage"] is WorkflowStage.APPROVAL
    assert result.get("error") is None
    assert "__interrupt__" in result

    # Observed empirically (see
    # tests/integration/test_dynamodb_renderer_terraform.py): the
    # secure baseline DynamoDB module always plans exactly one resource.
    plan_summary = result["plan_summary"]
    assert plan_summary.add_count == 1
    assert plan_summary.change_count == 0
    assert plan_summary.destroy_count == 0
    assert plan_summary.destructive_change_detected is False

    assert result["platform_evaluation"].overall_status.value == "pass"

    checkov_result = result["checkov_result"]
    assert checkov_result.failed_checks == 0
    assert checkov_result.findings == ()

    assert result["security_gate"].overall_status.value == "pass"

    # Batch 12 invariant, proven again for DynamoDB: the raw plan JSON
    # field does not exist in WorkflowState at all.
    assert result.get("terraform_plan_json") is None
    assert "terraform_plan_json" not in result

    assert result["workspace"] == tmp_path / "req-ddb-001"
