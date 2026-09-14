"""Unit tests for the shared ResourceType classification (Phase 2)."""

from __future__ import annotations

from iac_agent.domain.resource import ResourceType


def test_resource_type_has_exactly_sqs_s3_dynamodb_and_lambda():
    assert {member.value for member in ResourceType} == {"sqs", "s3", "dynamodb", "lambda"}


def test_resource_type_values_are_stable_identifiers():
    assert ResourceType.SQS.value == "sqs"
    assert ResourceType.S3.value == "s3"
    assert ResourceType.DYNAMODB.value == "dynamodb"
    assert ResourceType.LAMBDA.value == "lambda"
