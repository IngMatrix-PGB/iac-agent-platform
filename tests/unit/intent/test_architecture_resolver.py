"""Tests for `ArchitectureResolver.resolve()` — the closed, fail-closed
allowlist (Batch 21, Task 4, spec §7.1).

Exactly three resolvable architecture patterns exist. There is no
best-match, nearest-match, or fallback architecture anywhere in this
module — an unlisted combination always returns
`UnsupportedArchitecture`, never an approximation.
"""

from __future__ import annotations

import pytest

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.intent.models import ArchitectureIntent, Capability, InteractionPattern, WorkloadType
from iac_agent.intent.resolver import (
    ArchitectureResolver,
    ClarificationReason,
    ClarificationRequired,
    ResolvedArchitecture,
    UnsupportedArchitecture,
    UnsupportedReason,
)
from iac_agent.providers.aws.s3.contract import S3ResourceSpec

_REQUEST_ID = "req-001"


def _resolver() -> ArchitectureResolver:
    return ArchitectureResolver()


def test_api_synchronous_http_endpoint_resolves_to_api_lambda_spec():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ResolvedArchitecture)
    assert isinstance(result.request_spec, ApiLambdaSpec)
    assert result.matched_pattern == "api+synchronous+http_endpoint"


def test_worker_asynchronous_queue_processing_persistence_resolves_to_serverless_worker_spec():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.WORKER,
        interaction_pattern=InteractionPattern.ASYNCHRONOUS,
        capabilities=frozenset({Capability.QUEUE_PROCESSING, Capability.PERSISTENCE}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ResolvedArchitecture)
    assert isinstance(result.request_spec, ServerlessWorkerSpec)
    assert result.matched_pattern == "worker+asynchronous+queue_processing+persistence"


@pytest.mark.parametrize(
    "interaction_pattern",
    [
        InteractionPattern.SYNCHRONOUS,
        InteractionPattern.ASYNCHRONOUS,
        InteractionPattern.UNSPECIFIED,
    ],
)
def test_storage_object_storage_resolves_to_s3_spec_regardless_of_interaction_pattern(
    interaction_pattern,
):
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=interaction_pattern,
        capabilities=frozenset({Capability.OBJECT_STORAGE}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ResolvedArchitecture)
    assert isinstance(result.request_spec, S3ResourceSpec)
    assert result.matched_pattern == "storage+object_storage"


def test_unspecified_workload_type_returns_clarification_required_workload_type_required():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.UNSPECIFIED,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset(),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ClarificationRequired)
    assert result.request.reason == ClarificationReason.WORKLOAD_TYPE_REQUIRED


def test_api_unspecified_interaction_pattern_requires_clarification():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ClarificationRequired)
    assert result.request.reason == ClarificationReason.INTERACTION_PATTERN_REQUIRED


def test_worker_unspecified_interaction_pattern_requires_clarification():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.WORKER,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.QUEUE_PROCESSING, Capability.PERSISTENCE}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ClarificationRequired)
    assert result.request.reason == ClarificationReason.INTERACTION_PATTERN_REQUIRED


def test_api_synchronous_wrong_capability_set_returns_unsupported_combination():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT, Capability.PERSISTENCE}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, UnsupportedArchitecture)
    assert result.reason == UnsupportedReason.UNSUPPORTED_COMBINATION


def test_worker_asynchronous_wrong_capability_set_returns_unsupported_combination():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.WORKER,
        interaction_pattern=InteractionPattern.ASYNCHRONOUS,
        capabilities=frozenset({Capability.QUEUE_PROCESSING}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, UnsupportedArchitecture)
    assert result.reason == UnsupportedReason.UNSUPPORTED_COMBINATION


def test_api_asynchronous_returns_unsupported_combination():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.ASYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, UnsupportedArchitecture)
    assert result.reason == UnsupportedReason.UNSUPPORTED_COMBINATION


def test_worker_synchronous_returns_unsupported_combination():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.WORKER,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.QUEUE_PROCESSING, Capability.PERSISTENCE}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, UnsupportedArchitecture)
    assert result.reason == UnsupportedReason.UNSUPPORTED_COMBINATION


def test_storage_wrong_capability_set_returns_unsupported_capability():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.PERSISTENCE}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, UnsupportedArchitecture)
    assert result.reason == UnsupportedReason.UNSUPPORTED_CAPABILITY


def test_capability_from_wrong_workload_returns_unsupported_combination():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.WORKER,
        interaction_pattern=InteractionPattern.ASYNCHRONOUS,
        capabilities=frozenset(
            {Capability.QUEUE_PROCESSING, Capability.PERSISTENCE, Capability.HTTP_ENDPOINT}
        ),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, UnsupportedArchitecture)
    assert result.reason == UnsupportedReason.UNSUPPORTED_COMBINATION


def test_resolved_architecture_matched_pattern_is_populated_and_stable():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )
    resolver = _resolver()
    first = resolver.resolve(intent=intent, request_id=_REQUEST_ID)
    second = resolver.resolve(intent=intent, request_id=_REQUEST_ID)
    assert first.matched_pattern == second.matched_pattern == "api+synchronous+http_endpoint"


def test_resolved_api_lambda_spec_uses_normalized_logical_name_hint():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
        logical_name_hint="Order Processor",
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ResolvedArchitecture)
    spec: ApiLambdaSpec = result.request_spec
    assert spec.name == "order-processor"
    assert spec.api.name == "order-processor-api"
    assert spec.function.name == "order-processor-function"


def test_resolved_api_lambda_spec_falls_back_to_request_id_derived_name_when_hint_absent():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.SYNCHRONOUS,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ResolvedArchitecture)
    spec: ApiLambdaSpec = result.request_spec
    assert spec.name.startswith("req-")


def test_resolved_serverless_worker_spec_derives_pairwise_distinct_component_names():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.WORKER,
        interaction_pattern=InteractionPattern.ASYNCHRONOUS,
        capabilities=frozenset({Capability.QUEUE_PROCESSING, Capability.PERSISTENCE}),
        logical_name_hint="Order Worker",
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ResolvedArchitecture)
    spec: ServerlessWorkerSpec = result.request_spec
    names = {spec.name, spec.queue.name, spec.function.name, spec.table.name}
    assert len(names) == 4
    assert spec.name == "order-worker"
    assert spec.queue.name == "order-worker-queue"
    assert spec.function.name == "order-worker-function"
    assert spec.table.name == "order-worker-table"


def test_resolved_s3_spec_uses_normalized_logical_name_hint():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.OBJECT_STORAGE}),
        logical_name_hint="Uploaded Documents",
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ResolvedArchitecture)
    spec: S3ResourceSpec = result.request_spec
    assert spec.name == "uploaded-documents"


def test_clarification_request_field_and_allowed_values_are_exact_for_workload_type():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.UNSPECIFIED,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset(),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ClarificationRequired)
    assert result.request.field == "workload_type"
    assert result.request.allowed_values == ("api", "worker", "storage")


def test_clarification_request_field_and_allowed_values_are_exact_for_interaction_pattern():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.API,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.HTTP_ENDPOINT}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, ClarificationRequired)
    assert result.request.field == "interaction_pattern"
    assert result.request.allowed_values == ("synchronous", "asynchronous")


def test_unsupported_detail_never_leaks_raw_exception_text():
    intent = ArchitectureIntent(
        workload_type=WorkloadType.STORAGE,
        interaction_pattern=InteractionPattern.UNSPECIFIED,
        capabilities=frozenset({Capability.PERSISTENCE}),
    )
    result = _resolver().resolve(intent=intent, request_id=_REQUEST_ID)
    assert isinstance(result, UnsupportedArchitecture)
    for forbidden in ("Traceback", "Error", "Exception", "  File \""):
        assert forbidden not in result.detail
