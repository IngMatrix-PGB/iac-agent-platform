"""The explicit LangGraph state schema for the SQS workflow.

Deliberately a plain ``TypedDict`` of explicit workflow facts — never
``MessagesState``. There is no message history anywhere in this state;
every field here is inspectable, typed application data, reusing the
existing domain models (``SQSResourceSpec``, ``PlanSummary``,
``PolicyEvaluation``, ``CheckovScanResult``, ``SecurityGateResult``)
rather than re-serializing them into arbitrary dicts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import PolicyEvaluation, SecurityGateResult
from iac_agent.domain.workflow import WorkflowError, WorkflowStage, WorkflowStatus
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.security.checkov import CheckovScanResult


class WorkflowState(TypedDict, total=False):
    """Explicit workflow state — every field is a workflow fact, not a
    message. ``request_id`` and ``resource_spec`` must be present in the
    initial invocation; every other field is populated progressively by
    the graph's nodes.

    ``terraform_plan_json`` is a deliberately transient handoff between
    ``terraform_execute`` and ``plan_analysis`` — the latter clears it
    (sets it back to ``None``) once ``PlanSummary`` has been derived, so
    raw Terraform plan JSON never survives into a completed workflow's
    final state.
    """

    request_id: str
    resource_spec: SQSResourceSpec

    workspace: Path
    generated_files: dict[str, str] | None

    terraform_plan_json: dict[str, Any] | None
    plan_summary: PlanSummary | None

    platform_evaluation: PolicyEvaluation | None
    checkov_result: CheckovScanResult | None
    security_gate: SecurityGateResult | None

    workflow_status: WorkflowStatus
    current_stage: WorkflowStage
    error: WorkflowError | None
