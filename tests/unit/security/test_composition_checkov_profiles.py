"""Unit tests for the composition Checkov profile mapping (Batches 19-20)."""

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


def test_api_gateway_lambda_profile_is_exactly_the_seven_approved_skips():
    """Six carried forward from the already-approved API Gateway
    (CKV_AWS_76) and Lambda (five) skips, plus one genuinely new
    finding this batch (CKV_AWS_309, route authorization), approved
    via AskUserQuestion."""
    profile = composition_checkov_profile_for(CompositionType.API_GATEWAY_LAMBDA)
    assert set(profile.skipped_checks) == {
        "CKV_AWS_76",
        "CKV_AWS_117",
        "CKV_AWS_116",
        "CKV_AWS_158",
        "CKV_AWS_173",
        "CKV_AWS_272",
        "CKV_AWS_309",
    }


def test_api_gateway_lambda_profile_never_skips_any_s3_or_dynamodb_specific_check():
    profile = composition_checkov_profile_for(CompositionType.API_GATEWAY_LAMBDA)
    unrelated_checks = {
        "CKV_AWS_18",
        "CKV2_AWS_61",
        "CKV2_AWS_62",
        "CKV_AWS_144",
        "CKV_AWS_119",
    }
    assert unrelated_checks.isdisjoint(profile.skipped_checks)


def test_the_two_composition_profiles_are_not_identical():
    """The two compositions share some Lambda-specific skips but are
    genuinely different profiles — proves this isn't one hardcoded
    global skip bag reused for every composition type."""
    sqs_lambda_dynamodb = composition_checkov_profile_for(CompositionType.SQS_LAMBDA_DYNAMODB)
    api_gateway_lambda = composition_checkov_profile_for(CompositionType.API_GATEWAY_LAMBDA)
    assert set(sqs_lambda_dynamodb.skipped_checks) != set(api_gateway_lambda.skipped_checks)


def test_unregistered_composition_type_raises_value_error():
    class _NotARealCompositionType:
        pass

    with pytest.raises(ValueError, match="no Checkov scan profile registered"):
        composition_checkov_profile_for(_NotARealCompositionType())  # type: ignore[arg-type]
