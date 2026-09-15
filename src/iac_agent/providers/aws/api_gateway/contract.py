"""Strongly typed, deterministic API Gateway (HTTP API) resource
contract (Phase 2, Batch 20).

Mirrors the same design as every other resource contract in this
project (`iac_agent.providers.aws.sqs.contract`, `.s3.contract`,
`.dynamodb.contract`, `.lambda_function.contract`): pure domain logic
(no network calls, no AWS SDK, no filesystem access, no environment
variables, no Terraform/LLM dependency).

Deliberately small: `ApiGatewayResourceSpec` describes only the API
itself (an Amazon API Gateway **HTTP API** — protocol type `HTTP`,
never `WEBSOCKET`, and never exposed as a configurable field at all).
Routes, integrations, and Lambda permissions are relationships owned by
a composition (`iac_agent.compositions.api_lambda`), never by this
contract — this mirrors exactly how `LambdaResourceSpec` never
describes an SQS event source mapping.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_MIN_NAME_LENGTH = 1
_MAX_NAME_LENGTH = 128
_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

_MAX_DESCRIPTION_LENGTH = 256


def _validate_api_name(value: str) -> str:
    if not (_MIN_NAME_LENGTH <= len(value) <= _MAX_NAME_LENGTH):
        raise ValueError(
            f"name must be between {_MIN_NAME_LENGTH} and {_MAX_NAME_LENGTH} characters, "
            f"got {len(value)}"
        )
    if not _NAME_PATTERN.match(value):
        raise ValueError("name must contain only letters, digits, underscores, and hyphens")
    return value


class ApiGatewayResourceSpec(BaseModel):
    """Canonical, validated representation of a requested Amazon API
    Gateway HTTP API — the API Gateway counterpart to
    `SQSResourceSpec`/`S3ResourceSpec`/`DynamoDBResourceSpec`/
    `LambdaResourceSpec`.

    Protocol type is always HTTP — there is no field through which a
    caller could request `WEBSOCKET`, and the trusted module
    (`terraform/modules/api_gateway`) hardcodes `protocol_type = "HTTP"`
    unconditionally.
    """

    resource_type: Literal["api_gateway"] = "api_gateway"
    name: str
    description: str | None = None
    environment: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_api_name(value)

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        if value is not None and len(value) > _MAX_DESCRIPTION_LENGTH:
            raise ValueError(
                f"description must be at most {_MAX_DESCRIPTION_LENGTH} characters, "
                f"got {len(value)}"
            )
        return value
