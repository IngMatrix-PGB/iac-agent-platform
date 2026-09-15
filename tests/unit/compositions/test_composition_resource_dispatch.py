"""Unit tests for the composition dispatch boundary (Batch 19).

Mirrors tests/unit/providers/aws/test_resource_dispatch.py exactly:
proves `composition_type_of` classifies the one currently supported
`CompositionSpec` correctly and fails closed for anything else.
"""

from __future__ import annotations

import pytest

from iac_agent.compositions.resource import composition_type_of
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.composition import CompositionType
from iac_agent.providers.aws.dynamodb.contract import DynamoDBKeySpec, DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec


def _serverless_worker_spec() -> ServerlessWorkerSpec:
    return ServerlessWorkerSpec(
        name="orders-worker",
        queue=SQSResourceSpec(name="orders-queue"),
        function=LambdaResourceSpec(name="orders-processor", handler="app.handler"),
        table=DynamoDBResourceSpec(
            name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type="S")
        ),
    )


def test_serverless_worker_spec_classified_as_sqs_lambda_dynamodb():
    assert composition_type_of(_serverless_worker_spec()) is CompositionType.SQS_LAMBDA_DYNAMODB


def test_unsupported_spec_type_raises_value_error():
    with pytest.raises(ValueError, match="unsupported composition spec type"):
        composition_type_of(object())  # type: ignore[arg-type]
