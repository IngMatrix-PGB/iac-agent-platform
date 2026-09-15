"""Strongly typed, deterministic API-Gateway-to-Lambda composition
contract (Phase 2, Batch 20).

`ApiLambdaSpec` is the platform's second composition spec, mirroring
`iac_agent.compositions.serverless_worker.contract.ServerlessWorkerSpec`
exactly in discipline: it owns one `ApiGatewayResourceSpec`, one
`LambdaResourceSpec`, and the one relationship between them (an
explicit HTTP method + path route, bound via a Lambda proxy
integration — see `iac_agent.compositions.api_lambda.renderer`). It is
not a generic node/edge graph, not a YAML DAG schema, and not a
`resources: list[dict]` — the architecture itself (API Gateway HTTP API
-> Lambda) is fixed and named
(`CompositionType.API_GATEWAY_LAMBDA`, see
`iac_agent.domain.composition`), and this contract's two sub-specs are
exactly the existing `ApiGatewayResourceSpec`/`LambdaResourceSpec`
reused verbatim — their field definitions are never duplicated here.

Pure domain logic: no network calls, no AWS SDK, no filesystem access,
no environment variables, no Terraform/LLM dependency. Every cross-
resource invariant below is enforced by Pydantic at construction time,
exactly like every other contract in this project.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from iac_agent.providers.aws.api_gateway.contract import ApiGatewayResourceSpec
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec

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


# -- Route ----------------------------------------------------------------


class HttpMethod(StrEnum):
    """A deliberately bounded set of HTTP methods — Batch 20 supports
    exactly these five, never an arbitrary method string and never the
    API Gateway v2 `ANY` catch-all (no demonstrated need for it yet)."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


_MAX_PATH_LENGTH = 512

#: One path segment: either a plain literal identifier, or a
#: `{param}`-style path-parameter placeholder — deliberately not the
#: full API Gateway route-path grammar (no greedy `{proxy+}` support,
#: no multi-parameter segments), since nothing in this batch's
#: composition needs more than this.
_PATH_SEGMENT_PATTERN = re.compile(r"^([a-zA-Z0-9_\-.]+|\{[a-zA-Z_][a-zA-Z0-9_]*\})$")


def _validate_route_path(value: str) -> str:
    if not value:
        raise ValueError("path must not be empty")
    if len(value) > _MAX_PATH_LENGTH:
        raise ValueError(f"path must be at most {_MAX_PATH_LENGTH} characters, got {len(value)}")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError("path must not contain control characters")
    if value != value.strip() or any(ch.isspace() for ch in value):
        raise ValueError("path must not contain whitespace")
    if not value.startswith("/"):
        raise ValueError("path must start with '/'")
    if value == "/":
        return value
    if value.endswith("/"):
        raise ValueError("path must not end with a trailing '/' (except the root path '/')")
    segments = value[1:].split("/")
    for segment in segments:
        if not segment or not _PATH_SEGMENT_PATTERN.match(segment):
            raise ValueError(f"invalid path segment: {segment!r}")
    return value


class RouteSpec(BaseModel):
    """One explicit HTTP method + path pair.

    Batch 20 never creates an API Gateway v2 `$default` catch-all
    route implicitly — a route is only ever created because a caller
    supplied both a method and a path explicitly here.
    """

    method: HttpMethod
    path: str

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value: str) -> str:
        return _validate_route_path(value)

    @property
    def route_key(self) -> str:
        """The exact `route_key` value the trusted composition renders
        onto `aws_apigatewayv2_route` — `"<METHOD> <path>"`, matching
        API Gateway v2's own route-key grammar precisely (a single
        space between method and path, never `$default`)."""
        return f"{self.method.value} {self.path}"


class ApiLambdaSpec(BaseModel):
    """Canonical, validated representation of a requested API-Gateway-
    HTTP-API-to-Lambda composition architecture.

    `api` and `function` are exactly `ApiGatewayResourceSpec` and
    `LambdaResourceSpec` — Pydantic's own field typing is what enforces
    "the api is really API Gateway, the function is really Lambda"
    here; there is no separate `isinstance` check needed or added.
    """

    composition_type: Literal["api_gateway_lambda"] = "api_gateway_lambda"
    name: str
    environment: str | None = None
    api: ApiGatewayResourceSpec
    function: LambdaResourceSpec
    route: RouteSpec
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_composition_name(value)

    @model_validator(mode="after")
    def _validate_identifiers_are_pairwise_distinct(self) -> ApiLambdaSpec:
        # "No shared-name guessing", mirroring ServerlessWorkerSpec
        # exactly: this platform never silently renames a user-supplied
        # resource to force uniqueness.
        if self.api.name == self.function.name:
            raise ValueError(
                f"api.name and function.name must be distinct (both were {self.api.name!r})"
            )
        return self

    @model_validator(mode="after")
    def _validate_environment_consistency(self) -> ApiLambdaSpec:
        if self.environment is None:
            return self
        for label, sub_environment in (
            ("api", self.api.environment),
            ("function", self.function.environment),
        ):
            if sub_environment is not None and sub_environment != self.environment:
                raise ValueError(
                    f"{label}.environment ({sub_environment!r}) does not match this "
                    f"composition's environment ({self.environment!r})"
                )
        return self
