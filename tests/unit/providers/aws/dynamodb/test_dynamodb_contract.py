"""Unit tests for the DynamoDB resource contract (Phase 2, Batch 17).

Covers DynamoDBResourceSpec, DynamoDBKeySpec, DynamoDBEncryptionSpec:
valid construction, every required hard-failure rule, boundary values,
and canonical serialization. No network, filesystem, LLM, or Terraform
dependency is exercised anywhere in this module.
"""

import json

import pytest
from pydantic import ValidationError

from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBBillingMode,
    DynamoDBEncryptionSpec,
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)

# ---------------------------------------------------------------------------
# Valid cases
# ---------------------------------------------------------------------------


def test_table_with_all_defaults():
    spec = DynamoDBResourceSpec(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
    )

    assert spec.resource_type == "dynamodb_table"
    assert spec.name == "orders-table"
    assert spec.environment is None
    assert spec.sort_key is None
    assert spec.billing_mode is DynamoDBBillingMode.PAY_PER_REQUEST
    assert spec.point_in_time_recovery is True
    assert spec.deletion_protection is True
    assert spec.encryption.enabled is True
    assert spec.tags == {}


def test_table_with_environment_set():
    spec = DynamoDBResourceSpec(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        environment="staging",
    )
    assert spec.environment == "staging"


def test_table_with_custom_tags():
    spec = DynamoDBResourceSpec(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        tags={"Service": "orders", "Team": "data"},
    )
    assert spec.tags == {"Service": "orders", "Team": "data"}


@pytest.mark.parametrize(
    "key_type", [DynamoDBKeyType.STRING, DynamoDBKeyType.NUMBER, DynamoDBKeyType.BINARY]
)
def test_partition_key_accepts_every_valid_key_type(key_type):
    spec = DynamoDBResourceSpec(
        name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type=key_type)
    )
    assert spec.partition_key.type is key_type


def test_partition_and_sort_key():
    spec = DynamoDBResourceSpec(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        sort_key=DynamoDBKeySpec(name="sk", type=DynamoDBKeyType.NUMBER),
    )
    assert spec.sort_key.name == "sk"
    assert spec.sort_key.type is DynamoDBKeyType.NUMBER


def test_pitr_can_be_disabled():
    spec = DynamoDBResourceSpec(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        point_in_time_recovery=False,
    )
    assert spec.point_in_time_recovery is False


def test_deletion_protection_can_be_disabled():
    spec = DynamoDBResourceSpec(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        deletion_protection=False,
    )
    assert spec.deletion_protection is False


# ---------------------------------------------------------------------------
# Table name — valid boundary cases
# ---------------------------------------------------------------------------


def test_name_at_minimum_length_is_valid():
    spec = DynamoDBResourceSpec(
        name="abc", partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING)
    )
    assert spec.name == "abc"


def test_name_at_maximum_length_is_valid():
    name = "a" * 255
    spec = DynamoDBResourceSpec(
        name=name, partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING)
    )
    assert spec.name == name


def test_name_allows_mixed_case_digits_underscores_hyphens_and_periods():
    spec = DynamoDBResourceSpec(
        name="My_Orders-Table.v2",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
    )
    assert spec.name == "My_Orders-Table.v2"


# ---------------------------------------------------------------------------
# Table name — invalid cases
# ---------------------------------------------------------------------------


def test_name_too_short_is_rejected():
    with pytest.raises(ValidationError, match="between 3 and 255"):
        DynamoDBResourceSpec(
            name="ab", partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING)
        )


def test_name_too_long_is_rejected():
    with pytest.raises(ValidationError, match="between 3 and 255"):
        DynamoDBResourceSpec(
            name="a" * 256,
            partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        )


def test_name_with_space_is_rejected():
    with pytest.raises(ValidationError, match="only letters, digits"):
        DynamoDBResourceSpec(
            name="orders table",
            partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        )


def test_name_with_unsupported_character_is_rejected():
    with pytest.raises(ValidationError, match="only letters, digits"):
        DynamoDBResourceSpec(
            name="orders@table",
            partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        )


# ---------------------------------------------------------------------------
# Key validation
# ---------------------------------------------------------------------------


def test_partition_key_is_required():
    with pytest.raises(ValidationError, match="partition_key"):
        DynamoDBResourceSpec(name="orders-table")


def test_empty_key_name_is_rejected():
    with pytest.raises(ValidationError, match="must not be empty"):
        DynamoDBKeySpec(name="", type=DynamoDBKeyType.STRING)


def test_invalid_key_type_is_rejected():
    with pytest.raises(ValidationError):
        DynamoDBKeySpec(name="pk", type="STRING")  # not the "S" descriptor


def test_duplicate_partition_and_sort_key_names_are_rejected():
    with pytest.raises(ValidationError, match="must differ"):
        DynamoDBResourceSpec(
            name="orders-table",
            partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
            sort_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.NUMBER),
        )


# ---------------------------------------------------------------------------
# Billing mode
# ---------------------------------------------------------------------------


def test_billing_mode_rejects_provisioned():
    with pytest.raises(ValidationError):
        DynamoDBResourceSpec(
            name="orders-table",
            partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
            billing_mode="PROVISIONED",
        )


# ---------------------------------------------------------------------------
# Hard invariants
# ---------------------------------------------------------------------------


def test_encryption_disabled_is_rejected():
    with pytest.raises(ValidationError, match="encryption.enabled cannot be False"):
        DynamoDBEncryptionSpec(enabled=False)


def test_encryption_disabled_is_rejected_when_nested_in_spec():
    with pytest.raises(ValidationError, match="encryption.enabled cannot be False"):
        DynamoDBResourceSpec(
            name="orders-table",
            partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
            encryption={"enabled": False},
        )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_serialization_is_fully_json_serializable():
    spec = DynamoDBResourceSpec(
        name="orders-table", partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING)
    )
    dumped = spec.model_dump(mode="json")
    json.dumps(dumped)


def test_serialization_round_trip_reconstructs_an_equal_spec():
    original = DynamoDBResourceSpec(
        name="orders-table",
        environment="staging",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        sort_key=DynamoDBKeySpec(name="sk", type=DynamoDBKeyType.NUMBER),
        point_in_time_recovery=False,
        deletion_protection=False,
        tags={"Service": "orders"},
    )
    dumped = original.model_dump(mode="json")
    reconstructed = DynamoDBResourceSpec(**dumped)

    assert reconstructed == original
    assert reconstructed.model_dump(mode="json") == dumped
