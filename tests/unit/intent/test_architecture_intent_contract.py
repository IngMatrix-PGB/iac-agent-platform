"""Contract tests for `ArchitectureIntent` and its supporting vocabularies
(Batch 21, Task 1).

These tests prove the semantic contract only — nothing here exercises
`ArchitectureResolver` (Task 4) or the interpreter boundary (Task 5).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from iac_agent.intent.models import (
    ArchitectureIntent,
    AwsServiceHint,
    Capability,
    InteractionPattern,
    WorkloadType,
)


def test_minimal_valid_intent_constructs_with_defaults():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )
    assert intent.workload_type == WorkloadType.API
    assert intent.interaction_pattern == InteractionPattern.SYNCHRONOUS
    assert intent.capabilities == frozenset({Capability.HTTP_ENDPOINT})
    assert intent.logical_name_hint is None
    assert intent.user_provided_hints == ()
    assert intent.assumptions == ()
    assert intent.unresolved_questions == ()


def test_schema_version_defaults_to_literal_1():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.OBJECT_STORAGE}),
    )
    assert intent.schema_version == "1"


def test_frozen_instance_raises_on_mutation():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.OBJECT_STORAGE}),
    )
    with pytest.raises(ValidationError):
        intent.workload_type = WorkloadType.API


def test_capabilities_accepts_frozenset_and_deduplicates():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.WORKER,
        interaction_pattern=InteractionPattern.ASYNCHRONOUS,
        capabilities=frozenset(
            {Capability.QUEUE_PROCESSING, Capability.PERSISTENCE, Capability.QUEUE_PROCESSING}
        ),
    )
    assert intent.capabilities == frozenset({Capability.QUEUE_PROCESSING, Capability.PERSISTENCE})


def test_unknown_capability_string_rejected():
    with pytest.raises(ValidationError):
        ArchitectureIntent.model_validate(
            {
                "workload_type": "api",
                "interaction_pattern": "synchronous",
                "capabilities": ["background_processing"],
            }
        )


def test_unknown_workload_type_string_rejected():
    with pytest.raises(ValidationError):
        ArchitectureIntent.model_validate(
            {
                "workload_type": "database",
                "interaction_pattern": "synchronous",
                "capabilities": ["http_endpoint"],
            }
        )


def test_unknown_interaction_pattern_string_rejected():
    with pytest.raises(ValidationError):
        ArchitectureIntent.model_validate(
            {
                "workload_type": "api",
                "interaction_pattern": "eventual",
                "capabilities": ["http_endpoint"],
            }
        )


def test_unknown_aws_service_hint_string_rejected():
    with pytest.raises(ValidationError):
        ArchitectureIntent.model_validate(
            {
                "workload_type": "api",
                "interaction_pattern": "synchronous",
                "capabilities": ["http_endpoint"],
                "user_provided_hints": ["aurora"],
            }
        )


def test_logical_name_hint_over_max_length_rejected():
    with pytest.raises(ValidationError):
        ArchitectureIntent(
            workload_type=WorkloadType.API,
            interaction_pattern=InteractionPattern.SYNCHRONOUS,
            capabilities=frozenset({Capability.HTTP_ENDPOINT}),
            logical_name_hint="x" * 129,
        )


def test_user_provided_hints_over_max_count_rejected():
    with pytest.raises(ValidationError):
        ArchitectureIntent(
            workload_type=WorkloadType.API,
            interaction_pattern=InteractionPattern.SYNCHRONOUS,
            capabilities=frozenset({Capability.HTTP_ENDPOINT}),
            user_provided_hints=tuple(AwsServiceHint.SQS for _ in range(9)),
        )


def test_assumptions_over_max_count_rejected():
    with pytest.raises(ValidationError):
        ArchitectureIntent(
            workload_type=WorkloadType.API,
            interaction_pattern=InteractionPattern.SYNCHRONOUS,
            capabilities=frozenset({Capability.HTTP_ENDPOINT}),
            assumptions=tuple(f"assumption {i}" for i in range(9)),
        )


def test_unresolved_questions_over_max_count_rejected():
    with pytest.raises(ValidationError):
        ArchitectureIntent(
            workload_type=WorkloadType.API,
            interaction_pattern=InteractionPattern.SYNCHRONOUS,
            capabilities=frozenset({Capability.HTTP_ENDPOINT}),
            unresolved_questions=tuple(f"question {i}" for i in range(9)),
        )


def test_confidence_below_zero_rejected():
    with pytest.raises(ValidationError):
        ArchitectureIntent(
            workload_type=WorkloadType.API,
            interaction_pattern=InteractionPattern.SYNCHRONOUS,
            capabilities=frozenset({Capability.HTTP_ENDPOINT}),
            confidence=-0.01,
        )


def test_confidence_above_one_rejected():
    with pytest.raises(ValidationError):
        ArchitectureIntent(
            workload_type=WorkloadType.API,
            interaction_pattern=InteractionPattern.SYNCHRONOUS,
            capabilities=frozenset({Capability.HTTP_ENDPOINT}),
            confidence=1.01,
        )


def test_confidence_defaults_to_none():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )
    assert intent.confidence is None


def test_two_intents_with_capabilities_in_different_order_are_equal():
    first = ArchitectureIntent(
        workload_type=WorkloadType.WORKER,
        interaction_pattern=InteractionPattern.ASYNCHRONOUS,
        capabilities=frozenset({Capability.QUEUE_PROCESSING, Capability.PERSISTENCE}),
    )
    second = ArchitectureIntent(
        workload_type=WorkloadType.WORKER,
        interaction_pattern=InteractionPattern.ASYNCHRONOUS,
        capabilities=frozenset({Capability.PERSISTENCE, Capability.QUEUE_PROCESSING}),
    )
    assert first == second
