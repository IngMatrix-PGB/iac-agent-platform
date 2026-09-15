"""The deterministic side of the probabilistic boundary (Batch 21).

This module owns the `ResolutionResult` discriminated union (Task 2)
and, once Task 4 lands, `ArchitectureResolver` itself — the pure,
side-effect-free function that maps a validated `ArchitectureIntent`
onto one of a closed set of existing `IacRequestSpec` targets. Nothing
in this module performs I/O, calls an LLM, or imports
`iac_agent.execution`/`iac_agent.security`/`iac_agent.git`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.intent.models import (
    ArchitectureIntent,
    Capability,
    InteractionPattern,
    WorkloadType,
)
from iac_agent.intent.naming import component_name, resolve_base_name
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.request import IacRequestSpec


class ClarificationReason(StrEnum):
    WORKLOAD_TYPE_REQUIRED = "workload_type_required"
    INTERACTION_PATTERN_REQUIRED = "interaction_pattern_required"


@dataclass(frozen=True)
class ClarificationRequest:
    """A fully typed, resolver-authored clarification ask. The
    interpreter/LLM never invents this question — see spec §8."""

    reason: ClarificationReason
    field: str
    allowed_values: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedArchitecture:
    """The architecture resolved unambiguously to an existing,
    already-validated `IacRequestSpec`. `matched_pattern` is
    observability only (e.g. `"api+synchronous+http_endpoint"`)."""

    request_spec: IacRequestSpec
    matched_pattern: str
    outcome: Literal["resolved"] = "resolved"


@dataclass(frozen=True)
class ClarificationRequired:
    """The intent is missing information in a decisive position. Never
    silently resolved — see spec §7.1's explicit `UNSPECIFIED` arms."""

    request: ClarificationRequest
    outcome: Literal["clarification_required"] = "clarification_required"


class UnsupportedReason(StrEnum):
    UNSUPPORTED_WORKLOAD = "unsupported_workload"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    UNSUPPORTED_COMBINATION = "unsupported_combination"


@dataclass(frozen=True)
class UnsupportedArchitecture:
    """A fully specified but unsupported architecture. `detail` is a
    short, resolver-authored string — never a raw exception message or
    stack trace (see spec §8)."""

    reason: UnsupportedReason
    detail: str
    outcome: Literal["unsupported"] = "unsupported"


ResolutionResult = ResolvedArchitecture | ClarificationRequired | UnsupportedArchitecture


# -- Resolver-owned structural defaults --------------------------------
#
# `ArchitectureIntent` deliberately carries no field for a Lambda
# handler, a DynamoDB partition key, or an API route's method/path —
# these are construction-time details of the target contract, not
# architecture semantics. Building a valid `IacRequestSpec` from a
# resolved intent requires the resolver to supply fixed, code-owned,
# deterministic values for exactly these three gaps instead — never
# LLM-sourced, mirroring the naming-fallback discipline in
# `iac_agent.intent.naming` precisely (a fixed, code-owned default,
# never a value the model chose). Human-approved for Batch 21.

#: Every resolver-constructed Lambda function uses this same fixed
#: handler entry point — the LLM must never generate, override, or
#: select it.
LAMBDA_DEFAULT_HANDLER = "app.handler"

#: Every resolver-constructed API-Gateway-to-Lambda composition uses
#: this same fixed route. `RouteSpec.path`'s existing validator
#: (`iac_agent.compositions.api_lambda.contract`, Batch 20, unmodified
#: this batch) does not support a greedy `{proxy+}` segment, so a
#: concrete literal path is used instead.
API_LAMBDA_DEFAULT_ROUTE = RouteSpec(method=HttpMethod.POST, path="/invoke")

#: Every resolver-constructed DynamoDB table in a serverless-worker
#: composition uses this same fixed partition key.
WORKER_DDB_DEFAULT_PARTITION_KEY = DynamoDBKeySpec(name="id", type=DynamoDBKeyType.STRING)


def _workload_type_clarification() -> ClarificationRequest:
    return ClarificationRequest(
        reason=ClarificationReason.WORKLOAD_TYPE_REQUIRED,
        field="workload_type",
        allowed_values=("api", "worker", "storage"),
    )


def _interaction_pattern_clarification() -> ClarificationRequest:
    return ClarificationRequest(
        reason=ClarificationReason.INTERACTION_PATTERN_REQUIRED,
        field="interaction_pattern",
        allowed_values=("synchronous", "asynchronous"),
    )


def _classify_unsupported(intent: ArchitectureIntent) -> UnsupportedReason:
    if intent.workload_type == WorkloadType.STORAGE:
        return UnsupportedReason.UNSUPPORTED_CAPABILITY
    return UnsupportedReason.UNSUPPORTED_COMBINATION


def _build_api_lambda_spec(intent: ArchitectureIntent, *, request_id: str) -> ApiLambdaSpec:
    base = resolve_base_name(logical_name_hint=intent.logical_name_hint, request_id=request_id)
    return ApiLambdaSpec(
        name=base,
        api=ApiGatewayResourceSpec(name=component_name(base, "api")),
        function=LambdaResourceSpec(
            name=component_name(base, "function"), handler=LAMBDA_DEFAULT_HANDLER
        ),
        route=API_LAMBDA_DEFAULT_ROUTE,
    )


def _build_serverless_worker_spec(
    intent: ArchitectureIntent, *, request_id: str
) -> ServerlessWorkerSpec:
    base = resolve_base_name(logical_name_hint=intent.logical_name_hint, request_id=request_id)
    return ServerlessWorkerSpec(
        name=base,
        queue=SQSResourceSpec(name=component_name(base, "queue")),
        function=LambdaResourceSpec(
            name=component_name(base, "function"), handler=LAMBDA_DEFAULT_HANDLER
        ),
        table=DynamoDBResourceSpec(
            name=component_name(base, "table"), partition_key=WORKER_DDB_DEFAULT_PARTITION_KEY
        ),
    )


def _build_s3_spec(intent: ArchitectureIntent, *, request_id: str) -> S3ResourceSpec:
    base = resolve_base_name(logical_name_hint=intent.logical_name_hint, request_id=request_id)
    return S3ResourceSpec(name=base)


class ArchitectureResolver:
    """Pure, deterministic. No I/O, no LLM call, no network, no
    filesystem access — mirrors `resource_type_of`'s own purity exactly.

    The allowlist below is closed: an unlisted, fully-specified
    combination always falls through the `case _` arm to
    `UnsupportedArchitecture`, never to an approximation.
    """

    def resolve(self, *, intent: ArchitectureIntent, request_id: str) -> ResolutionResult:
        # `frozenset` contents cannot be destructured as a match-case
        # literal pattern (sets are unordered — Python's structural
        # pattern matching only unpacks sequences/mappings/classes), so
        # exact-capability-set membership is expressed as an explicit
        # guard (`if capabilities == frozenset({...})`) on each `case`
        # instead. The dispatch shape (closed cases, fail-closed
        # `case _` default) is otherwise the same idiom `resource_type_of`
        # uses.
        workload_type = intent.workload_type
        interaction_pattern = intent.interaction_pattern
        capabilities = intent.capabilities

        match workload_type:
            case WorkloadType.API if (
                interaction_pattern == InteractionPattern.SYNCHRONOUS
                and capabilities == frozenset({Capability.HTTP_ENDPOINT})
            ):
                return ResolvedArchitecture(
                    request_spec=_build_api_lambda_spec(intent, request_id=request_id),
                    matched_pattern="api+synchronous+http_endpoint",
                )
            case WorkloadType.WORKER if (
                interaction_pattern == InteractionPattern.ASYNCHRONOUS
                and capabilities == frozenset({Capability.QUEUE_PROCESSING, Capability.PERSISTENCE})
            ):
                return ResolvedArchitecture(
                    request_spec=_build_serverless_worker_spec(intent, request_id=request_id),
                    matched_pattern="worker+asynchronous+queue_processing+persistence",
                )
            case WorkloadType.STORAGE if capabilities == frozenset({Capability.OBJECT_STORAGE}):
                return ResolvedArchitecture(
                    request_spec=_build_s3_spec(intent, request_id=request_id),
                    matched_pattern="storage+object_storage",
                )
            case WorkloadType.UNSPECIFIED:
                return ClarificationRequired(request=_workload_type_clarification())
            case WorkloadType.API if (
                interaction_pattern == InteractionPattern.UNSPECIFIED
                and capabilities == frozenset({Capability.HTTP_ENDPOINT})
            ):
                return ClarificationRequired(request=_interaction_pattern_clarification())
            case WorkloadType.WORKER if (
                interaction_pattern == InteractionPattern.UNSPECIFIED
                and capabilities == frozenset({Capability.QUEUE_PROCESSING, Capability.PERSISTENCE})
            ):
                return ClarificationRequired(request=_interaction_pattern_clarification())
            case _:
                reason = _classify_unsupported(intent)
                return UnsupportedArchitecture(
                    reason=reason,
                    detail=(
                        f"workload_type={workload_type.value}, "
                        f"interaction_pattern={interaction_pattern.value} is not a "
                        "supported combination for the given capabilities"
                    ),
                )
