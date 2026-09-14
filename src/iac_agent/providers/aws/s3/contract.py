"""Strongly typed, deterministic S3 resource contract (Phase 2).

Mirrors the same design as `iac_agent.providers.aws.sqs.contract`: pure
domain logic (no network calls, no AWS SDK, no filesystem access, no
environment variables, no Terraform/LLM dependency), every invariant
enforced by Pydantic at construction time.

Bucket-name rules below were verified against the current AWS S3
"General purpose buckets naming rules" documentation before
implementation, not assumed from memory or an older tutorial. A
syntactically valid name here is NOT proof the name is globally
available — S3 bucket names are unique across all AWS accounts in a
partition, and this contract has no way to check that without a live
AWS API call, which Phase 2 deliberately never makes (see
docs/resources/s3.md).
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from iac_agent.providers.aws.kms import validate_kms_key_id

# -- Bucket name ------------------------------------------------------------

_MIN_NAME_LENGTH = 3
_MAX_NAME_LENGTH = 63

# Lowercase letters, digits, periods, and hyphens; must begin and end
# with a letter or digit.
_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$")

# "Formatted as an IP address" is a shape check (four dot-separated
# groups of digits) — AWS rejects this regardless of whether the
# octets are within 0-255, so this is deliberately not a strict IPv4
# validator.
_IPV4_SHAPED_PATTERN = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# Reserved prefixes/suffixes per the current AWS naming rules — every
# one of these is verified current, not carried over from an older
# ruleset (AWS has both added prefixes/suffixes over time, e.g. for
# directory buckets and S3 Tables, and previously allowed names this
# project must still reject).
_FORBIDDEN_PREFIXES = ("xn--", "sthree-", "amzn-s3-demo-")
_FORBIDDEN_SUFFIXES = ("-s3alias", "--ol-s3", ".mrap", "--x-s3", "--table-s3")


def _validate_bucket_name(value: str) -> str:
    if not (_MIN_NAME_LENGTH <= len(value) <= _MAX_NAME_LENGTH):
        raise ValueError(
            f"name must be between {_MIN_NAME_LENGTH} and {_MAX_NAME_LENGTH} characters, "
            f"got {len(value)}"
        )
    if not _NAME_PATTERN.match(value):
        raise ValueError(
            "name must contain only lowercase letters, digits, periods, and hyphens, "
            "and must begin and end with a letter or digit"
        )
    if ".." in value:
        raise ValueError("name must not contain two adjacent periods")
    if _IPV4_SHAPED_PATTERN.match(value):
        raise ValueError(f"name must not be formatted as an IP address: {value!r}")
    for prefix in _FORBIDDEN_PREFIXES:
        if value.startswith(prefix):
            raise ValueError(f"name must not start with the reserved prefix {prefix!r}")
    for suffix in _FORBIDDEN_SUFFIXES:
        if value.endswith(suffix):
            raise ValueError(f"name must not end with the reserved suffix {suffix!r}")
    return value


class S3EncryptionSpec(BaseModel):
    """Server-side encryption configuration for the bucket.

    Phase 2 hard invariant: there is no valid `S3EncryptionSpec` with
    `enabled=False` — an unencrypted bucket cannot be represented by
    this contract at all, by construction (mirrors SQS's
    `EncryptionSpec` exactly).
    """

    enabled: bool = True
    kms_key_id: str | None = None

    @field_validator("enabled")
    @classmethod
    def _enabled_must_be_true(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "encryption.enabled cannot be False — Phase 2 does not support an "
                "unencrypted bucket"
            )
        return value

    @field_validator("kms_key_id")
    @classmethod
    def _validate_kms_key_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_kms_key_id(value)


class S3ResourceSpec(BaseModel):
    """Canonical, validated representation of a requested S3 bucket.

    An instance of this model is the deterministic contract boundary
    between AI-driven intent extraction and everything downstream
    (Terraform generation, execution, security policy) — the S3
    counterpart to `iac_agent.providers.aws.sqs.contract.SQSResourceSpec`.
    """

    resource_type: Literal["s3_bucket"] = "s3_bucket"
    name: str
    environment: str | None = None
    versioning: bool = True
    encryption: S3EncryptionSpec = Field(default_factory=S3EncryptionSpec)
    block_public_access: bool = True
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_bucket_name(value)

    @field_validator("block_public_access")
    @classmethod
    def _block_public_access_must_be_true(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "block_public_access cannot be False — Phase 2 does not support a bucket "
                "with public access unblocked"
            )
        return value
