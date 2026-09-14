"""Domain models for the deterministic SQS workflow.

These describe workflow-level facts (status, stage, error) — they
carry no orchestration logic themselves (that lives in
``iac_agent.graph``) and no security/policy logic (already owned by
``iac_agent.policies`` and ``iac_agent.security``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class WorkflowStatus(StrEnum):
    """The overall lifecycle status of one workflow run.

    This is workflow *lifecycle*, deliberately distinct from the
    deterministic *security outcome* (``SecurityGateResult.overall_status``,
    which stays ``PASS``/``WARN``/``BLOCK`` and is never rewritten by
    human approval — see ``iac_agent.domain.security.PolicyStatus``).
    Batch 13 removed the ``PASS``/``WARN`` workflow statuses that
    existed before the human approval gate: with an approval gate in
    the graph, a deterministic PASS/WARN result is no longer a terminal
    workflow outcome by itself, and keeping both a
    ``WorkflowStatus.PASS`` and a ``SecurityGateResult.overall_status ==
    PASS`` would be exactly the ambiguous duplicate state this project
    avoids elsewhere.

    BLOCKED and ERROR are deliberately distinct: BLOCKED means security
    evidence was completed successfully and explicitly rejected the
    change (``SecurityGateResult.overall_status == BLOCK``) — this
    workflow never reaches human review. ERROR means reliable security
    evidence could not be obtained at all (a Terraform, plan-analysis,
    Checkov, security-gate, or approval-decision boundary raised) — the
    two must never be collapsed into one meaning, and neither ever
    reaches human review either.

    AWAITING_APPROVAL means a PASS or WARN security result is durably
    paused for human review. APPROVED/REJECTED are the only two
    terminal outcomes reachable from AWAITING_APPROVAL.
    """

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    ERROR = "error"


class WorkflowStage(StrEnum):
    """A bounded, deterministic set of workflow stage names."""

    RENDER = "render"
    TERRAFORM = "terraform"
    PLAN_ANALYSIS = "plan_analysis"
    PLATFORM_POLICY = "platform_policy"
    CHECKOV = "checkov"
    SECURITY_GATE = "security_gate"
    APPROVAL = "approval"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass(frozen=True)
class WorkflowError:
    """A safe, structured representation of a workflow-stage failure.

    Deliberately excludes the original exception object, any traceback,
    subprocess stdout/stderr, environment values, or raw Terraform/
    Checkov JSON — only the stage, the exception's type name, and a
    length-bounded message are kept.
    """

    stage: WorkflowStage
    error_type: str
    message: str


def validate_request_id(request_id: str) -> str:
    """The single request-ID safety rule shared by the workspace path
    resolver (``iac_agent.graph.workflow``) and the checkpoint thread-ID
    mapping (``iac_agent.persistence.checkpoints``) — deliberately one
    rule set, not two that could drift apart.

    A ``request_id`` must be a non-empty, simple path-segment-safe
    string: no path separators, no parent-directory references, and
    never shaped like an absolute path. It is never treated as a
    trusted filesystem path or thread identifier without this check.
    """
    if not request_id:
        raise ValueError("request_id must be a non-empty string")

    candidate = Path(request_id)
    if candidate.is_absolute():
        raise ValueError(f"request_id must not be an absolute path: {request_id!r}")
    if candidate.name != request_id or ".." in candidate.parts:
        raise ValueError(
            "request_id must be a simple path segment with no separators or "
            f"parent-directory references, got {request_id!r}"
        )
    return request_id
