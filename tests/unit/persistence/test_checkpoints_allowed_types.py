"""Isolated serializer round-trip proof for the durable checkpoint
allowlist (Batch 26).

`_ALLOWED_WORKFLOW_TYPES` is a critical dispatch boundary: an omitted
composition spec type does not crash at submit time — it silently
breaks durable resume for that composition specifically, the first
time a real checkpoint save/load cycle is attempted. This file proves
each composition spec survives the real `JsonPlusSerializer` in
isolation, fast and without a full graph/SQLite round trip (that full,
fresh-process proof is
`tests/integration/test_api_lambda_dynamodb_workflow_persistence.py`,
Gate B, Task 18 — this file is the narrow Gate-A-safe version).
"""

from __future__ import annotations

from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec, HttpMethod, RouteSpec
from iac_agent.compositions.api_lambda_dynamodb.contract import ApiLambdaDynamoDbSpec
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.persistence.checkpoints import _build_serializer
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)
from iac_agent.providers.aws.ecr.contract import EcrResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec


def _round_trip(value):
    serializer = _build_serializer()
    type_name, serialized = serializer.dumps_typed(value)
    return serializer.loads_typed((type_name, serialized))


def test_api_lambda_dynamodb_spec_survives_serialization_round_trip():
    spec = ApiLambdaDynamoDbSpec(
        name="orders-api-worker",
        api=ApiGatewayResourceSpec(name="orders-api"),
        function=LambdaResourceSpec(name="orders-handler", handler="app.handler"),
        route=RouteSpec(method=HttpMethod.POST, path="/orders"),
        table=DynamoDBResourceSpec(
            name="orders-table",
            partition_key=DynamoDBKeySpec(name="id", type=DynamoDBKeyType.STRING),
        ),
    )

    result = _round_trip(spec)

    # `type(...) is`, not `isinstance` — rules out silent widening to a
    # base type, a subclass, or a permissive dict fallback.
    assert type(result) is ApiLambdaDynamoDbSpec
    assert result == spec


def test_api_lambda_dynamodb_spec_never_degrades_into_api_lambda_spec():
    spec = ApiLambdaDynamoDbSpec(
        name="orders-api-worker",
        api=ApiGatewayResourceSpec(name="orders-api"),
        function=LambdaResourceSpec(name="orders-handler", handler="app.handler"),
        route=RouteSpec(method=HttpMethod.POST, path="/orders"),
        table=DynamoDBResourceSpec(
            name="orders-table",
            partition_key=DynamoDBKeySpec(name="id", type=DynamoDBKeyType.STRING),
        ),
    )

    result = _round_trip(spec)

    assert type(result) is not ApiLambdaSpec
    assert not isinstance(result, ApiLambdaSpec)
    assert not isinstance(result, dict)


def test_existing_composition_types_still_round_trip_unchanged():
    """Backward-compat proof: this task only adds an entry, never edits
    an existing one."""
    worker_spec = ServerlessWorkerSpec(
        name="orders-worker",
        queue=SQSResourceSpec(name="orders-queue"),
        function=LambdaResourceSpec(name="orders-processor", handler="app.handler"),
        table=DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
    )
    api_lambda_spec = ApiLambdaSpec(
        name="orders-api",
        api=ApiGatewayResourceSpec(name="orders-api-gw"),
        function=LambdaResourceSpec(name="orders-fn", handler="app.handler"),
        route=RouteSpec(method=HttpMethod.GET, path="/orders"),
    )

    assert type(_round_trip(worker_spec)) is ServerlessWorkerSpec
    assert type(_round_trip(api_lambda_spec)) is ApiLambdaSpec


def test_ecr_spec_survives_serialization_round_trip_as_the_concrete_type():
    spec = EcrResourceSpec(name="team/service", tags={"owner": "platform"})

    result = _round_trip(spec)

    assert type(result) is EcrResourceSpec
    assert not isinstance(result, dict)
    assert result.image_tag_mutability is spec.image_tag_mutability
    assert result.scan_on_push is True
    assert result.encryption.enabled is True
    assert result == spec
