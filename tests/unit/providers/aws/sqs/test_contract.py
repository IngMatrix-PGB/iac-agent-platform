"""Unit tests for the SQS resource contract.

Covers SQSResourceSpec, EncryptionSpec, and DlqSpec: valid construction,
every required hard-failure rule, boundary values, and canonical
serialization. No network, filesystem, LLM, or Terraform dependency is
exercised anywhere in this module.
"""

import json

import pytest
from pydantic import ValidationError

from iac_agent.providers.aws.sqs.contract import DlqSpec, EncryptionSpec, SQSResourceSpec

# ---------------------------------------------------------------------------
# Valid cases
# ---------------------------------------------------------------------------


def test_standard_queue_with_all_defaults():
    spec = SQSResourceSpec(name="order-events")

    assert spec.resource_type == "sqs_queue"
    assert spec.name == "order-events"
    assert spec.environment is None
    assert spec.fifo is False
    assert spec.visibility_timeout_seconds == 30
    assert spec.message_retention_seconds == 345600
    assert spec.delay_seconds == 0
    assert spec.encryption.enabled is True
    assert spec.encryption.kms_key_id is None
    assert spec.dlq.enabled is True
    assert spec.dlq.max_receive_count == 5
    assert spec.tags == {}


def test_standard_queue_with_custom_numeric_values():
    spec = SQSResourceSpec(
        name="payment-events",
        visibility_timeout_seconds=120,
        message_retention_seconds=86400,
        delay_seconds=15,
    )

    assert spec.visibility_timeout_seconds == 120
    assert spec.message_retention_seconds == 86400
    assert spec.delay_seconds == 15


def test_fifo_queue_with_fifo_suffix():
    spec = SQSResourceSpec(name="order-processing.fifo", fifo=True)

    assert spec.fifo is True
    assert spec.name == "order-processing.fifo"


def test_queue_with_environment_set():
    spec = SQSResourceSpec(name="order-events", environment="staging")

    assert spec.environment == "staging"


def test_queue_with_custom_tags():
    spec = SQSResourceSpec(name="order-events", tags={"Service": "orders", "Team": "platform"})

    assert spec.tags == {"Service": "orders", "Team": "platform"}


def test_queue_uses_default_sse_sqs_encryption_when_no_kms_key_given():
    spec = SQSResourceSpec(name="order-events")

    assert spec.encryption.enabled is True
    assert spec.encryption.kms_key_id is None


@pytest.mark.parametrize(
    "kms_key_id",
    [
        "arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab",
        "arn:aws:kms:us-east-1:123456789012:alias/my-queue-key",
        "alias/my-queue-key",
        "1234abcd-12ab-34cd-56ef-1234567890ab",
    ],
    ids=["key-arn", "alias-arn", "alias-name", "bare-key-id"],
)
def test_queue_with_valid_kms_key_id_forms(kms_key_id):
    spec = SQSResourceSpec(name="order-events", encryption=EncryptionSpec(kms_key_id=kms_key_id))

    assert spec.encryption.kms_key_id == kms_key_id


def test_dlq_enabled_with_default_max_receive_count():
    spec = SQSResourceSpec(name="order-events", dlq=DlqSpec())

    assert spec.dlq.enabled is True
    assert spec.dlq.max_receive_count == 5


def test_dlq_disabled_with_max_receive_count_none():
    spec = SQSResourceSpec(name="order-events", dlq=DlqSpec(enabled=False, max_receive_count=None))

    assert spec.dlq.enabled is False
    assert spec.dlq.max_receive_count is None


def test_name_allows_hyphen_and_underscore():
    spec = SQSResourceSpec(name="order_events-v2")

    assert spec.name == "order_events-v2"


# ---------------------------------------------------------------------------
# Boundary values (valid)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 43200], ids=["min", "max"])
def test_visibility_timeout_boundaries_are_valid(value):
    spec = SQSResourceSpec(name="order-events", visibility_timeout_seconds=value)
    assert spec.visibility_timeout_seconds == value


@pytest.mark.parametrize("value", [60, 1209600], ids=["min", "max"])
def test_message_retention_boundaries_are_valid(value):
    spec = SQSResourceSpec(name="order-events", message_retention_seconds=value)
    assert spec.message_retention_seconds == value


@pytest.mark.parametrize("value", [0, 900], ids=["min", "max"])
def test_delay_seconds_boundaries_are_valid(value):
    spec = SQSResourceSpec(name="order-events", delay_seconds=value)
    assert spec.delay_seconds == value


@pytest.mark.parametrize("value", [1, 1000], ids=["min", "max"])
def test_dlq_max_receive_count_boundaries_are_valid(value):
    spec = SQSResourceSpec(name="order-events", dlq=DlqSpec(max_receive_count=value))
    assert spec.dlq.max_receive_count == value


def test_name_at_max_length_is_valid():
    name = "a" * 80
    spec = SQSResourceSpec(name=name)
    assert spec.name == name


# ---------------------------------------------------------------------------
# Invalid cases — required hard failures
# ---------------------------------------------------------------------------


def test_empty_name_is_rejected():
    with pytest.raises(ValidationError, match="must not be empty"):
        SQSResourceSpec(name="")


@pytest.mark.parametrize(
    "name",
    ["orders!events", "orders/events", "orders events", "orders.events", "orders@prod"],
)
def test_name_with_invalid_characters_is_rejected(name):
    with pytest.raises(ValidationError, match="alphanumeric"):
        SQSResourceSpec(name=name)


def test_name_over_max_length_is_rejected():
    name = "a" * 81
    with pytest.raises(ValidationError, match="80 characters"):
        SQSResourceSpec(name=name)


def test_fifo_true_without_fifo_suffix_is_rejected():
    with pytest.raises(ValidationError, match=r"fifo=True requires name"):
        SQSResourceSpec(name="orders", fifo=True)


def test_fifo_false_with_fifo_suffix_is_rejected():
    with pytest.raises(ValidationError, match=r"fifo=False requires name"):
        SQSResourceSpec(name="orders.fifo", fifo=False)


def test_encryption_disabled_is_rejected():
    with pytest.raises(ValidationError, match="encryption.enabled cannot be False"):
        EncryptionSpec(enabled=False)


def test_encryption_disabled_is_rejected_when_nested_in_spec():
    """A caller cannot smuggle an unencrypted queue in through the parent
    model either — passing the raw dict form still runs EncryptionSpec's
    own validation, it is not bypassed by nesting."""
    with pytest.raises(ValidationError, match="encryption.enabled cannot be False"):
        SQSResourceSpec(name="order-events", encryption={"enabled": False})


@pytest.mark.parametrize("value", [-1, -100])
def test_visibility_timeout_below_minimum_is_rejected(value):
    with pytest.raises(ValidationError):
        SQSResourceSpec(name="order-events", visibility_timeout_seconds=value)


@pytest.mark.parametrize("value", [43201, 100000])
def test_visibility_timeout_above_maximum_is_rejected(value):
    with pytest.raises(ValidationError):
        SQSResourceSpec(name="order-events", visibility_timeout_seconds=value)


@pytest.mark.parametrize("value", [0, 59])
def test_retention_below_minimum_is_rejected(value):
    with pytest.raises(ValidationError):
        SQSResourceSpec(name="order-events", message_retention_seconds=value)


@pytest.mark.parametrize("value", [1209601, 2000000])
def test_retention_above_maximum_is_rejected(value):
    with pytest.raises(ValidationError):
        SQSResourceSpec(name="order-events", message_retention_seconds=value)


@pytest.mark.parametrize("value", [-1, -50])
def test_delay_below_minimum_is_rejected(value):
    with pytest.raises(ValidationError):
        SQSResourceSpec(name="order-events", delay_seconds=value)


@pytest.mark.parametrize("value", [901, 1000])
def test_delay_above_maximum_is_rejected(value):
    with pytest.raises(ValidationError):
        SQSResourceSpec(name="order-events", delay_seconds=value)


@pytest.mark.parametrize("value", [0, -1])
def test_dlq_max_receive_count_below_minimum_is_rejected(value):
    with pytest.raises(ValidationError, match="max_receive_count must be between"):
        DlqSpec(max_receive_count=value)


@pytest.mark.parametrize("value", [1001, 5000])
def test_dlq_max_receive_count_above_maximum_is_rejected(value):
    with pytest.raises(ValidationError, match="max_receive_count must be between"):
        DlqSpec(max_receive_count=value)


def test_dlq_disabled_while_max_receive_count_is_set_is_rejected():
    with pytest.raises(ValidationError, match="must be None when dlq.enabled is False"):
        DlqSpec(enabled=False, max_receive_count=5)


def test_dlq_enabled_without_max_receive_count_is_rejected():
    with pytest.raises(ValidationError, match="is required when dlq.enabled is True"):
        DlqSpec(enabled=True, max_receive_count=None)


def test_malformed_kms_key_id_is_rejected():
    with pytest.raises(ValidationError, match="not a recognizable KMS key"):
        EncryptionSpec(kms_key_id="not-a-valid-key!")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_serialization_is_fully_json_serializable():
    spec = SQSResourceSpec(name="order-events")
    dumped = spec.model_dump(mode="json")

    # Must not raise — proves there is no hidden non-JSON runtime state.
    json.dumps(dumped)


def test_serialization_includes_nested_encryption_and_dlq_objects():
    spec = SQSResourceSpec(
        name="order-events",
        encryption=EncryptionSpec(kms_key_id="alias/my-queue-key"),
        dlq=DlqSpec(max_receive_count=3),
    )
    dumped = spec.model_dump(mode="json")

    assert dumped["encryption"] == {"enabled": True, "kms_key_id": "alias/my-queue-key"}
    assert dumped["dlq"] == {"enabled": True, "max_receive_count": 3}


def test_serialization_includes_tags():
    spec = SQSResourceSpec(name="order-events", tags={"Service": "orders"})
    dumped = spec.model_dump(mode="json")

    assert dumped["tags"] == {"Service": "orders"}


def test_serialization_represents_optional_environment_as_null():
    spec = SQSResourceSpec(name="order-events")
    dumped = spec.model_dump(mode="json")

    assert dumped["environment"] is None


def test_serialization_represents_none_kms_key_id_as_null():
    spec = SQSResourceSpec(name="order-events")
    dumped = spec.model_dump(mode="json")

    assert dumped["encryption"]["kms_key_id"] is None


def test_serialization_is_deterministic_for_the_same_spec():
    spec = SQSResourceSpec(name="order-events", tags={"Service": "orders"})

    assert spec.model_dump(mode="json") == spec.model_dump(mode="json")


def test_serialization_round_trip_reconstructs_an_equal_spec():
    original = SQSResourceSpec(
        name="order-processing.fifo",
        fifo=True,
        environment="staging",
        tags={"Service": "orders"},
        encryption=EncryptionSpec(kms_key_id="alias/my-queue-key"),
        dlq=DlqSpec(max_receive_count=3),
    )

    dumped = original.model_dump(mode="json")
    reconstructed = SQSResourceSpec(**dumped)

    assert reconstructed == original
    assert reconstructed.model_dump(mode="json") == dumped
