"""Domain model for multi-resource architecture classification (Batch 19).

`CompositionType` is deliberately **separate** from `ResourceType`
(`iac_agent.domain.resource`). `ResourceType` classifies a single AWS
resource a trusted module directly creates (SQS, S3, DynamoDB, Lambda);
`CompositionType` classifies a bounded, deterministic *relationship*
between several already-supported resource types. There is no
`ResourceType.SERVERLESS` and none is ever added here — a composition
is not itself a new kind of AWS resource, it is a fixed architecture
built out of existing ones. Keeping the two enums distinct is what lets
`iac_agent.providers.aws.resource.resource_type_of` keep meaning
exactly what it always has (classify one AWS resource spec) without
needing a case for something that isn't one.
"""

from __future__ import annotations

from enum import StrEnum


class CompositionType(StrEnum):
    """A bounded, deterministic multi-resource architecture this
    platform can generate. Batch 19 introduces exactly one member — a
    small, explicit enum, not an open-ended architecture/graph DSL."""

    SQS_LAMBDA_DYNAMODB = "sqs_lambda_dynamodb"
