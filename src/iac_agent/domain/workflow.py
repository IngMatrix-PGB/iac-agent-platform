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
    """The overall status of one workflow run.

    BLOCKED and ERROR are deliberately distinct: BLOCKED means security
    evidence was completed successfully and explicitly rejected the
    change (``SecurityGateResult.overall_status == BLOCK``). ERROR
    means reliable security evidence could not be obtained at all
    (a Terraform, plan-analysis, Checkov, or security-gate boundary
    raised) — the two must never be collapsed into one meaning.
    """

    PENDING = "pending"
    RUNNING = "running"
    PASS = "pass"
    WARN = "warn"
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
