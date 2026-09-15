"""Unit tests for the composition Checkov profile mapping (Batch 19)."""

from __future__ import annotations

import pytest

from iac_agent.domain.composition import CompositionType
from iac_agent.security.composition_checkov_profiles import composition_checkov_profile_for


def test_sqs_lambda_dynamodb_profile_is_exactly_the_six_approved_skips():
    profile = composition_checkov_profile_for(CompositionType.SQS_LAMBDA_DYNAMODB)
    assert set(profile.skipped_checks) == {
        "CKV_AWS_119",
        "CKV_AWS_117",
        "CKV_AWS_116",
        "CKV_AWS_158",
        "CKV_AWS_173",
        "CKV_AWS_272",
    }


def test_profile_never_skips_any_s3_specific_check():
    # This composition never uses S3 — proving the four S3-specific
    # skip IDs from `iac_agent.security.checkov_profiles` never appear
    # here is a direct proof against accidentally unioning in
    # unrelated resource skip lists.
    profile = composition_checkov_profile_for(CompositionType.SQS_LAMBDA_DYNAMODB)
    s3_only_checks = {"CKV_AWS_18", "CKV2_AWS_61", "CKV2_AWS_62", "CKV_AWS_144"}
    assert s3_only_checks.isdisjoint(profile.skipped_checks)


def test_unregistered_composition_type_raises_value_error():
    class _NotARealCompositionType:
        pass

    with pytest.raises(ValueError, match="no Checkov scan profile registered"):
        composition_checkov_profile_for(_NotARealCompositionType())  # type: ignore[arg-type]
