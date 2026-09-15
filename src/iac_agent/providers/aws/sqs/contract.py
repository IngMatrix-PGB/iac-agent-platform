"""Strongly typed, deterministic SQS resource contract.

This module is the canonical structured representation of "what queue
the user wants." It is pure domain logic: no network calls, no AWS SDK,
no filesystem access, no environment variables, and no dependency on
Terraform or an LLM. Every invariant here is enforced by Pydantic at
construction time, so any later layer (Terraform rendering, security
policy, evaluation) can trust an ``SQSResourceSpec`` instance without
re-validating it.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from iac_agent.providers.aws.kms import validate_kms_key_id

# -- Queue name -----------------------------------------------------------

_MAX_NAME_LENGTH = 80
_FIFO_SUFFIX = ".fifo"
_NAME_BODY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")

# -- Numeric constraints (AWS SQS limits) ----------------------------------

_VISIBILITY_TIMEOUT_MIN = 0
_VISIBILITY_TIMEOUT_MAX = 43200
_RETENTION_MIN = 60
_RETENTION_MAX = 1209600
_DELAY_MIN = 0
_DELAY_MAX = 900
_MAX_RECEIVE_COUNT_MIN = 1
_MAX_RECEIVE_COUNT_MAX = 1000


def _validate_queue_name(value: str) -> str:
    if not value:
        raise ValueError("name must not be empty")
    if len(value) > _MAX_NAME_LENGTH:
        raise ValueError(f"name must be at most {_MAX_NAME_LENGTH} characters, got {len(value)}")

    body = value[: -len(_FIFO_SUFFIX)] if value.endswith(_FIFO_SUFFIX) else value
    if not body or not _NAME_BODY_PATTERN.match(body):
        raise ValueError(
            "name must contain only alphanumeric characters, hyphens, and underscores "
            "(a literal '.fifo' suffix is the only allowed exception)"
        )
    return value


# -- Derived DLQ name -------------------------------------------------------
# The trusted Terraform module (terraform/modules/sqs/main.tf) derives the
# DLQ's physical name from the primary queue name rather than accepting it
# as a separate input:
#
#     name = var.fifo
#       ? "${trimsuffix(var.name, ".fifo")}-dlq.fifo"
#       : "${var.name}-dlq"
#
# A primary name that is individually valid (<= 80 characters) can still
# produce a derived DLQ name that exceeds AWS's 80-character SQS queue-name
# limit. `derive_dlq_name` is the single canonical Python mirror of that
# exact Terraform expression — every place in this codebase (contract
# validation, tests, the cross-layer proof against a real Terraform plan)
# computes the expected derived name by calling this function, never by
# rebuilding the string independently.


def derive_dlq_name(name: str, fifo: bool) -> str:
    """Mirror the trusted Terraform module's DLQ-name derivation exactly.

    Pure and deterministic: no network access, no filesystem access, and
    the primary `name` is never mutated — this only computes what the
    *derived* DLQ name would be.
    """
    if fifo:
        base = name[: -len(_FIFO_SUFFIX)] if name.endswith(_FIFO_SUFFIX) else name
        return f"{base}-dlq.fifo"
    return f"{name}-dlq"


class EncryptionSpec(BaseModel):
    """Server-side encryption configuration for the queue.

    Phase 1 hard invariant: there is no valid ``EncryptionSpec`` with
    ``enabled=False`` — an unencrypted queue cannot be represented by
    this contract at all, by construction.
    """

    enabled: bool = True
    kms_key_id: str | None = None

    @field_validator("enabled")
    @classmethod
    def _enabled_must_be_true(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "encryption.enabled cannot be False — Phase 1 does not support an unencrypted queue"
            )
        return value

    @field_validator("kms_key_id")
    @classmethod
    def _validate_kms_key_id(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return validate_kms_key_id(value)


class DlqSpec(BaseModel):
    """Dead-letter-queue / redrive configuration.

    Unlike encryption, disabling the DLQ is a valid (if not recommended)
    choice at the contract layer — it is surfaced as a security finding
    by a later policy layer, not rejected here.
    """

    enabled: bool = True
    max_receive_count: int | None = 5

    @model_validator(mode="after")
    def _validate_consistency(self) -> DlqSpec:
        if self.enabled:
            if self.max_receive_count is None:
                raise ValueError("dlq.max_receive_count is required when dlq.enabled is True")
            if not (_MAX_RECEIVE_COUNT_MIN <= self.max_receive_count <= _MAX_RECEIVE_COUNT_MAX):
                raise ValueError(
                    "dlq.max_receive_count must be between "
                    f"{_MAX_RECEIVE_COUNT_MIN} and {_MAX_RECEIVE_COUNT_MAX}, "
                    f"got {self.max_receive_count}"
                )
        elif self.max_receive_count is not None:
            raise ValueError("dlq.max_receive_count must be None when dlq.enabled is False")
        return self


class SQSResourceSpec(BaseModel):
    """Canonical, validated representation of a requested SQS queue.

    An instance of this model is the deterministic contract boundary
    between AI-driven intent extraction and everything downstream
    (Terraform generation, execution, security policy). If it
    constructs successfully, every Phase 1 invariant already holds.
    """

    resource_type: Literal["sqs_queue"] = "sqs_queue"
    name: str
    environment: str | None = None
    fifo: bool = False
    visibility_timeout_seconds: int = Field(
        default=30, ge=_VISIBILITY_TIMEOUT_MIN, le=_VISIBILITY_TIMEOUT_MAX
    )
    message_retention_seconds: int = Field(default=345600, ge=_RETENTION_MIN, le=_RETENTION_MAX)
    delay_seconds: int = Field(default=0, ge=_DELAY_MIN, le=_DELAY_MAX)
    encryption: EncryptionSpec = Field(default_factory=EncryptionSpec)
    dlq: DlqSpec = Field(default_factory=DlqSpec)
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_queue_name(value)

    @model_validator(mode="after")
    def _validate_fifo_naming_consistency(self) -> SQSResourceSpec:
        ends_with_fifo = self.name.endswith(_FIFO_SUFFIX)
        if self.fifo and not ends_with_fifo:
            raise ValueError("fifo=True requires name to end with '.fifo'")
        if not self.fifo and ends_with_fifo:
            raise ValueError("fifo=False requires name to NOT end with '.fifo'")
        return self

    @model_validator(mode="after")
    def _validate_derived_dlq_name_length(self) -> SQSResourceSpec:
        # Only meaningful when a DLQ will actually be created — a primary
        # name that is valid up to the normal 80-character limit must
        # remain valid when no DLQ exists to derive a name for.
        if not self.dlq.enabled:
            return self

        derived_name = derive_dlq_name(self.name, self.fifo)
        if len(derived_name) > _MAX_NAME_LENGTH:
            raise ValueError(
                f"derived DLQ queue name {derived_name!r} is {len(derived_name)} characters, "
                f"exceeding the SQS {_MAX_NAME_LENGTH}-character limit — shorten name"
            )
        return self
