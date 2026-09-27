"""Strongly typed, deterministic API-Gateway-to-Lambda-to-DynamoDB
composition contract (Batch 26).

`ApiLambdaDynamoDbSpec` is the platform's third composition spec: a
synchronous REST API backed by one DynamoDB table (API Gateway HTTP API
-> Lambda -> DynamoDB). It owns one `ApiGatewayResourceSpec`, one
`LambdaResourceSpec`, one `RouteSpec` (reused verbatim from
`iac_agent.compositions.api_lambda.contract`, never duplicated — the
route/HTTP-method grammar is identical to composition #2's, and this is
the one place a composition imports from a sibling composition instead
of only from `providers.aws.*`), and one `DynamoDBResourceSpec`.

Deliberately **not** a subclass of `ApiLambdaSpec` and does not extend
it — this is a structurally distinct type by design (Batch 26 human
decision), so that no existing `isinstance(spec, ApiLambdaSpec)` or
`case ApiLambdaSpec():` dispatch site can ever silently classify an
`ApiLambdaDynamoDbSpec` request as the older, table-less composition.
See `tests/unit/compositions/api_lambda_dynamodb/test_api_lambda_dynamodb_contract.py`
for the two tests that prove this mechanically, not just by
inspection.

Pure domain logic: no network calls, no AWS SDK, no filesystem access,
no environment variables, no Terraform/LLM dependency. Every cross-
resource invariant below is enforced by Pydantic at construction time,
exactly like every other contract in this project.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from iac_agent.compositions.api_lambda.contract import HttpMethod, RouteSpec
from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.dynamodb.contract import DynamoDBResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec

__all__ = ["ApiLambdaDynamoDbSpec", "HttpMethod", "RouteSpec"]

# -- Composition name ---------------------------------------------------

_MIN_NAME_LENGTH = 1
_MAX_NAME_LENGTH = 64
_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_composition_name(value: str) -> str:
    if not (_MIN_NAME_LENGTH <= len(value) <= _MAX_NAME_LENGTH):
        raise ValueError(
            f"name must be between {_MIN_NAME_LENGTH} and {_MAX_NAME_LENGTH} characters, "
            f"got {len(value)}"
        )
    if not _NAME_PATTERN.match(value):
        raise ValueError("name must contain only letters, digits, underscores, and hyphens")
    return value


class ApiLambdaDynamoDbSpec(BaseModel):
    """Canonical, validated representation of a requested API-Gateway-
    HTTP-API -> Lambda -> DynamoDB composition architecture.

    `api`, `function`, `route`, and `table` are exactly
    `ApiGatewayResourceSpec`, `LambdaResourceSpec`, `RouteSpec`, and
    `DynamoDBResourceSpec` — Pydantic's own field typing is what
    enforces "the api is really API Gateway, the function is really
    Lambda, the table is really DynamoDB" here; there is no separate
    `isinstance` check needed or added, and no way to construct this
    spec with a wrong-shaped nested resource at all.
    """

    composition_type: Literal["api_gateway_lambda_dynamodb"] = "api_gateway_lambda_dynamodb"
    name: str
    environment: str | None = None
    api: ApiGatewayResourceSpec
    function: LambdaResourceSpec
    route: RouteSpec
    table: DynamoDBResourceSpec
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_composition_name(value)

    @model_validator(mode="after")
    def _validate_identifiers_are_pairwise_distinct(self) -> ApiLambdaDynamoDbSpec:
        # "No shared-name guessing", mirroring ServerlessWorkerSpec's
        # 3-way check exactly: this platform never silently renames a
        # user-supplied resource to force uniqueness.
        names = (self.api.name, self.function.name, self.table.name)
        if len(set(names)) != len(names):
            raise ValueError(
                f"api.name, function.name, and table.name must all be distinct (got {names!r})"
            )
        return self

    @model_validator(mode="after")
    def _validate_environment_consistency(self) -> ApiLambdaDynamoDbSpec:
        if self.environment is None:
            return self
        for label, sub_environment in (
            ("api", self.api.environment),
            ("function", self.function.environment),
            ("table", self.table.environment),
        ):
            if sub_environment is not None and sub_environment != self.environment:
                raise ValueError(
                    f"{label}.environment ({sub_environment!r}) does not match this "
                    f"composition's environment ({self.environment!r})"
                )
        return self
