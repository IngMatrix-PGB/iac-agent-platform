"""Integration proof: the real LangGraph workflow over the real
Lambda+IAM pipeline (Batch 18).

LambdaResourceSpec -> build_iac_workflow(...).invoke(...) using the
real `AWSResourceRenderer` (dispatching to
`LambdaTerraformCompositionRenderer`), the real `TerraformRunner` (real
Terraform binary), the real trusted `terraform/modules/lambda` module
(which creates the Lambda function, its IAM execution role, the inline
CloudWatch Logs permission policy, and the log group all internally),
and the real `CheckovAdapter` (real Checkov binary; the graph's
`checkov_scan` node selects the approved Lambda `CheckovScanProfile`
via `checkov_profile_for` — see `docs/resources/lambda.md` for why
those five skipped checks are documented Phase 2 scope exclusions, not
suppressed security weaknesses). No AWS credentials, no
`terraform apply`.

Mirrors tests/integration/test_dynamodb_workflow_integration.py
exactly, using `build_iac_workflow` directly — proving the generalized
entry point works end-to-end for a fourth resource type, including one
whose trusted module owns an internal multi-resource relationship
(Lambda + IAM + CloudWatch Logs), with no new graph node anywhere.
"""

from __future__ import annotations

import shutil

import pytest

from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
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


def test_real_workflow_passes_for_a_secure_default_function_request(tmp_path, terraform_test_env):
    spec = LambdaResourceSpec(
        name="orders-processor",
        handler="app.handler",
        reserved_concurrency=5,
        tags={"Service": "orders"},
    )

    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=TerraformRunner(base_env=terraform_test_env),
        checkov_adapter=CheckovAdapter(),
        source_control_port=_NeverCalledSourceControl(),
        workspace_root=tmp_path,
    )

    result = graph.invoke({"request_id": "req-lambda-001", "resource_spec": spec})

    # As with SQS/S3/DynamoDB: a clean PASS security result durably
    # pauses for human approval rather than terminating by itself. No
    # checkpointer here, so it cannot be resumed — see
    # test_lambda_workflow_persistence.py for the full interrupt ->
    # reconstruct -> resume proof.
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["current_stage"] is WorkflowStage.APPROVAL
    assert result.get("error") is None
    assert "__interrupt__" in result

    # Observed empirically (see
    # tests/integration/test_lambda_renderer_terraform.py): the secure
    # baseline Lambda+IAM module always plans exactly four resources.
    plan_summary = result["plan_summary"]
    assert plan_summary.add_count == 4
    assert plan_summary.change_count == 0
    assert plan_summary.destroy_count == 0
    assert plan_summary.destructive_change_detected is False

    assert result["platform_evaluation"].overall_status.value == "pass"

    checkov_result = result["checkov_result"]
    assert checkov_result.failed_checks == 0
    assert checkov_result.findings == ()

    assert result["security_gate"].overall_status.value == "pass"

    # Batch 12 invariant, proven again for Lambda: the raw plan JSON
    # field does not exist in WorkflowState at all.
    assert result.get("terraform_plan_json") is None
    assert "terraform_plan_json" not in result

    assert result["workspace"] == tmp_path / "req-lambda-001"
