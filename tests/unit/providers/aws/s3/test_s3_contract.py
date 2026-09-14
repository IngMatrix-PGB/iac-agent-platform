"""Unit tests for the S3 resource contract (Phase 2).

Covers S3ResourceSpec, S3EncryptionSpec: valid construction, every
required hard-failure rule, boundary values, and canonical
serialization. No network, filesystem, LLM, or Terraform dependency is
exercised anywhere in this module.
"""

import json

import pytest
from pydantic import ValidationError

from iac_agent.providers.aws.s3.contract import S3EncryptionSpec, S3ResourceSpec

# ---------------------------------------------------------------------------
# Valid cases
# ---------------------------------------------------------------------------


def test_bucket_with_all_defaults():
    spec = S3ResourceSpec(name="my-example-bucket")

    assert spec.resource_type == "s3_bucket"
    assert spec.name == "my-example-bucket"
    assert spec.environment is None
    assert spec.versioning is True
    assert spec.encryption.enabled is True
    assert spec.encryption.kms_key_id is None
    assert spec.block_public_access is True
    assert spec.tags == {}


def test_bucket_with_environment_set():
    spec = S3ResourceSpec(name="my-example-bucket", environment="staging")
    assert spec.environment == "staging"


def test_bucket_with_custom_tags():
    spec = S3ResourceSpec(name="my-example-bucket", tags={"Service": "reports", "Team": "data"})
    assert spec.tags == {"Service": "reports", "Team": "data"}


def test_bucket_with_versioning_disabled():
    spec = S3ResourceSpec(name="my-example-bucket", versioning=False)
    assert spec.versioning is False


@pytest.mark.parametrize(
    "kms_key_id",
    [
        "arn:aws:kms:us-east-1:123456789012:key/1234abcd-12ab-34cd-56ef-1234567890ab",
        "arn:aws:kms:us-east-1:123456789012:alias/my-bucket-key",
        "alias/my-bucket-key",
        "1234abcd-12ab-34cd-56ef-1234567890ab",
    ],
    ids=["key-arn", "alias-arn", "alias-name", "bare-key-id"],
)
def test_bucket_with_valid_kms_key_id_forms(kms_key_id):
    spec = S3ResourceSpec(
        name="my-example-bucket", encryption=S3EncryptionSpec(kms_key_id=kms_key_id)
    )
    assert spec.encryption.kms_key_id == kms_key_id


# ---------------------------------------------------------------------------
# Bucket name — valid boundary cases
# ---------------------------------------------------------------------------


def test_name_at_minimum_length_is_valid():
    spec = S3ResourceSpec(name="abc")
    assert spec.name == "abc"


def test_name_at_maximum_length_is_valid():
    name = "a" * 63
    spec = S3ResourceSpec(name=name)
    assert spec.name == name


def test_name_allows_digits_periods_and_hyphens():
    spec = S3ResourceSpec(name="my.example-bucket123")
    assert spec.name == "my.example-bucket123"


def test_name_may_begin_and_end_with_digit():
    spec = S3ResourceSpec(name="1-example-bucket9")
    assert spec.name == "1-example-bucket9"


# ---------------------------------------------------------------------------
# Bucket name — invalid cases
# ---------------------------------------------------------------------------


def test_name_too_short_is_rejected():
    with pytest.raises(ValidationError, match="between 3 and 63"):
        S3ResourceSpec(name="ab")


def test_name_too_long_is_rejected():
    with pytest.raises(ValidationError, match="between 3 and 63"):
        S3ResourceSpec(name="a" * 64)


def test_uppercase_name_is_rejected():
    with pytest.raises(ValidationError, match="lowercase"):
        S3ResourceSpec(name="MyExampleBucket")


def test_underscore_in_name_is_rejected():
    with pytest.raises(ValidationError, match="lowercase"):
        S3ResourceSpec(name="my_example_bucket")


def test_name_starting_with_hyphen_is_rejected():
    with pytest.raises(ValidationError, match="begin and end"):
        S3ResourceSpec(name="-my-bucket")


def test_name_ending_with_hyphen_is_rejected():
    with pytest.raises(ValidationError, match="begin and end"):
        S3ResourceSpec(name="my-bucket-")


def test_name_starting_with_period_is_rejected():
    with pytest.raises(ValidationError, match="begin and end"):
        S3ResourceSpec(name=".my-bucket")


def test_adjacent_periods_are_rejected():
    with pytest.raises(ValidationError, match="adjacent periods"):
        S3ResourceSpec(name="my..bucket")


def test_ipv4_shaped_name_is_rejected():
    with pytest.raises(ValidationError, match="IP address"):
        S3ResourceSpec(name="192.168.5.4")


def test_ipv4_shaped_name_with_out_of_range_octets_is_still_rejected():
    """AWS rejects the *shape* of an IP address, not just valid octets."""
    with pytest.raises(ValidationError, match="IP address"):
        S3ResourceSpec(name="999.999.999.999")


@pytest.mark.parametrize(
    "name",
    ["xn--my-bucket", "sthree-my-bucket", "amzn-s3-demo-my-bucket"],
)
def test_reserved_prefixes_are_rejected(name):
    with pytest.raises(ValidationError, match="reserved prefix"):
        S3ResourceSpec(name=name)


@pytest.mark.parametrize(
    "name",
    [
        "my-bucket-s3alias",
        "my-bucket--ol-s3",
        "my-bucket.mrap",
        "my-bucket--x-s3",
        "my-bucket--table-s3",
    ],
)
def test_reserved_suffixes_are_rejected(name):
    with pytest.raises(ValidationError, match="reserved suffix"):
        S3ResourceSpec(name=name)


# ---------------------------------------------------------------------------
# Hard invariants
# ---------------------------------------------------------------------------


def test_encryption_disabled_is_rejected():
    with pytest.raises(ValidationError, match="encryption.enabled cannot be False"):
        S3EncryptionSpec(enabled=False)


def test_encryption_disabled_is_rejected_when_nested_in_spec():
    with pytest.raises(ValidationError, match="encryption.enabled cannot be False"):
        S3ResourceSpec(name="my-example-bucket", encryption={"enabled": False})


def test_block_public_access_disabled_is_rejected():
    with pytest.raises(ValidationError, match="block_public_access cannot be False"):
        S3ResourceSpec(name="my-example-bucket", block_public_access=False)


def test_malformed_kms_key_id_is_rejected():
    with pytest.raises(ValidationError, match="not a recognizable KMS key"):
        S3EncryptionSpec(kms_key_id="not-a-valid-key!")


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_serialization_is_fully_json_serializable():
    spec = S3ResourceSpec(name="my-example-bucket")
    dumped = spec.model_dump(mode="json")
    json.dumps(dumped)


def test_serialization_round_trip_reconstructs_an_equal_spec():
    original = S3ResourceSpec(
        name="my-example-bucket",
        environment="staging",
        versioning=False,
        tags={"Service": "reports"},
        encryption=S3EncryptionSpec(kms_key_id="alias/my-bucket-key"),
    )
    dumped = original.model_dump(mode="json")
    reconstructed = S3ResourceSpec(**dumped)

    assert reconstructed == original
    assert reconstructed.model_dump(mode="json") == dumped
