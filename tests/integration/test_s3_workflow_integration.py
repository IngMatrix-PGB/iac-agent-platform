"""Integration proof: the real LangGraph workflow over the real S3 pipeline.

S3ResourceSpec -> build_iac_workflow(...).invoke(...) using the real
`AWSResourceRenderer` (dispatching to `S3TerraformCompositionRenderer`),
the real `TerraformRunner` (real Terraform binary), the real trusted
`terraform/modules/s3` module, and the real `CheckovAdapter` (real
Checkov binary, with its default `DEFAULT_SKIPPED_CHECKS` applied — see
`docs/resources/s3.md` for why those four checks are a documented Phase
2 scope exclusion, not a suppressed security weakness). No AWS
credentials, no `terraform apply`.

Mirrors tests/integration/test_sqs_workflow_integration.py exactly,
using `build_iac_workflow` directly (not the `build_sqs_workflow`
compatibility wrapper, which only ever carries a single SQS renderer)
— proving the generalized entry point works end-to-end for a second
resource type with no S3-specific branch anywhere except rendering.
"""

from __future__ import annotations

import shutil

import pytest

from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.security.checkov import CheckovAdapter

pytestmark = pytest.mark.skipif(
    shutil.which("terraform") is None or shutil.which("checkov") is None,
    reason="terraform and/or checkov binary not available on PATH",
)


class _NeverCalledSourceControl:
    """This test never resumes past the approval interrupt, so
    `publish_change` must never be invoked — calling it is a test
    failure, not a fallback."""

    def publish_change(self, **kwargs):
        raise AssertionError("publish_change must not be called in this test")


def test_real_workflow_passes_for_a_secure_default_bucket_request(tmp_path):
    spec = S3ResourceSpec(name="order-events-bucket", tags={"Service": "orders"})

    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=TerraformRunner(),
        checkov_adapter=CheckovAdapter(),
        source_control_port=_NeverCalledSourceControl(),
        workspace_root=tmp_path,
    )

    result = graph.invoke({"request_id": "req-s3-001", "resource_spec": spec})

    # As with SQS: a clean PASS security result durably pauses for human
    # approval rather than terminating by itself. No checkpointer here,
    # so it cannot be resumed — see test_s3_workflow_persistence.py /
    # test_s3_workflow_hitl.py-style coverage for the full interrupt ->
    # reconstruct -> resume proof.
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["current_stage"] is WorkflowStage.APPROVAL
    assert result.get("error") is None
    assert "__interrupt__" in result

    # Observed empirically (see tests/integration/test_s3_renderer_terraform.py):
    # the secure baseline S3 module always plans exactly five resources.
    plan_summary = result["plan_summary"]
    assert plan_summary.add_count == 5
    assert plan_summary.change_count == 0
    assert plan_summary.destroy_count == 0
    assert plan_summary.destructive_change_detected is False

    assert result["platform_evaluation"].overall_status.value == "pass"

    checkov_result = result["checkov_result"]
    assert checkov_result.failed_checks == 0
    assert checkov_result.findings == ()

    assert result["security_gate"].overall_status.value == "pass"

    # Batch 12 invariant, proven again for S3: the raw plan JSON field
    # does not exist in WorkflowState at all.
    assert result.get("terraform_plan_json") is None
    assert "terraform_plan_json" not in result

    assert result["workspace"] == tmp_path / "req-s3-001"
