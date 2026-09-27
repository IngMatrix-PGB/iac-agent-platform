"""Strongly typed, deterministic ECR repository contract (Batch 27).

Pure domain logic: no network calls, no AWS SDK, no filesystem access,
no environment variables, and no Terraform or LLM dependency. Every
invariant is enforced by Pydantic at construction time.

Repository-name rules follow AWS CreateRepository's published regex
and the 2–256 character length bound. The regex permits a leading
digit; AWS prose that says the name must start with a letter is not
what that regex enforces. A Gate B terraform plan records which one
the provider accepts.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_MIN_NAME_LENGTH = 2
_MAX_NAME_LENGTH = 256

# AWS CreateRepository pattern, anchored. Length is checked separately.
_NAME_PATTERN = re.compile(
    r"^[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*(\/[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*)*$"
)


def _validate_repository_name(value: str) -> str:
    if not (_MIN_NAME_LENGTH <= len(value) <= _MAX_NAME_LENGTH):
        raise ValueError(
            f"name must be between {_MIN_NAME_LENGTH} and {_MAX_NAME_LENGTH} characters, "
            f"got {len(value)}"
        )
    if not _NAME_PATTERN.match(value):
        raise ValueError(
            "name must match the ECR repository name pattern: lowercase letters, digits, "
            "and separators (., _, __, -+) inside slash-delimited segments"
        )
    return value


class EcrImageTagMutability(StrEnum):
    """Batch 27 supports the two mutability modes that do not need an
    exclusion-filter block. MUTABLE_WITH_EXCLUSION and
    IMMUTABLE_WITH_EXCLUSION are not members."""

    MUTABLE = "MUTABLE"
    IMMUTABLE = "IMMUTABLE"


class EcrEncryptionSpec(BaseModel):
    """Server-side encryption for the repository.

    There is no valid EcrEncryptionSpec with enabled=False. Batch 27
    supports only AWS-managed AES256. There is no kms_key_id field.
    """

    enabled: bool = True

    @field_validator("enabled")
    @classmethod
    def _enabled_must_be_true(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "encryption.enabled cannot be False — Batch 27 does not "
                "support an unencrypted repository"
            )
        return value


class EcrResourceSpec(BaseModel):
    """Canonical, validated representation of a requested ECR repository."""

    resource_type: Literal["ecr_repository"] = "ecr_repository"
    name: str
    environment: str | None = None
    image_tag_mutability: EcrImageTagMutability = EcrImageTagMutability.IMMUTABLE
    scan_on_push: bool = True
    encryption: EcrEncryptionSpec = Field(default_factory=EcrEncryptionSpec)
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        return _validate_repository_name(value)
