"""Mechanical proofs that `confidence`, `assumptions`,
`user_provided_hints`, and `unresolved_questions` never change
`ArchitectureResolver.resolve()`'s output (Batch 21, Task 4, spec
§4.2-§4.5, §19).

These are direct, mechanical proofs — not comments claiming the
invariant holds.
"""

from __future__ import annotations

import inspect

from iac_agent.intent import resolver as resolver_module
from iac_agent.intent.models import (
    ArchitectureIntent,
    AwsServiceHint,
    Capability,
    InteractionPattern,
    WorkloadType,
)
from iac_agent.intent.resolver import ArchitectureResolver
from iac_agent.providers.aws.s3.contract import S3ResourceSpec

_REQUEST_ID = "req-001"


def _base_kwargs() -> dict:
    return dict(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )


def test_confidence_does_not_change_resolution_result():
    resolver = ArchitectureResolver()
    low = ArchitectureIntent(**_base_kwargs(), confidence=0.01)
    high = ArchitectureIntent(**_base_kwargs(), confidence=0.99)
    none = ArchitectureIntent(**_base_kwargs(), confidence=None)

    results = [resolver.resolve(intent=i, request_id=_REQUEST_ID) for i in (low, high, none)]
    assert all(r.outcome == results[0].outcome for r in results)
    assert all(r.matched_pattern == results[0].matched_pattern for r in results)


def test_assumptions_do_not_change_resolution_result():
    resolver = ArchitectureResolver()
    empty = ArchitectureIntent(**_base_kwargs(), assumptions=())
    populated = ArchitectureIntent(
        **_base_kwargs(), assumptions=("user probably wants this to be public",)
    )

    first = resolver.resolve(intent=empty, request_id=_REQUEST_ID)
    second = resolver.resolve(intent=populated, request_id=_REQUEST_ID)
    assert first.outcome == second.outcome
    assert first.matched_pattern == second.matched_pattern


def test_user_provided_hints_do_not_change_resolution_result():
    resolver = ArchitectureResolver()
    no_hints = ArchitectureIntent(**_base_kwargs(), user_provided_hints=())
    misleading_hints = ArchitectureIntent(
        **_base_kwargs(), user_provided_hints=(AwsServiceHint.DYNAMODB,)
    )

    first = resolver.resolve(intent=no_hints, request_id=_REQUEST_ID)
    second = resolver.resolve(intent=misleading_hints, request_id=_REQUEST_ID)
    assert first.outcome == second.outcome
    assert first.matched_pattern == second.matched_pattern


def test_unresolved_questions_do_not_change_resolution_result():
    resolver = ArchitectureResolver()
    empty = ArchitectureIntent(**_base_kwargs(), unresolved_questions=())
    populated = ArchitectureIntent(
        **_base_kwargs(), unresolved_questions=("is this the right pattern?",)
    )

    first = resolver.resolve(intent=empty, request_id=_REQUEST_ID)
    second = resolver.resolve(intent=populated, request_id=_REQUEST_ID)
    assert first.outcome == second.outcome
    assert first.matched_pattern == second.matched_pattern


def test_resolver_source_contains_no_confidence_attribute_reference():
    source = inspect.getsource(resolver_module)
    assert ".confidence" not in source


def test_misleading_aws_hint_does_not_override_semantic_resolution():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.OBJECT_STORAGE}),
        user_provided_hints=(AwsServiceHint.LAMBDA,),
    )
    result = ArchitectureResolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result.request_spec, S3ResourceSpec)
