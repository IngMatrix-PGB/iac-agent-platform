"""Decide whether an approval may resume, return, or conflict."""

from __future__ import annotations

from typing import Literal

from iac_agent.app.service import WorkflowView
from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.workflow import WorkflowStatus


def decide_approval(
    view: WorkflowView, decision: ApprovalDecision
) -> Literal["resume", "return_current", "conflict"]:
    status = view.workflow_status
    stored = view.approval_decision
    if status is WorkflowStatus.AWAITING_APPROVAL:
        return "resume"
    if (
        decision is ApprovalDecision.APPROVE
        and stored is ApprovalDecision.APPROVE
        and status in (WorkflowStatus.PR_CREATED, WorkflowStatus.APPROVED)
    ):
        return "return_current"
    if (
        decision is ApprovalDecision.REJECT
        and stored is ApprovalDecision.REJECT
        and status is WorkflowStatus.REJECTED
    ):
        return "return_current"
    return "conflict"
