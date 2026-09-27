"""Approval idempotency is a pure function of the durable view."""

from __future__ import annotations

from iac_agent.app.service import WorkflowView
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.workflow import WorkflowStage, WorkflowStatus


def _view(status: WorkflowStatus, decision: ApprovalDecision | None = None) -> WorkflowView:
    return WorkflowView(
        request_id="req-001",
        workflow_status=status,
        current_stage=WorkflowStage.COMPLETE,
        resource_name="order-events",
        security_status=None,
        plan_summary=None,
        approval_decision=decision,
        pull_request=None,
        error=None,
    )


def test_decide_approval_table():
    from iac_agent.api.approval import decide_approval

    awaiting = _view(WorkflowStatus.AWAITING_APPROVAL)
    assert decide_approval(awaiting, ApprovalDecision.APPROVE) == "resume"
    assert decide_approval(awaiting, ApprovalDecision.REJECT) == "resume"
    assert (
        decide_approval(
            _view(WorkflowStatus.PR_CREATED, ApprovalDecision.APPROVE),
            ApprovalDecision.APPROVE,
        )
        == "return_current"
    )
    assert (
        decide_approval(
            _view(WorkflowStatus.APPROVED, ApprovalDecision.APPROVE),
            ApprovalDecision.APPROVE,
        )
        == "return_current"
    )
    assert (
        decide_approval(
            _view(WorkflowStatus.REJECTED, ApprovalDecision.REJECT),
            ApprovalDecision.REJECT,
        )
        == "return_current"
    )
    assert (
        decide_approval(
            _view(WorkflowStatus.REJECTED, ApprovalDecision.REJECT),
            ApprovalDecision.APPROVE,
        )
        == "conflict"
    )
    assert (
        decide_approval(
            _view(WorkflowStatus.PR_CREATED, ApprovalDecision.APPROVE),
            ApprovalDecision.REJECT,
        )
        == "conflict"
    )
    assert decide_approval(_view(WorkflowStatus.BLOCKED), ApprovalDecision.APPROVE) == "conflict"
    assert decide_approval(_view(WorkflowStatus.BLOCKED), ApprovalDecision.REJECT) == "conflict"
    assert (
        decide_approval(
            _view(WorkflowStatus.ERROR, ApprovalDecision.APPROVE),
            ApprovalDecision.APPROVE,
        )
        == "conflict"
    )
