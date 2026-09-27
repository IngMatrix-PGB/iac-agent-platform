"""Unit tests for the ECR repository contract (Batch 27).

Covers EcrResourceSpec, EcrEncryptionSpec, and EcrImageTagMutability.
No network, filesystem, LLM, or Terraform dependency is exercised.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from iac_agent.providers.aws.ecr.contract import (
    EcrEncryptionSpec,
    EcrImageTagMutability,
    EcrResourceSpec,
)


def test_repository_with_secure_defaults():
    spec = EcrResourceSpec(name="orders")

    assert spec.resource_type == "ecr_repository"
    assert spec.name == "orders"
    assert spec.environment is None
    assert spec.image_tag_mutability is EcrImageTagMutability.IMMUTABLE
    assert spec.scan_on_push is True
    assert spec.encryption.enabled is True
    assert spec.tags == {}


@pytest.mark.parametrize(
    "name",
    ["team/service", "a--b", "a__b", "a.b", "1abc", "ab"],
)
def test_ecr_name_patterns_accepted_by_the_aws_regex(name: str):
    spec = EcrResourceSpec(name=name)
    assert spec.name == name


def test_name_at_maximum_length_is_valid():
    name = "a" * 256
    assert EcrResourceSpec(name=name).name == name


@pytest.mark.parametrize(
    "name",
    ["", "A", "Orders", "/team", "team/", "a..b", "a" * 257, "a", "order events"],
)
def test_invalid_ecr_names_are_rejected(name: str):
    with pytest.raises(ValidationError):
        EcrResourceSpec(name=name)


def test_encryption_disabled_is_rejected():
    with pytest.raises(ValidationError, match="encryption.enabled cannot be False"):
        EcrEncryptionSpec(enabled=False)


def test_encryption_disabled_is_rejected_when_nested_in_spec():
    with pytest.raises(ValidationError, match="encryption.enabled cannot be False"):
        EcrResourceSpec(name="orders", encryption=EcrEncryptionSpec(enabled=False))


def test_encryption_spec_has_no_kms_key_id_field():
    assert "kms_key_id" not in EcrEncryptionSpec.model_fields


def test_repository_spec_has_no_force_delete_or_lifecycle_field():
    assert "force_delete" not in EcrResourceSpec.model_fields
    assert "lifecycle" not in EcrResourceSpec.model_fields
    assert "lifecycle_policy" not in EcrResourceSpec.model_fields
