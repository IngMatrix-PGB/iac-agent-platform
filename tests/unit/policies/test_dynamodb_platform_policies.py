"""Unit tests for the Phase 2 deterministic DynamoDB platform policies
(Batch 17).

No Terraform, AWS, network, or LLM dependency anywhere in this file.
Mirrors tests/unit/policies/test_s3_platform_policies.py's structure
for the DynamoDB-specific policies.
"""

from __future__ import annotations

from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.security import PolicyStatus, SecuritySeverity
from iac_agent.policies.platform import (
    DDB_DELETION_PROTECTION_RECOMMENDED,
    DDB_ENCRYPTION_REQUIRED,
    DDB_PITR_RECOMMENDED,
    TF_NO_DESTRUCTIVE_CHANGES,
    evaluate_platform_policies,
)
from iac_agent.providers.aws.dynamodb.contract import (
    DynamoDBEncryptionSpec,
    DynamoDBKeySpec,
    DynamoDBKeyType,
    DynamoDBResourceSpec,
)


def _spec(**overrides) -> DynamoDBResourceSpec:
    defaults = {
        "name": "orders-table",
        "partition_key": DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
    }
    defaults.update(overrides)
    return DynamoDBResourceSpec(**defaults)


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


_NO_CHANGE_PLAN = _create_only_plan("module.dynamodb.aws_dynamodb_table.this")


def _find(evaluation, policy_id):
    return next(f for f in evaluation.findings if f.policy_id == policy_id)


# ---------------------------------------------------------------------------
# Encryption policy
# ---------------------------------------------------------------------------


def test_encrypted_table_passes_encryption_policy():
    finding = _find(evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN), DDB_ENCRYPTION_REQUIRED)
    assert finding.status is PolicyStatus.PASS


def test_deliberately_invalid_encryption_disabled_spec_blocks():
    # Pydantic makes encryption.enabled=False unconstructible through
    # normal validation (by design). Bypass it with model_construct —
    # a test-only technique, never used in production code.
    invalid_encryption = DynamoDBEncryptionSpec.model_construct(enabled=False)
    invalid_spec = DynamoDBResourceSpec.model_construct(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        encryption=invalid_encryption,
    )

    finding = _find(
        evaluate_platform_policies(invalid_spec, _NO_CHANGE_PLAN), DDB_ENCRYPTION_REQUIRED
    )
    assert finding.status is PolicyStatus.BLOCK
    assert finding.blocking is True


def test_encryption_block_severity_is_high():
    invalid_encryption = DynamoDBEncryptionSpec.model_construct(enabled=False)
    invalid_spec = DynamoDBResourceSpec.model_construct(
        name="orders-table",
        partition_key=DynamoDBKeySpec(name="pk", type=DynamoDBKeyType.STRING),
        encryption=invalid_encryption,
    )
    finding = _find(
        evaluate_platform_policies(invalid_spec, _NO_CHANGE_PLAN), DDB_ENCRYPTION_REQUIRED
    )
    assert finding.severity is SecuritySeverity.HIGH


# ---------------------------------------------------------------------------
# Point-in-time recovery policy
# ---------------------------------------------------------------------------


def test_pitr_enabled_passes():
    finding = _find(
        evaluate_platform_policies(_spec(point_in_time_recovery=True), _NO_CHANGE_PLAN),
        DDB_PITR_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.PASS


def test_pitr_disabled_warns():
    finding = _find(
        evaluate_platform_policies(_spec(point_in_time_recovery=False), _NO_CHANGE_PLAN),
        DDB_PITR_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.WARN


def test_pitr_warning_is_non_blocking():
    finding = _find(
        evaluate_platform_policies(_spec(point_in_time_recovery=False), _NO_CHANGE_PLAN),
        DDB_PITR_RECOMMENDED,
    )
    assert finding.blocking is False


def test_pitr_warning_severity_is_medium():
    finding = _find(
        evaluate_platform_policies(_spec(point_in_time_recovery=False), _NO_CHANGE_PLAN),
        DDB_PITR_RECOMMENDED,
    )
    assert finding.severity is SecuritySeverity.MEDIUM


# ---------------------------------------------------------------------------
# Deletion-protection policy
# ---------------------------------------------------------------------------


def test_deletion_protection_enabled_passes():
    finding = _find(
        evaluate_platform_policies(_spec(deletion_protection=True), _NO_CHANGE_PLAN),
        DDB_DELETION_PROTECTION_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.PASS


def test_deletion_protection_disabled_warns():
    finding = _find(
        evaluate_platform_policies(_spec(deletion_protection=False), _NO_CHANGE_PLAN),
        DDB_DELETION_PROTECTION_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.WARN


def test_deletion_protection_warning_is_non_blocking():
    finding = _find(
        evaluate_platform_policies(_spec(deletion_protection=False), _NO_CHANGE_PLAN),
        DDB_DELETION_PROTECTION_RECOMMENDED,
    )
    assert finding.blocking is False


def test_deletion_protection_warning_severity_is_medium():
    finding = _find(
        evaluate_platform_policies(_spec(deletion_protection=False), _NO_CHANGE_PLAN),
        DDB_DELETION_PROTECTION_RECOMMENDED,
    )
    assert finding.severity is SecuritySeverity.MEDIUM


# ---------------------------------------------------------------------------
# Shared destructive-change policy (proves it applies to DynamoDB too)
# ---------------------------------------------------------------------------


def test_no_destructive_changes_passes():
    finding = _find(evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN), TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.PASS


def test_delete_action_blocks():
    plan = _destructive_plan(
        action=PlanAction.DELETE, addresses=("module.dynamodb.aws_dynamodb_table.old",)
    )
    finding = _find(evaluate_platform_policies(_spec(), plan), TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.BLOCK


# ---------------------------------------------------------------------------
# Cross-policy scenarios
# ---------------------------------------------------------------------------


def test_secure_table_create_only_gives_four_pass_findings():
    evaluation = evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN)

    assert len(evaluation.findings) == 4
    assert all(f.status is PolicyStatus.PASS for f in evaluation.findings)
    assert evaluation.overall_status is PolicyStatus.PASS


def test_pitr_disabled_gives_overall_warn():
    evaluation = evaluate_platform_policies(_spec(point_in_time_recovery=False), _NO_CHANGE_PLAN)
    assert evaluation.overall_status is PolicyStatus.WARN


def test_deletion_protection_disabled_gives_overall_warn():
    evaluation = evaluate_platform_policies(_spec(deletion_protection=False), _NO_CHANGE_PLAN)
    assert evaluation.overall_status is PolicyStatus.WARN


def test_destructive_plan_gives_overall_block():
    plan = _destructive_plan(
        action=PlanAction.REPLACE, addresses=("module.dynamodb.aws_dynamodb_table.this",)
    )
    evaluation = evaluate_platform_policies(_spec(), plan)
    assert evaluation.overall_status is PolicyStatus.BLOCK


def test_pitr_warn_and_destructive_block_wins_over_warn():
    plan = _destructive_plan(
        action=PlanAction.DELETE, addresses=("module.dynamodb.aws_dynamodb_table.old",)
    )
    evaluation = evaluate_platform_policies(_spec(point_in_time_recovery=False), plan)

    assert evaluation.overall_status is PolicyStatus.BLOCK
    assert _find(evaluation, DDB_PITR_RECOMMENDED).status is PolicyStatus.WARN


def test_same_logical_inputs_produce_equal_evaluation():
    spec_a = _spec(tags={"Service": "orders", "Team": "data"})
    spec_b = _spec(tags={"Team": "data", "Service": "orders"})

    assert evaluate_platform_policies(spec_a, _NO_CHANGE_PLAN) == evaluate_platform_policies(
        spec_b, _NO_CHANGE_PLAN
    )
