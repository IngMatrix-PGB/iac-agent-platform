"""Unit tests for ECR platform policies (Batch 27)."""

from __future__ import annotations

import pytest

from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.security import FindingSource, PolicyStatus, SecuritySeverity
from iac_agent.policies.platform import (
    ECR_ENCRYPTION_REQUIRED,
    ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED,
    ECR_SCAN_ON_PUSH_RECOMMENDED,
    TF_NO_DESTRUCTIVE_CHANGES,
    evaluate_platform_policies,
)
from iac_agent.providers.aws.ecr.contract import (
    EcrEncryptionSpec,
    EcrImageTagMutability,
    EcrResourceSpec,
)


def _plan() -> PlanSummary:
    change = ResourceChange(
        address="module.ecr.aws_ecr_repository.this",
        actions=("create",),
        action=PlanAction.CREATE,
        replacement=False,
        destructive=False,
    )
    return PlanSummary(
        resource_changes=(change,),
        resources_to_add=("module.ecr.aws_ecr_repository.this",),
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def _finding(evaluation, policy_id: str):
    matches = [finding for finding in evaluation.findings if finding.policy_id == policy_id]
    assert len(matches) == 1
    return matches[0]


def test_secure_default_repository_passes_every_ecr_policy():
    evaluation = evaluate_platform_policies(EcrResourceSpec(name="orders"), _plan())
    actual = {finding.policy_id for finding in evaluation.findings}
    assert actual == {
        ECR_ENCRYPTION_REQUIRED,
        ECR_SCAN_ON_PUSH_RECOMMENDED,
        ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED,
        TF_NO_DESTRUCTIVE_CHANGES,
    }
    assert all(finding.status is PolicyStatus.PASS for finding in evaluation.findings)


def test_encryption_disabled_blocks():
    invalid = EcrResourceSpec.model_construct(
        name="orders",
        image_tag_mutability=EcrImageTagMutability.IMMUTABLE,
        scan_on_push=True,
        encryption=EcrEncryptionSpec.model_construct(enabled=False),
        tags={},
    )
    finding = _finding(evaluate_platform_policies(invalid, _plan()), ECR_ENCRYPTION_REQUIRED)
    assert finding.status is PolicyStatus.BLOCK
    assert finding.severity is SecuritySeverity.HIGH
    assert finding.source is FindingSource.PLATFORM_POLICY
    assert finding.blocking is True


def test_scan_on_push_disabled_warns():
    finding = _finding(
        evaluate_platform_policies(EcrResourceSpec(name="orders", scan_on_push=False), _plan()),
        ECR_SCAN_ON_PUSH_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.WARN
    assert finding.severity is SecuritySeverity.MEDIUM


def test_mutable_tags_warn():
    finding = _finding(
        evaluate_platform_policies(
            EcrResourceSpec(name="orders", image_tag_mutability=EcrImageTagMutability.MUTABLE),
            _plan(),
        ),
        ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.WARN


def test_unknown_spec_type_still_fails_closed():
    with pytest.raises(ValueError, match="unsupported resource spec type"):
        evaluate_platform_policies(object(), _plan())  # type: ignore[arg-type]
