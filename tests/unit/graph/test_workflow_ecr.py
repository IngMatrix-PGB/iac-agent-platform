"""Unit tests for ECR registration in the workflow graph (Batch 27)."""

from __future__ import annotations

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.security import SecurityGateResult
from iac_agent.graph.modules import default_trusted_module_dirs
from iac_agent.graph.workflow import (
    _RESOURCE_KIND_DISPLAY_NAMES,
    _pr_body,
    _resource_kind_of,
)
from iac_agent.providers.aws.ecr.contract import EcrResourceSpec


def test_ecr_trusted_module_dir_is_registered_and_exists():
    module_dir = default_trusted_module_dirs()[ResourceType.ECR]
    assert module_dir.name == "ecr"
    assert module_dir.is_dir()


def test_ecr_display_name_is_ecr():
    assert _RESOURCE_KIND_DISPLAY_NAMES[ResourceType.ECR] == "ECR"


def test_resource_kind_of_ecr_spec():
    assert _resource_kind_of(EcrResourceSpec(name="orders")) == "ECR"


def test_ecr_spec_is_not_a_composition():
    spec = EcrResourceSpec(name="orders")
    assert not isinstance(spec, (ServerlessWorkerSpec, ApiLambdaSpec, ApiLambdaDynamoDbSpec))


def test_pr_body_uses_the_standalone_resource_lines():
    body = _pr_body(
        {
            "request_id": "req-001",
            "resource_spec": EcrResourceSpec(name="orders"),
            "security_gate": SecurityGateResult(findings=()),
            "plan_summary": PlanSummary(
                resource_changes=(),
                resources_to_add=("module.ecr.aws_ecr_repository.this",),
                resources_to_change=(),
                resources_to_destroy=(),
                destructive_change_detected=False,
            ),
            "approval_decision": ApprovalDecision.APPROVE,
        }
    )
    assert "Resource type: ecr" in body
    assert "Resource: orders" in body
    assert "workspace" not in body
    assert "resource_changes" not in body
