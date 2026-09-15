"""Unit tests for the Phase 2 deterministic S3 platform policies.

No Terraform, AWS, network, or LLM dependency anywhere in this file.
Mirrors tests/unit/policies/test_platform_policies.py's structure for
the S3-specific policies.
"""

from __future__ import annotations

from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.security import PolicyStatus, SecuritySeverity
from iac_agent.policies.platform import (
    S3_ENCRYPTION_REQUIRED,
    S3_PUBLIC_ACCESS_BLOCK_REQUIRED,
    S3_VERSIONING_RECOMMENDED,
    TF_NO_DESTRUCTIVE_CHANGES,
    evaluate_platform_policies,
)
from iac_agent.providers.aws.s3.contract import S3EncryptionSpec, S3ResourceSpec


def _spec(**overrides) -> S3ResourceSpec:
    defaults = {"name": "my-example-bucket"}
    defaults.update(overrides)
    return S3ResourceSpec(**defaults)


def _create_only_plan(*addresses: str) -> PlanSummary:
    changes = tuple(
        ResourceChange(
            address=addr,
            actions=("create",),
            action=PlanAction.CREATE,
            replacement=False,
            destructive=False,
        )
        for addr in addresses
    )
    return PlanSummary(
        resource_changes=changes,
        resources_to_add=tuple(sorted(addresses)),
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def _destructive_plan(*, action: PlanAction, addresses: tuple[str, ...]) -> PlanSummary:
    changes = tuple(
        ResourceChange(
            address=addr,
            actions=("delete",) if action is PlanAction.DELETE else ("delete", "create"),
            action=action,
            replacement=(action is PlanAction.REPLACE),
            destructive=True,
        )
        for addr in addresses
    )
    return PlanSummary(
        resource_changes=changes,
        resources_to_add=(),
        resources_to_change=(),
        resources_to_destroy=tuple(sorted(addresses)),
        destructive_change_detected=True,
    )


_NO_CHANGE_PLAN = _create_only_plan("module.bucket.aws_s3_bucket.this")


def _find(evaluation, policy_id):
    return next(f for f in evaluation.findings if f.policy_id == policy_id)


# ---------------------------------------------------------------------------
# Encryption policy
# ---------------------------------------------------------------------------


def test_encrypted_bucket_passes_encryption_policy():
    finding = _find(evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN), S3_ENCRYPTION_REQUIRED)
    assert finding.status is PolicyStatus.PASS


def test_kms_encrypted_bucket_passes_encryption_policy():
    spec = _spec(encryption=S3EncryptionSpec(kms_key_id="alias/aws/s3"))
    finding = _find(evaluate_platform_policies(spec, _NO_CHANGE_PLAN), S3_ENCRYPTION_REQUIRED)
    assert finding.status is PolicyStatus.PASS


def test_deliberately_invalid_encryption_disabled_spec_blocks():
    # Pydantic makes encryption.enabled=False unconstructible through
    # normal validation (by design). Bypass it with model_construct —
    # a test-only technique, never used in production code.
    invalid_encryption = S3EncryptionSpec.model_construct(enabled=False, kms_key_id=None)
    invalid_spec = S3ResourceSpec.model_construct(
        name="my-example-bucket", encryption=invalid_encryption
    )

    finding = _find(
        evaluate_platform_policies(invalid_spec, _NO_CHANGE_PLAN), S3_ENCRYPTION_REQUIRED
    )
    assert finding.status is PolicyStatus.BLOCK
    assert finding.blocking is True


def test_encryption_block_severity_is_high():
    invalid_encryption = S3EncryptionSpec.model_construct(enabled=False, kms_key_id=None)
    invalid_spec = S3ResourceSpec.model_construct(
        name="my-example-bucket", encryption=invalid_encryption
    )
    finding = _find(
        evaluate_platform_policies(invalid_spec, _NO_CHANGE_PLAN), S3_ENCRYPTION_REQUIRED
    )
    assert finding.severity is SecuritySeverity.HIGH


# ---------------------------------------------------------------------------
# Public access block policy
# ---------------------------------------------------------------------------


def test_public_access_blocked_passes():
    finding = _find(
        evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN), S3_PUBLIC_ACCESS_BLOCK_REQUIRED
    )
    assert finding.status is PolicyStatus.PASS


def test_deliberately_invalid_public_access_unblocked_spec_blocks():
    invalid_spec = S3ResourceSpec.model_construct(
        name="my-example-bucket",
        block_public_access=False,
        encryption=S3EncryptionSpec(),
        versioning=True,
        tags={},
    )
    finding = _find(
        evaluate_platform_policies(invalid_spec, _NO_CHANGE_PLAN), S3_PUBLIC_ACCESS_BLOCK_REQUIRED
    )
    assert finding.status is PolicyStatus.BLOCK
    assert finding.blocking is True


def test_public_access_block_severity_is_critical():
    finding = _find(
        evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN), S3_PUBLIC_ACCESS_BLOCK_REQUIRED
    )
    assert finding.severity is SecuritySeverity.CRITICAL


# ---------------------------------------------------------------------------
# Versioning policy
# ---------------------------------------------------------------------------


def test_versioning_enabled_passes():
    finding = _find(
        evaluate_platform_policies(_spec(versioning=True), _NO_CHANGE_PLAN),
        S3_VERSIONING_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.PASS


def test_versioning_disabled_warns():
    finding = _find(
        evaluate_platform_policies(_spec(versioning=False), _NO_CHANGE_PLAN),
        S3_VERSIONING_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.WARN


def test_versioning_warning_is_non_blocking():
    finding = _find(
        evaluate_platform_policies(_spec(versioning=False), _NO_CHANGE_PLAN),
        S3_VERSIONING_RECOMMENDED,
    )
    assert finding.blocking is False


def test_versioning_warning_severity_is_medium():
    finding = _find(
        evaluate_platform_policies(_spec(versioning=False), _NO_CHANGE_PLAN),
        S3_VERSIONING_RECOMMENDED,
    )
    assert finding.severity is SecuritySeverity.MEDIUM


# ---------------------------------------------------------------------------
# Shared destructive-change policy (proves it applies to S3 too)
# ---------------------------------------------------------------------------


def test_no_destructive_changes_passes():
    finding = _find(evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN), TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.PASS


def test_delete_action_blocks():
    plan = _destructive_plan(
        action=PlanAction.DELETE, addresses=("module.bucket.aws_s3_bucket.old",)
    )
    finding = _find(evaluate_platform_policies(_spec(), plan), TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.BLOCK


# ---------------------------------------------------------------------------
# Cross-policy scenarios
# ---------------------------------------------------------------------------


def test_secure_bucket_create_only_gives_four_pass_findings():
    evaluation = evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN)

    assert len(evaluation.findings) == 4
    assert all(f.status is PolicyStatus.PASS for f in evaluation.findings)
    assert evaluation.overall_status is PolicyStatus.PASS


def test_versioning_disabled_gives_overall_warn():
    evaluation = evaluate_platform_policies(_spec(versioning=False), _NO_CHANGE_PLAN)
    assert evaluation.overall_status is PolicyStatus.WARN


def test_destructive_plan_gives_overall_block():
    plan = _destructive_plan(
        action=PlanAction.REPLACE, addresses=("module.bucket.aws_s3_bucket.this",)
    )
    evaluation = evaluate_platform_policies(_spec(), plan)
    assert evaluation.overall_status is PolicyStatus.BLOCK


def test_versioning_warn_and_destructive_block_wins_over_warn():
    plan = _destructive_plan(
        action=PlanAction.DELETE, addresses=("module.bucket.aws_s3_bucket.old",)
    )
    evaluation = evaluate_platform_policies(_spec(versioning=False), plan)

    assert evaluation.overall_status is PolicyStatus.BLOCK
    assert _find(evaluation, S3_VERSIONING_RECOMMENDED).status is PolicyStatus.WARN


def test_same_logical_inputs_produce_equal_evaluation():
    spec_a = _spec(tags={"Service": "reports", "Team": "data"})
    spec_b = _spec(tags={"Team": "data", "Service": "reports"})

    assert evaluate_platform_policies(spec_a, _NO_CHANGE_PLAN) == evaluate_platform_policies(
        spec_b, _NO_CHANGE_PLAN
    )
