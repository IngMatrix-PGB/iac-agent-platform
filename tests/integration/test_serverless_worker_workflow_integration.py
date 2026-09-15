"""Integration proof: the real LangGraph workflow over the real
serverless-worker composition pipeline (Batch 19).

ServerlessWorkerSpec -> build_iac_workflow(...).invoke(...) using the
real `IacRenderer` (dispatching to
`ServerlessWorkerTerraformRenderer`), the real `TerraformRunner` (real
Terraform binary), the three real trusted modules
(`terraform/modules/{sqs,lambda,dynamodb}`) plus the composition-owned
event source mapping and IAM policies, and the real `CheckovAdapter`
(real Checkov binary; the graph's `checkov_scan` node selects the
approved composition `CheckovScanProfile` via
`composition_checkov_profile_for` — see
`docs/compositions/serverless-worker.md` for why those six skipped
checks are documented Phase 2 scope exclusions, not suppressed security
weaknesses). No AWS credentials, no `terraform apply`.

This is the ONE required primary real-tool full-pipeline test for
Batch 19, mirroring
tests/integration/test_lambda_workflow_integration.py exactly, proving
`build_iac_workflow` works end-to-end for a composition request — a
request whose trusted-module relationships span three modules — with
no new graph node anywhere.
"""

from __future__ import annotations

import shutil

import pytest

from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus
from iac_agent.execution.terraform_runner import TerraformRunner
from iac_agent.graph.workflow import build_iac_workflow
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.renderer import AWSResourceRenderer
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
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


def test_real_workflow_passes_for_a_secure_default_composition_request(
    tmp_path, terraform_test_env
):
    spec = ServerlessWorkerSpec(
        name="orders-worker",
        queue=SQSResourceSpec(name="orders-queue"),
        function=LambdaResourceSpec(
            name="orders-processor", handler="app.handler", reserved_concurrency=5
        ),
        table=DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
    )

    graph = build_iac_workflow(
        renderer=AWSResourceRenderer(),
        terraform_runner=TerraformRunner(base_env=terraform_test_env),
        checkov_adapter=CheckovAdapter(),
        source_control_port=_NeverCalledSourceControl(),
        workspace_root=tmp_path,
    )

    result = graph.invoke({"request_id": "req-worker-001", "resource_spec": spec})

    # As with SQS/S3/DynamoDB/Lambda: a clean PASS security result
    # durably pauses for human approval rather than terminating by
    # itself. No checkpointer here, so it cannot be resumed — see
    # test_serverless_worker_workflow_persistence.py for the full
    # interrupt -> reconstruct -> resume proof.
    assert result["workflow_status"] is WorkflowStatus.AWAITING_APPROVAL
    assert result["current_stage"] is WorkflowStage.APPROVAL
    assert result.get("error") is None
    assert "__interrupt__" in result

    # Observed empirically (see
    # tests/integration/test_serverless_worker_renderer_terraform.py):
    # the secure baseline composition always plans exactly ten
    # resources.
    plan_summary = result["plan_summary"]
    assert plan_summary.add_count == 10
    assert plan_summary.change_count == 0
    assert plan_summary.destroy_count == 0
    assert plan_summary.destructive_change_detected is False

    assert result["platform_evaluation"].overall_status.value == "pass"

    checkov_result = result["checkov_result"]
    assert checkov_result.failed_checks == 0
    assert checkov_result.findings == ()

    assert result["security_gate"].overall_status.value == "pass"

    # Batch 12 invariant, proven again for the serverless-worker
    # composition: the raw plan JSON field does not exist in
    # WorkflowState at all.
    assert result.get("terraform_plan_json") is None
    assert "terraform_plan_json" not in result

    assert result["workspace"] == tmp_path / "req-worker-001"
