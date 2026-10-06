"""Public HTTP projection. Denied domain facts have no DTO field."""

from __future__ import annotations

from iac_agent.app.service import WorkflowView
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecurityGateResult,
    SecuritySeverity,
)
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.resolver import (
    ClarificationReason,
    ClarificationRequest,
    ClarificationRequired,
    ResolvedArchitecture,
    UnsupportedArchitecture,
    UnsupportedReason,
)
from iac_agent.intent.service import IntentSubmissionResult
from iac_agent.providers.aws.ecr.contract import EcrResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec


def _intent(**overrides) -> ArchitectureIntent:
    values = {
        "workload_type": WorkloadType.STORAGE,
        "interaction_pattern": InteractionPattern.UNSPECIFIED,
        "capabilities": frozenset({Capability.OBJECT_STORAGE}),
        "logical_name_hint": "hint-not-sent",
        "assumptions": ("build a bucket named order-events",),
        "unresolved_questions": ("what region?",),
    }
    values.update(overrides)
    return ArchitectureIntent(**values)


def _view() -> WorkflowView:
    finding = SecurityFinding(
        policy_id="CKV_AWS_27",
        severity=SecuritySeverity.HIGH,
        status=PolicyStatus.PASS,
        resource="module.queue.aws_sqs_queue.this",
        message="Checkov CKV_AWS_27 failed. account 123456789012",
        source=FindingSource.CHECKOV,
    )
    return WorkflowView(
        request_id="req-001",
        workflow_status=WorkflowStatus.ERROR,
        current_stage=WorkflowStage.ERROR,
        resource_name="order-events",
        security_status="pass",
        plan_summary=PlanSummary(
            resource_changes=(),
            resources_to_add=("module.queue.aws_sqs_queue.this",),
            resources_to_change=("arn:aws:s3:::order-events",),
            resources_to_destroy=(),
            destructive_change_detected=False,
        ),
        approval_decision=None,
        pull_request=PullRequestResult(
            number=7,
            url="https://example.invalid/pull/7",
            branch="iac-agent/req-001",
            base_branch="main",
        ),
        error=WorkflowError(
            stage=WorkflowStage.TERRAFORM,
            error_type="TerraformCommandError",
            message="benign failure\n# fake terraform",
        ),
        security_gate=SecurityGateResult(findings=(finding,)),
    )


def _submission(**overrides) -> IntentSubmissionResult:
    values = {
        "request_id": "req-001",
        "intent": _intent(),
        "resolution": ResolvedArchitecture(
            request_spec=SQSResourceSpec(name="order-events"),
            matched_pattern="storage+object_storage",
        ),
        "workflow_view": _view(),
    }
    values.update(overrides)
    return IntentSubmissionResult(**values)


def test_projection_keeps_names_and_url_and_drops_denied_text():
    from iac_agent.api.project import project_submission

    body = project_submission(_submission())
    rendered = body.model_dump_json()
    assert body.resolution.name == "order-events"
    assert body.workflow is not None
    assert body.workflow.pull_request is not None
    assert body.workflow.pull_request.url == "https://example.invalid/pull/7"
    assert body.workflow.findings[0].model_dump() == {
        "policy_id": "CKV_AWS_27",
        "status": "pass",
        "severity": "high",
    }
    assert body.workflow.error is not None
    assert body.workflow.error.error_type == "TerraformCommandError"
    assert "message" not in body.workflow.error.model_dump()
    for needle in (
        "module.queue.aws_sqs_queue.this",
        "arn:aws:s3:::order-events",
        "123456789012",
        "Checkov CKV_AWS_27 failed.",
        "benign failure",
        "iac-agent/req-001",
        "build a bucket named order-events",
        "# fake terraform",
        "hint-not-sent",
        "what region?",
    ):
        assert needle not in rendered
    assert "branch" not in body.workflow.pull_request.model_dump()
    assert "source" not in body.workflow.findings[0].model_dump()


def test_clarification_has_no_workflow():
    from iac_agent.api.project import project_submission

    body = project_submission(
        _submission(
            resolution=ClarificationRequired(
                request=ClarificationRequest(
                    reason=ClarificationReason.WORKLOAD_TYPE_REQUIRED,
                    field="workload_type",
                    allowed_values=("api", "worker", "storage"),
                )
            ),
            workflow_view=None,
        )
    )
    assert body.outcome == "clarification_required"
    assert body.approval_available is False
    assert body.workflow is None
    assert body.resolution.field == "workload_type"
    assert body.resolution.reason == "workload_type_required"


def test_unsupported_keeps_resolver_detail():
    from iac_agent.api.project import project_submission

    body = project_submission(
        _submission(
            resolution=UnsupportedArchitecture(
                reason=UnsupportedReason.UNSUPPORTED_CAPABILITY,
                detail="no such capability",
            ),
            workflow_view=None,
        )
    )
    assert body.outcome == "unsupported"
    assert body.workflow is None
    assert body.resolution.detail == "no such capability"
    assert body.resolution.reason == "unsupported_capability"


def test_ecr_component_exposes_mutability_and_scan():
    from iac_agent.api.project import project_submission

    body = project_submission(
        _submission(
            intent=_intent(capabilities=frozenset({Capability.CONTAINER_REGISTRY})),
            resolution=ResolvedArchitecture(
                request_spec=EcrResourceSpec(name="orders"),
                matched_pattern="storage+container_registry",
            ),
        )
    )
    assert body.resolution.architecture == "ecr"
    assert body.resolution.components[0].model_dump() == {
        "role": "repository",
        "name": "orders",
        "image_tag_mutability": "IMMUTABLE",
        "scan_on_push": True,
    }


def test_project_view_reconstructs_architecture_and_components_from_the_checkpoint_spec():
    from dataclasses import replace

    from iac_agent.api.project import project_view
    from iac_agent.compositions.api_lambda.contract import HttpMethod, RouteSpec
    from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
    from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
    from iac_agent.providers.aws.dynamodb.contract import (
        DynamoDBKeySpec,
        DynamoDBKeyType,
        DynamoDBResourceSpec,
    )
    from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec

    spec = ApiLambdaDynamoDbSpec(
        name="orders",
        api=ApiGatewayResourceSpec(name="orders-api"),
        function=LambdaResourceSpec(name="orders-function", handler="app.handler"),
        route=RouteSpec(method=HttpMethod.POST, path="/invoke"),
        table=DynamoDBResourceSpec(
            name="orders-table",
            partition_key=DynamoDBKeySpec(name="id", type=DynamoDBKeyType.STRING),
        ),
    )

    body = project_view(replace(_view(), resource_spec=spec))

    assert body.resolution.architecture == "API Gateway + Lambda + DynamoDB"
    assert [(item.role, item.name) for item in body.resolution.components] == [
        ("api", "orders-api"),
        ("route", "POST /invoke"),
        ("function", "orders-function"),
        ("table", "orders-table"),
    ]
    assert body.resolution.matched_pattern is None
    assert body.intent is None


def test_project_view_without_a_spec_keeps_architecture_absent():
    from iac_agent.api.project import project_view

    body = project_view(_view())
    assert body.resolution.architecture is None
    assert body.resolution.components == []
