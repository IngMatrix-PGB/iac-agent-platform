"""Strongly typed, deterministic Lambda resource contract (Phase 2,
Batch 18).

Mirrors the same design as `iac_agent.providers.aws.sqs.contract` /
`s3.contract` / `dynamodb.contract`: pure domain logic (no network
calls, no AWS SDK, no filesystem access, no environment variables, no
Terraform/LLM dependency), every invariant enforced by Pydantic at
construction time.

Named `lambda_function` rather than `lambda` because `lambda` is a
Python reserved keyword — this mirrors the trusted Terraform module's
own `aws_lambda_function` resource name.

This module models **infrastructure configuration only** — never
arbitrary developer source code. There is deliberately no field for a
deployment package path, S3 code location, or container image: the
trusted `terraform/modules/lambda` module always uses its own
checked-in fixture package (see that module's `main.tf`), independent
of anything in this contract. `handler` is metadata describing what a
real deployment's entry point would be, not a filesystem reference
this project ever reads or executes.

Numeric ranges and enumerated value sets (runtime identifiers, memory,
timeout, tracing modes, CloudWatch Logs retention values) were verified
against current AWS documentation before implementation — see
docs/resources/lambda.md for the exact sources and values.

Batch 18 deliberately keeps this contract small: no VPC configuration,
no Lambda Layers, no dead-letter queue, no Secrets Manager/SSM
integration, no event source mappings, and no permissions for any
other AWS resource type this platform supports (SQS/S3/DynamoDB) — see
docs/resources/lambda.md for the full list of Phase 2 non-goals.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# -- Function name --------------------------------------------------------

_MIN_NAME_LENGTH = 1
_MAX_NAME_LENGTH = 64

# Verified against the AWS Lambda CreateFunction API's own
# function-name-only pattern: letters, digits, underscore, hyphen.
_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _validate_function_name(value: str) -> str:
    if not (_MIN_NAME_LENGTH <= len(value) <= _MAX_NAME_LENGTH):
        raise ValueError(
            f"name must be between {_MIN_NAME_LENGTH} and {_MAX_NAME_LENGTH} characters, "
            f"got {len(value)}"
        )
    if not _NAME_PATTERN.match(value):
        raise ValueError("name must contain only letters, digits, underscores, and hyphens")
    return value


# -- Handler ----------------------------------------------------------------

# `module.function` (or a dotted package path ending in a function
# name) — plain identifiers separated by dots only. Deliberately
# rejects empty strings, whitespace, path traversal ("..", "/"), and
# shell-like syntax (";", "|", "&", "$", quotes, backticks) by
# construction, since none of those characters are in the allowed set.
# Never imported or executed — this is a syntax check only.
_HANDLER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")


def _validate_handler(value: str) -> str:
    if not _HANDLER_PATTERN.match(value):
        raise ValueError(
            "handler must be in the form 'module.function' (dot-separated identifiers only, "
            "no whitespace, no path separators)"
        )
    return value


# -- Environment variables ---------------------------------------------------

# Verified against current AWS Lambda documentation: keys start with a
# letter, are at least 2 characters, and contain only letters, digits,
# and underscores.
_ENV_VAR_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]+$")

#: Reserved by the Lambda runtime itself — verified against current AWS
#: documentation. A caller-supplied environment variable using one of
#: these names would silently never take effect at runtime, so it is
#: rejected here instead.
_RESERVED_ENV_VAR_NAMES = frozenset(
    {
        "_HANDLER",
        "_X_AMZN_TRACE_ID",
        "AWS_DEFAULT_REGION",
        "AWS_REGION",
        "AWS_EXECUTION_ENV",
        "AWS_LAMBDA_FUNCTION_NAME",
        "AWS_LAMBDA_FUNCTION_MEMORY_SIZE",
        "AWS_LAMBDA_FUNCTION_VERSION",
        "AWS_LAMBDA_INITIALIZATION_TYPE",
        "AWS_LAMBDA_LOG_GROUP_NAME",
        "AWS_LAMBDA_LOG_STREAM_NAME",
        "AWS_ACCESS_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_LAMBDA_RUNTIME_API",
        "LAMBDA_TASK_ROOT",
        "LAMBDA_RUNTIME_DIR",
        "AWS_LAMBDA_MAX_CONCURRENCY",
        "AWS_LAMBDA_METADATA_API",
        "AWS_LAMBDA_METADATA_TOKEN",
    }
)

#: AWS's own aggregate limit for all environment variables on one
#: function, verified against current documentation.
_ENV_VARS_MAX_TOTAL_BYTES = 4096


def _validate_environment_variables(value: dict[str, str]) -> dict[str, str]:
    for name in value:
        if not _ENV_VAR_NAME_PATTERN.match(name):
            raise ValueError(
                f"environment variable name {name!r} must start with a letter, be at "
                "least 2 characters, and contain only letters, digits, and underscores"
            )
        if name in _RESERVED_ENV_VAR_NAMES:
            raise ValueError(
                f"environment variable name {name!r} is reserved by the Lambda runtime "
                "and cannot be set"
            )
    total_bytes = sum(len(name) + len(val) for name, val in value.items())
    if total_bytes > _ENV_VARS_MAX_TOTAL_BYTES:
        raise ValueError(
            f"environment variables total {total_bytes} bytes, which exceeds the "
            f"{_ENV_VARS_MAX_TOTAL_BYTES}-byte aggregate limit"
        )
    return value


# -- Enums --------------------------------------------------------------


class LambdaRuntime(StrEnum):
    """Batch 18 supports exactly one runtime. Values are Lambda's own
    runtime identifiers (see AWS docs), reused as-is rather than
    invented. Node/Java/.NET are deliberately not added merely for
    breadth — see docs/resources/lambda.md."""

    PYTHON3_12 = "python3.12"


class LambdaArchitecture(StrEnum):
    """Both values Lambda itself supports for every current runtime."""

    X86_64 = "x86_64"
    ARM64 = "arm64"


class LambdaTracingMode(StrEnum):
    """Lambda's own AWS X-Ray `TracingConfig.Mode` values, reused as-is
    (exact casing verified against current AWS API documentation)."""

    ACTIVE = "Active"
    PASS_THROUGH = "PassThrough"


# -- Memory / timeout / concurrency / retention ------------------------------

# Verified against the current AWS Lambda quotas documentation.
_MEMORY_MIN_MB = 128
_MEMORY_MAX_MB = 10_240
_TIMEOUT_MIN_SECONDS = 1
_TIMEOUT_MAX_SECONDS = 900

#: Verified against the current CloudWatch Logs PutRetentionPolicy API
#: documentation — the *complete* set of values CloudWatch Logs itself
#: accepts for `retentionInDays`. Batch 18 requires a positive, bounded
#: value (no indefinite-retention option) — see docs/resources/lambda.md.
_VALID_LOG_RETENTION_DAYS = frozenset(
    {
        1,
        3,
        5,
        7,
        14,
        30,
        60,
        90,
        120,
        150,
        180,
        365,
        400,
        545,
        731,
        1096,
        1827,
        2192,
        2557,
        2922,
        3288,
        3653,
    }
)


class LambdaResourceSpec(BaseModel):
    """Canonical, validated representation of a requested Lambda
    function (with its execution role and log group as an internal
    implementation detail) — the Lambda counterpart to
    `SQSResourceSpec`/`S3ResourceSpec`/`DynamoDBResourceSpec`.
    """

    resource_type: Literal["lambda_function"] = "lambda_function"
    name: str
    environment: str | None = None
    runtime: LambdaRuntime = LambdaRuntime.PYTHON3_12
    handler: str
    architecture: LambdaArchitecture = LambdaArchitecture.ARM64
    memory_size_mb: int = 256
    timeout_seconds: int = 30
    reserved_concurrency: int | None = None
    tracing_mode: LambdaTracingMode = LambdaTracingMode.ACTIVE
    log_retention_days: int = 365
    environment_variables: dict[str, str] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_function_name(value)

    @field_validator("handler")
    @classmethod
    def _validate_handler_field(cls, value: str) -> str:
        return _validate_handler(value)

    @field_validator("memory_size_mb")
    @classmethod
    def _validate_memory(cls, value: int) -> int:
        if not (_MEMORY_MIN_MB <= value <= _MEMORY_MAX_MB):
            raise ValueError(
                f"memory_size_mb must be between {_MEMORY_MIN_MB} and {_MEMORY_MAX_MB}, got {value}"
            )
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _validate_timeout(cls, value: int) -> int:
        if not (_TIMEOUT_MIN_SECONDS <= value <= _TIMEOUT_MAX_SECONDS):
            raise ValueError(
                f"timeout_seconds must be between {_TIMEOUT_MIN_SECONDS} and "
                f"{_TIMEOUT_MAX_SECONDS}, got {value}"
            )
        return value

    @field_validator("reserved_concurrency")
    @classmethod
    def _validate_reserved_concurrency(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError(f"reserved_concurrency must be >= 0 when set, got {value}")
        return value

    @field_validator("log_retention_days")
    @classmethod
    def _validate_log_retention(cls, value: int) -> int:
        if value not in _VALID_LOG_RETENTION_DAYS:
            raise ValueError(
                f"log_retention_days must be one of {sorted(_VALID_LOG_RETENTION_DAYS)}, "
                f"got {value}"
            )
        return value

    @field_validator("environment_variables")
    @classmethod
    def _validate_environment_variables_field(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_environment_variables(value)
