"""Strongly typed, deterministic DynamoDB resource contract (Phase 2,
Batch 17).

Mirrors the same design as `iac_agent.providers.aws.sqs.contract` and
`iac_agent.providers.aws.s3.contract`: pure domain logic (no network
calls, no AWS SDK, no filesystem access, no environment variables, no
Terraform/LLM dependency), every invariant enforced by Pydantic at
construction time.

Table-name rules below were verified against the current AWS DynamoDB
"Naming rules" documentation before implementation, not assumed from
memory or an older ruleset: table names must be 3-255 characters,
UTF-8, case-sensitive, and contain only `a-z`, `A-Z`, `0-9`, `_`, `-`,
and `.`. Unlike S3, DynamoDB table names are scoped per AWS
account+region, not globally unique — there is no equivalent
"syntactically valid but unavailable" caveat to document here.

Batch 17 deliberately keeps this contract small: no provisioned
capacity, autoscaling, GSIs, LSIs, Streams, Global Tables, DAX, TTL,
table classes, import/export, or resource policies — see
docs/resources/dynamodb.md for the full list of Phase 2 non-goals.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# -- Table name ---------------------------------------------------------

_MIN_NAME_LENGTH = 3
_MAX_NAME_LENGTH = 255

# Verified current AWS DynamoDB naming rule: letters, digits,
# underscore, hyphen, and period — nothing else (no lowercase-only
# requirement, no adjacent-character restriction, unlike S3).
_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _validate_table_name(value: str) -> str:
    if not (_MIN_NAME_LENGTH <= len(value) <= _MAX_NAME_LENGTH):
        raise ValueError(
            f"name must be between {_MIN_NAME_LENGTH} and {_MAX_NAME_LENGTH} characters, "
            f"got {len(value)}"
        )
    if not _NAME_PATTERN.match(value):
        raise ValueError(
            "name must contain only letters, digits, underscores, hyphens, and periods"
        )
    return value


class DynamoDBKeyType(StrEnum):
    """The three DynamoDB key attribute types — deliberately not an
    arbitrary string. Values are DynamoDB's own data-type descriptors
    (see AWS docs), reused as-is rather than invented."""

    STRING = "S"
    NUMBER = "N"
    BINARY = "B"


class DynamoDBKeySpec(BaseModel):
    """One key attribute (partition or sort key): a name and a type.

    This is the *only* place a table's attribute definitions come
    from — the renderer/module never infer an additional attribute
    beyond the partition key and (if present) the sort key.
    """

    name: str
    type: DynamoDBKeyType

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not value:
            raise ValueError("key name must not be empty")
        return value


class DynamoDBBillingMode(StrEnum):
    """Batch 17 supports exactly one billing mode. `PROVISIONED` is
    deliberately not a member of this enum at all — exposing it would
    require read/write capacity controls this phase does not
    implement, rather than merely defaulting to a value nothing
    validates."""

    PAY_PER_REQUEST = "PAY_PER_REQUEST"


class DynamoDBEncryptionSpec(BaseModel):
    """Server-side encryption configuration for the table.

    Phase 2 hard invariant: there is no valid `DynamoDBEncryptionSpec`
    with `enabled=False` — an unencrypted table cannot be represented
    by this contract at all, by construction (mirrors SQS's
    `EncryptionSpec` and S3's `S3EncryptionSpec` exactly).

    Deliberately no `kms_key_id` field. Customer-managed KMS support
    was evaluated against `aws_dynamodb_table`'s real schema
    (`server_side_encryption.kms_key_arn`) and found not to fit the
    shared `iac_agent.providers.aws.kms.validate_kms_key_id` validator
    cleanly: DynamoDB's Terraform field requires a full KMS key or
    alias ARN and rejects the bare alias-name/bare-key-id forms that
    validator (and S3's/SQS's own `kms_key_id` fields) otherwise
    accept — confirmed empirically via a real `terraform plan`, which
    fails with "invalid ARN: arn: invalid prefix" for a bare alias
    name. Rather than bolt on a second, DynamoDB-only KMS validator for
    Batch 17, customer-managed KMS support for DynamoDB is deferred to
    a future phase (see docs/resources/dynamodb.md); this phase only
    supports AWS-owned-key encryption.
    """

    enabled: bool = True

    @field_validator("enabled")
    @classmethod
    def _enabled_must_be_true(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "encryption.enabled cannot be False — Phase 2 does not support an unencrypted table"
            )
        return value


class DynamoDBResourceSpec(BaseModel):
    """Canonical, validated representation of a requested DynamoDB table.

    An instance of this model is the deterministic contract boundary
    between AI-driven intent extraction and everything downstream
    (Terraform generation, execution, security policy) — the DynamoDB
    counterpart to `SQSResourceSpec`/`S3ResourceSpec`.
    """

    resource_type: Literal["dynamodb_table"] = "dynamodb_table"
    name: str
    environment: str | None = None
    partition_key: DynamoDBKeySpec
    sort_key: DynamoDBKeySpec | None = None
    billing_mode: DynamoDBBillingMode = DynamoDBBillingMode.PAY_PER_REQUEST
    point_in_time_recovery: bool = True
    deletion_protection: bool = True
    encryption: DynamoDBEncryptionSpec = Field(default_factory=DynamoDBEncryptionSpec)
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_table_name(value)

    @model_validator(mode="after")
    def _validate_key_names_differ(self) -> DynamoDBResourceSpec:
        if self.sort_key is not None and self.sort_key.name == self.partition_key.name:
            raise ValueError(
                "sort_key.name must differ from partition_key.name "
                f"(both were {self.partition_key.name!r})"
            )
        return self
