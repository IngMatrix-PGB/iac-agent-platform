"""Unit tests for the resource-aware Checkov scan profile mapping
(Batch 16.5).

Pure lookup logic — no subprocess, no real Checkov binary required.
"""

from __future__ import annotations

import pytest

from iac_agent.domain.resource import ResourceType
from iac_agent.security.checkov import CheckovScanProfile
from iac_agent.security.checkov_profiles import checkov_profile_for


def test_sqs_profile_has_no_skips():
    profile = checkov_profile_for(ResourceType.SQS)
    assert isinstance(profile, CheckovScanProfile)
    assert profile.skipped_checks == ()


def test_s3_profile_has_exactly_the_four_approved_skips():
    profile = checkov_profile_for(ResourceType.S3)
    assert profile.skipped_checks == (
        "CKV_AWS_18",
        "CKV2_AWS_61",
        "CKV2_AWS_62",
        "CKV_AWS_144",
    )


def test_dynamodb_profile_has_exactly_the_one_approved_skip():
    """Batch 17: a real Checkov scan of the trusted DynamoDB module's
    secure baseline reported exactly one finding (CKV_AWS_119,
    customer-managed KMS) — corresponding to the one documented Phase 2
    DynamoDB non-goal, approved via AskUserQuestion before being added."""
    profile = checkov_profile_for(ResourceType.DYNAMODB)
    assert isinstance(profile, CheckovScanProfile)
    assert profile.skipped_checks == ("CKV_AWS_119",)


def test_lambda_profile_has_exactly_the_five_approved_skips():
    """Batch 18: a real Checkov scan of the trusted Lambda+IAM module's
    secure baseline reported exactly five findings (after fixing the
    one real defect — CKV_AWS_338 log retention — by raising the
    default to 365 days), each corresponding to a documented Phase 2
    Lambda non-goal, approved via AskUserQuestion before being added."""
    profile = checkov_profile_for(ResourceType.LAMBDA)
    assert isinstance(profile, CheckovScanProfile)
    assert profile.skipped_checks == (
        "CKV_AWS_117",
        "CKV_AWS_116",
        "CKV_AWS_158",
        "CKV_AWS_173",
        "CKV_AWS_272",
    )


def test_all_four_resource_profiles_are_pairwise_disjoint():
    """Proves isolation across every registered resource type at once —
    no skip check ever leaks from one resource's profile into
    another's."""
    profiles = {
        resource_type: set(checkov_profile_for(resource_type).skipped_checks)
        for resource_type in ResourceType
    }
    resource_types = list(profiles)
    for i, a in enumerate(resource_types):
        for b in resource_types[i + 1 :]:
            assert profiles[a].isdisjoint(profiles[b]), (a, b, profiles[a], profiles[b])


def test_every_registered_resource_type_has_a_profile():
    """Fails closed the other direction too: every current `ResourceType`
    member must have an explicit, reviewed profile decision — a new
    member added without updating the mapping is a real gap, not
    something this test should quietly tolerate."""
    for resource_type in ResourceType:
        assert isinstance(checkov_profile_for(resource_type), CheckovScanProfile)


def test_unregistered_resource_type_fails_closed():
    """An unknown/unregistered resource type must never silently
    receive skips (or silently receive the strict profile either) —
    it must fail loudly."""

    class _NotARealResourceType:
        pass

    with pytest.raises(ValueError, match="no Checkov scan profile registered"):
        checkov_profile_for(_NotARealResourceType())  # type: ignore[arg-type]


def test_calling_twice_returns_equal_profiles():
    """Deterministic: the same resource type always yields an equal
    profile, never a fresh/different one from call to call."""
    assert checkov_profile_for(ResourceType.S3) == checkov_profile_for(ResourceType.S3)
