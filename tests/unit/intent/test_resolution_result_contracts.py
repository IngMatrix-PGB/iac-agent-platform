"""Contract tests for the `ResolutionResult` discriminated union
(Batch 21, Task 2).

These tests prove the result-shape types only. `ArchitectureResolver`
itself (the logic that produces these values) is Task 4's addition to
this same module.
"""

from __future__ import annotations

import dataclasses

import pytest

from iac_agent.intent.resolver import (
    ClarificationReason,
    ClarificationRequest,
    ClarificationRequired,
    ResolvedArchitecture,
    UnsupportedArchitecture,
    UnsupportedReason,
)


def test_resolved_architecture_outcome_literal_is_resolved():
    result = ResolvedArchitecture(
        request_spec=object(), matched_pattern="api+synchronous+http_endpoint"
    )
    assert result.outcome == "resolved"


def test_clarification_required_outcome_literal_is_clarification_required():
    request = ClarificationRequest(
        reason=ClarificationReason.WORKLOAD_TYPE_REQUIRED,
        field="workload_type",
        allowed_values=("api", "worker", "storage"),
    )
    result = ClarificationRequired(request=request)
    assert result.outcome == "clarification_required"


def test_unsupported_architecture_outcome_literal_is_unsupported():
    result = UnsupportedArchitecture(
        reason=UnsupportedReason.UNSUPPORTED_COMBINATION, detail="not a supported combination"
    )
    assert result.outcome == "unsupported"


def test_resolution_result_union_narrows_via_match_case():
    request = ClarificationRequest(
        reason=ClarificationReason.INTERACTION_PATTERN_REQUIRED,
        field="interaction_pattern",
        allowed_values=("synchronous", "asynchronous"),
    )
    results = [
        ResolvedArchitecture(request_spec=object(), matched_pattern="storage+object_storage"),
        ClarificationRequired(request=request),
        UnsupportedArchitecture(reason=UnsupportedReason.UNSUPPORTED_WORKLOAD, detail="x"),
    ]
    labels = []
    for result in results:
        match result:
            case ResolvedArchitecture():
                labels.append("resolved")
            case ClarificationRequired():
                labels.append("clarification_required")
            case UnsupportedArchitecture():
                labels.append("unsupported")
    assert labels == ["resolved", "clarification_required", "unsupported"]


def test_resolved_architecture_is_frozen():
    result = ResolvedArchitecture(request_spec=object(), matched_pattern="storage+object_storage")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.matched_pattern = "changed"


def test_clarification_required_is_frozen():
    request = ClarificationRequest(
        reason=ClarificationReason.WORKLOAD_TYPE_REQUIRED,
        field="workload_type",
        allowed_values=("api", "worker", "storage"),
    )
    result = ClarificationRequired(request=request)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.request = request


def test_unsupported_architecture_is_frozen():
    result = UnsupportedArchitecture(reason=UnsupportedReason.UNSUPPORTED_CAPABILITY, detail="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.detail = "changed"


def test_clarification_reason_values_are_exactly_two():
    assert {member.value for member in ClarificationReason} == {
        "workload_type_required",
        "interaction_pattern_required",
    }


def test_unsupported_reason_values_are_exactly_three():
    assert {member.value for member in UnsupportedReason} == {
        "unsupported_workload",
        "unsupported_capability",
        "unsupported_combination",
    }
