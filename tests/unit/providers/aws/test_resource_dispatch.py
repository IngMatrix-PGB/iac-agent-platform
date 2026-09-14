"""Unit tests for the shared AWS resource dispatch boundary (Phase 2)."""

from __future__ import annotations

import pytest

from iac_agent.domain.resource import ResourceType
from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)
from iac_agent.providers.aws.resource import resource_type_of
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec


def test_sqs_spec_classified_as_sqs():
    spec = SQSResourceSpec(name="order-events")
    assert resource_type_of(spec) is ResourceType.SQS


def test_s3_spec_classified_as_s3():
    spec = S3ResourceSpec(name="my-example-bucket")
    assert resource_type_of(spec) is ResourceType.S3


def test_dynamodb_spec_classified_as_dynamodb():
    spec = DynamoDBResourceSpec(
        name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING)
    )
    assert resource_type_of(spec) is ResourceType.DYNAMODB


def test_unsupported_spec_type_fails_closed():
    with pytest.raises(ValueError, match="unsupported resource spec type"):
        resource_type_of(object())  # type: ignore[arg-type]


def test_unsupported_spec_type_never_silently_defaults_to_sqs():
    """A `None` or arbitrary object must never be silently classified
    as SQS just because SQS was the first/default resource type."""
    with pytest.raises(ValueError):
        result = resource_type_of(None)  # type: ignore[arg-type]
        assert result is not ResourceType.SQS  # unreachable if raised, as expected
