"""Copy named allowlisted fields into telemetry models.

The input objects are not returned and are not forwarded.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from iac_agent.app.service import WorkflowView
from iac_agent.intent.models import ArchitectureIntent
from iac_agent.intent.resolver import (
    ClarificationRequired,
    ResolutionResult,
    ResolvedArchitecture,
    UnsupportedArchitecture,
)
from iac_agent.observability.models import (
    FindingTelemetry,
    GenerationTelemetry,
    ResolutionTelemetry,
    WorkflowTelemetry,
)

_WORKFLOW_KINDS = frozenset({"submit", "resume", "terminal"})


def project_generation(metadata: Mapping[str, Any]) -> GenerationTelemetry:
    return GenerationTelemetry(
        request_id=str(metadata["request_id"]),
        provider=str(metadata["provider"]),
        model=str(metadata["model"]),
        prompt_version=str(metadata["prompt_version"]),
        latency_ms=float(metadata["latency_ms"]),
        attempt_count=int(metadata["attempt_count"]),
        outcome_category=str(metadata["outcome_category"]),
        input_tokens=_optional_int(metadata, "input_tokens"),
        output_tokens=_optional_int(metadata, "output_tokens"),
    )


def project_resolution(
    request_id: str,
    intent: ArchitectureIntent,
    resolution: ResolutionResult,
) -> ResolutionTelemetry:
    matched_pattern = None
    resolved_type = None
    clarification_reason = None
    unsupported_reason = None
    match resolution:
        case ResolvedArchitecture():
            matched_pattern = resolution.matched_pattern
            resolved_type = type(resolution.request_spec).__name__
        case ClarificationRequired():
            clarification_reason = resolution.request.reason.value
        case UnsupportedArchitecture():
            unsupported_reason = resolution.reason.value
    return ResolutionTelemetry(
        request_id=request_id,
        outcome=resolution.outcome,
        workload_type=intent.workload_type.value,
        interaction_pattern=intent.interaction_pattern.value,
        capabilities=tuple(sorted(item.value for item in intent.capabilities)),
        user_provided_hints=tuple(sorted(item.value for item in intent.user_provided_hints)),
        matched_pattern=matched_pattern,
        resolved_type=resolved_type,
        clarification_reason=clarification_reason,
        unsupported_reason=unsupported_reason,
    )


def project_workflow(
    view: WorkflowView,
    *,
    kind: Literal["submit", "resume", "terminal"],
) -> WorkflowTelemetry:
    if kind not in _WORKFLOW_KINDS:
        raise ValueError(f"unknown workflow telemetry kind: {kind!r}")
    summary = view.plan_summary
    gate = view.security_gate
    error = view.error
    return WorkflowTelemetry(
        request_id=view.request_id,
        kind=kind,
        workflow_status=view.workflow_status.value,
        current_stage=None if view.current_stage is None else view.current_stage.value,
        security_status=view.security_status,
        add_count=None if summary is None else summary.add_count,
        change_count=None if summary is None else summary.change_count,
        destroy_count=None if summary is None else summary.destroy_count,
        destructive_change_detected=(
            None if summary is None else summary.destructive_change_detected
        ),
        findings=(
            ()
            if gate is None
            else tuple(
                FindingTelemetry(
                    policy_id=finding.policy_id,
                    status=finding.status.value,
                    severity=finding.severity.value,
                )
                for finding in gate.findings
            )
        ),
        approval_decision=(
            None if view.approval_decision is None else view.approval_decision.value
        ),
        error_stage=None if error is None else error.stage.value,
        error_type=None if error is None else error.error_type,
        published=view.pull_request is not None,
    )


def _optional_int(metadata: Mapping[str, Any], key: str) -> int | None:
    if key not in metadata or metadata[key] is None:
        return None
    return int(metadata[key])
