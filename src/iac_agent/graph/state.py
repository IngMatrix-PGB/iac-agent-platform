"""The explicit LangGraph state schema for the Phase 1/2 AWS workflow.

Deliberately a plain ``TypedDict`` of explicit workflow facts — never
``MessagesState``. There is no message history anywhere in this state;
every field here is inspectable, typed application data, reusing the
existing domain models (``AWSResourceSpec``, ``PlanSummary``,
``PolicyEvaluation``, ``CheckovScanResult``, ``SecurityGateResult``,
``ApprovalDecision``) rather than re-serializing them into arbitrary
dicts.

Batch 16 (Phase 2) widened ``resource_spec`` from ``SQSResourceSpec`` to
the ``AWSResourceSpec`` union (currently SQS or S3) — a typing-only
change; nothing about how this ``TypedDict`` is constructed, stored, or
checkpointed changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from iac_agent.domain.approval import ApprovalDecision
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyEvaluation, SecurityGateResult
from iac_agent.domain.source_control import PullRequestResult
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus
from iac_agent.providers.aws.resource import AWSResourceSpec
from iac_agent.security.checkov import CheckovScanResult


class WorkflowState(TypedDict, total=False):
    """Explicit workflow state — every field is a workflow fact, not a
    message. ``request_id`` and ``resource_spec`` must be present in the
    initial invocation; every other field is populated progressively by
    the graph's nodes.

    There is deliberately no raw-Terraform-plan-JSON field here (no
    ``terraform_plan_json`` or equivalent). Since Batch 12 durably
    checkpoints every superstep of this state to SQLite, any such field
    would mean a raw Terraform plan could persist to disk even for a
    request whose *final* state never shows it. Instead,
    ``plan_analysis`` reads the raw ``terraform show -json`` result into
    a local variable, derives ``plan_summary`` from it, and returns only
    ``plan_summary`` as a state update — the raw dict never becomes part
    of ``WorkflowState`` at any point, checkpointed or not.

    ``approval_decision`` (Batch 13) holds only the typed
    ``ApprovalDecision`` outcome (``APPROVE``/``REJECT``) once a human
    has reviewed a ``PASS``/``WARN`` security result — never an
    identity, comment, or timestamp field (see
    ``iac_agent.domain.approval``).

    ``pull_request`` (Batch 14) holds only the typed
    ``PullRequestResult`` once an ``APPROVED`` workflow has been
    published to source control — never a GitHub token, a raw GitHub
    HTTP response, or an ``Authorization`` header (see
    ``iac_agent.git``).
    """

    request_id: str
    resource_spec: AWSResourceSpec

    workspace: Path
    generated_files: dict[str, str] | None

    plan_summary: PlanSummary | None

    platform_evaluation: PolicyEvaluation | None
    checkov_result: CheckovScanResult | None
    security_gate: SecurityGateResult | None

    approval_decision: ApprovalDecision | None
    pull_request: PullRequestResult | None

    workflow_status: WorkflowStatus
    current_stage: WorkflowStage
    error: WorkflowError | None
