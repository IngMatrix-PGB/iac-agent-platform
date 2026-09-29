"""Public list rows copy six fields and drop checkpoint internals."""

from __future__ import annotations

from iac_agent.api.project import project_list_item
from iac_agent.api.schemas import RequestResponse
from iac_agent.app.service import WorkflowView
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.security import (
    FindingSource,
    PolicyStatus,
    SecurityFinding,
    SecurityGateResult,
    SecuritySeverity,
)
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus

_SENTINELS = (
    "module.queue.aws_sqs_queue.this",
    "arn:aws:sqs:us-east-1:123456789012:hidden",
    "HIDDEN_FINDING_MESSAGE",
    "HIDDEN_WORKFLOW_ERROR_MESSAGE",
    "/var/lib/iac-agent/workspaces/secret",
    "HIDDEN_CHECKPOINT_SENTINEL",
    "example-owner",
    "example-repository",
    "ghp_exampleTokenShouldNeverRender",
    'resource "aws_sqs_queue"',
)


def _hostile_view() -> WorkflowView:
    finding = SecurityFinding(
        policy_id="SQS_ENCRYPTION",
        severity=SecuritySeverity.HIGH,
        status=PolicyStatus.PASS,
        resource="arn:aws:sqs:us-east-1:123456789012:hidden",
        message="HIDDEN_FINDING_MESSAGE",
        source=FindingSource.PLATFORM_POLICY,
    )
    return WorkflowView(
        request_id="req-1",
        workflow_status=WorkflowStatus.AWAITING_APPROVAL,
        current_stage=WorkflowStage.APPROVAL,
        resource_name="orders",
        security_status="pass",
        plan_summary=PlanSummary(
            resource_changes=(
                ResourceChange(
                    address="module.queue.aws_sqs_queue.this",
                    actions=("create",),
                    action=PlanAction.CREATE,
                    replacement=False,
                    destructive=False,
                ),
            ),
            resources_to_add=("module.queue.aws_sqs_queue.this",),
            resources_to_change=(),
            resources_to_destroy=(),
            destructive_change_detected=False,
        ),
        approval_decision=None,
        pull_request=PullRequestResult(
            number=7,
            url="https://example.invalid/pull/7",
            branch="example-owner/example-repository",
            base_branch="main",
        ),
        error=WorkflowError(
            stage=WorkflowStage.ERROR,
            error_type="RuntimeError",
            message=(
                "HIDDEN_WORKFLOW_ERROR_MESSAGE /var/lib/iac-agent/workspaces/secret "
                "HIDDEN_CHECKPOINT_SENTINEL example-owner example-repository "
                "ghp_exampleTokenShouldNeverRender resource \"aws_sqs_queue\""
            ),
        ),
        security_gate=SecurityGateResult(findings=(finding,)),
    )


def test_project_list_item_keeps_only_the_public_row():
    item = project_list_item(_hostile_view(), created_at="2026-09-29T00:00:00.000000Z")
    dumped = item.model_dump()
    assert dumped == {
        "request_id": "req-1",
        "created_at": "2026-09-29T00:00:00.000000Z",
        "workflow_status": "awaiting_approval",
        "approval_available": True,
        "security_status": "pass",
        "name": "orders",
    }
    text = item.model_dump_json()
    for sentinel in _SENTINELS:
        assert sentinel not in text
    assert "https://example.invalid/pull/7" not in text


def test_missing_security_and_name_are_null_and_blocked_is_not_approvable():
    view = WorkflowView(
        request_id="req-2",
        workflow_status=WorkflowStatus.BLOCKED,
        current_stage=None,
        resource_name=None,
        security_status=None,
        plan_summary=None,
        approval_decision=None,
        pull_request=None,
        error=None,
    )
    dumped = project_list_item(view, created_at="2026-09-29T00:00:01.000000Z").model_dump()
    assert dumped["security_status"] is None
    assert dumped["name"] is None
    assert dumped["workflow_status"] == "blocked"
    assert dumped["approval_available"] is False
    assert dumped["created_at"] == "2026-09-29T00:00:01.000000Z"


def test_request_response_did_not_gain_list_fields():
    assert set(RequestResponse.model_fields) == {
        "request_id",
        "outcome",
        "approval_available",
        "terraform_apply",
        "intent",
        "resolution",
        "workflow",
    }
