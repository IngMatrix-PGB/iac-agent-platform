"""Unit tests for the Phase 1 deterministic platform policies.

No Terraform, AWS, network, or LLM dependency anywhere in this file —
policies consume only SQSResourceSpec and PlanSummary. Real-Terraform
evidence is exercised separately by
tests/integration/test_platform_policy_integration.py.
"""

from __future__ import annotations

import inspect

from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.security import PolicyStatus, SecuritySeverity
from iac_agent.policies import platform
from iac_agent.policies.platform import (
    SQS_DLQ_RECOMMENDED,
    SQS_ENCRYPTION_REQUIRED,
    TF_NO_DESTRUCTIVE_CHANGES,
    evaluate_platform_policies,
)
from iac_agent.providers.aws.sqs.contract import DlqSpec, EncryptionSpec, SQSResourceSpec


def _spec(**overrides) -> SQSResourceSpec:
    defaults = {"name": "order-events"}
    defaults.update(overrides)
    return SQSResourceSpec(**defaults)


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


_NO_CHANGE_PLAN = _create_only_plan("module.queue.aws_sqs_queue.this")


def _find(evaluation, policy_id):
    return next(f for f in evaluation.findings if f.policy_id == policy_id)


# ---------------------------------------------------------------------------
# Encryption policy
# ---------------------------------------------------------------------------


def test_encrypted_queue_passes_encryption_policy():
    evaluation = evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN)
    finding = _find(evaluation, SQS_ENCRYPTION_REQUIRED)
    assert finding.status is PolicyStatus.PASS


def test_kms_encrypted_queue_passes_encryption_policy():
    spec = _spec(encryption=EncryptionSpec(kms_key_id="alias/aws/sqs"))
    evaluation = evaluate_platform_policies(spec, _NO_CHANGE_PLAN)
    finding = _find(evaluation, SQS_ENCRYPTION_REQUIRED)
    assert finding.status is PolicyStatus.PASS


def test_deliberately_invalid_encryption_disabled_spec_blocks():
    # Pydantic makes encryption.enabled=False unconstructible through
    # normal validation (by design). To exercise this policy's defense-
    # in-depth path, we deliberately bypass validation with
    # model_construct — a test-only technique, never used in production
    # code, and production validation is not weakened to allow this.
    invalid_encryption = EncryptionSpec.model_construct(enabled=False, kms_key_id=None)
    invalid_spec = SQSResourceSpec.model_construct(
        name="order-events", encryption=invalid_encryption
    )

    evaluation = evaluate_platform_policies(invalid_spec, _NO_CHANGE_PLAN)
    finding = _find(evaluation, SQS_ENCRYPTION_REQUIRED)

    assert finding.status is PolicyStatus.BLOCK
    assert finding.blocking is True


def test_encryption_block_severity_is_high():
    invalid_encryption = EncryptionSpec.model_construct(enabled=False, kms_key_id=None)
    invalid_spec = SQSResourceSpec.model_construct(
        name="order-events", encryption=invalid_encryption
    )

    finding = _find(
        evaluate_platform_policies(invalid_spec, _NO_CHANGE_PLAN), SQS_ENCRYPTION_REQUIRED
    )
    assert finding.severity is SecuritySeverity.HIGH


# ---------------------------------------------------------------------------
# DLQ policy
# ---------------------------------------------------------------------------


def test_dlq_enabled_passes():
    evaluation = evaluate_platform_policies(
        _spec(dlq=DlqSpec(enabled=True, max_receive_count=5)), _NO_CHANGE_PLAN
    )
    finding = _find(evaluation, SQS_DLQ_RECOMMENDED)
    assert finding.status is PolicyStatus.PASS


def test_dlq_disabled_warns():
    spec = _spec(dlq=DlqSpec(enabled=False, max_receive_count=None))
    evaluation = evaluate_platform_policies(spec, _NO_CHANGE_PLAN)
    finding = _find(evaluation, SQS_DLQ_RECOMMENDED)
    assert finding.status is PolicyStatus.WARN


def test_dlq_warning_is_non_blocking():
    spec = _spec(dlq=DlqSpec(enabled=False, max_receive_count=None))
    finding = _find(evaluate_platform_policies(spec, _NO_CHANGE_PLAN), SQS_DLQ_RECOMMENDED)
    assert finding.blocking is False


def test_dlq_warning_severity_is_medium():
    spec = _spec(dlq=DlqSpec(enabled=False, max_receive_count=None))
    finding = _find(evaluate_platform_policies(spec, _NO_CHANGE_PLAN), SQS_DLQ_RECOMMENDED)
    assert finding.severity is SecuritySeverity.MEDIUM


# ---------------------------------------------------------------------------
# Destructive-change policy
# ---------------------------------------------------------------------------


def test_no_destructive_changes_passes():
    finding = _find(evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN), TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.PASS


def test_delete_action_blocks():
    plan = _destructive_plan(
        action=PlanAction.DELETE, addresses=("module.queue.aws_sqs_queue.old",)
    )
    finding = _find(evaluate_platform_policies(_spec(), plan), TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.BLOCK


def test_replace_action_blocks():
    plan = _destructive_plan(
        action=PlanAction.REPLACE, addresses=("module.queue.aws_sqs_queue.this",)
    )
    finding = _find(evaluate_platform_policies(_spec(), plan), TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.BLOCK


def test_multiple_destructive_addresses_produce_deterministic_sorted_message():
    plan = _destructive_plan(
        action=PlanAction.DELETE,
        addresses=("module.queue.aws_sqs_queue.zzz", "module.queue.aws_sqs_queue.aaa"),
    )
    finding = _find(evaluate_platform_policies(_spec(), plan), TF_NO_DESTRUCTIVE_CHANGES)

    assert "aaa" in finding.message
    assert finding.message.index("aaa") < finding.message.index("zzz")


def test_destructive_block_severity_is_critical():
    plan = _destructive_plan(action=PlanAction.DELETE, addresses=("x",))
    finding = _find(evaluate_platform_policies(_spec(), plan), TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.severity is SecuritySeverity.CRITICAL


def test_raw_before_after_values_cannot_appear_in_destructive_finding():
    plan = _destructive_plan(
        action=PlanAction.DELETE, addresses=("module.queue.aws_sqs_queue.old",)
    )
    finding = _find(evaluate_platform_policies(_spec(), plan), TF_NO_DESTRUCTIVE_CHANGES)

    # ResourceChange itself never carries before/after values (Batch 6),
    # so there is nothing of that shape for this policy to leak; confirm
    # the finding message only ever contains the address, not any
    # fabricated infrastructure value.
    assert (
        finding.message
        == "Terraform plan contains destructive changes: module.queue.aws_sqs_queue.old."
    )


# ---------------------------------------------------------------------------
# Cross-policy scenarios
# ---------------------------------------------------------------------------


def test_normal_encrypted_dlq_create_only_gives_three_pass_findings():
    evaluation = evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN)

    assert len(evaluation.findings) == 3
    assert all(f.status is PolicyStatus.PASS for f in evaluation.findings)
    assert evaluation.overall_status is PolicyStatus.PASS


def test_encrypted_no_dlq_create_only_gives_overall_warn():
    spec = _spec(dlq=DlqSpec(enabled=False, max_receive_count=None))
    evaluation = evaluate_platform_policies(spec, _NO_CHANGE_PLAN)

    assert evaluation.overall_status is PolicyStatus.WARN


def test_encrypted_dlq_destructive_gives_overall_block():
    plan = _destructive_plan(
        action=PlanAction.REPLACE, addresses=("module.queue.aws_sqs_queue.this",)
    )
    evaluation = evaluate_platform_policies(_spec(), plan)

    assert evaluation.overall_status is PolicyStatus.BLOCK


def test_no_dlq_and_destructive_block_wins_over_warn():
    spec = _spec(dlq=DlqSpec(enabled=False, max_receive_count=None))
    plan = _destructive_plan(
        action=PlanAction.DELETE, addresses=("module.queue.aws_sqs_queue.old",)
    )
    evaluation = evaluate_platform_policies(spec, plan)

    assert evaluation.overall_status is PolicyStatus.BLOCK
    assert _find(evaluation, SQS_DLQ_RECOMMENDED).status is PolicyStatus.WARN


def test_same_logical_inputs_produce_equal_evaluation():
    spec_a = _spec(tags={"Service": "orders", "Team": "platform"})
    spec_b = _spec(tags={"Team": "platform", "Service": "orders"})

    assert evaluate_platform_policies(spec_a, _NO_CHANGE_PLAN) == evaluate_platform_policies(
        spec_b, _NO_CHANGE_PLAN
    )


def test_no_organization_specific_tag_requirement_exists():
    # A spec with zero tags must not produce any additional finding or
    # different outcome purely because tags like owner/cost-center/team
    # are absent — Phase 1 has no tag-governance policy at all.
    untagged = evaluate_platform_policies(_spec(tags={}), _NO_CHANGE_PLAN)
    tagged = evaluate_platform_policies(
        _spec(tags={"Service": "orders", "Owner": "someone", "CostCenter": "x"}), _NO_CHANGE_PLAN
    )

    assert {f.policy_id for f in untagged.findings} == {f.policy_id for f in tagged.findings}
    assert untagged.overall_status is PolicyStatus.PASS
    assert tagged.overall_status is PolicyStatus.PASS


def test_sse_sqs_without_customer_managed_key_is_not_penalized():
    spec = _spec(encryption=EncryptionSpec(kms_key_id=None))
    finding = _find(evaluate_platform_policies(spec, _NO_CHANGE_PLAN), SQS_ENCRYPTION_REQUIRED)
    assert finding.status is PolicyStatus.PASS


# ---------------------------------------------------------------------------
# Architectural boundary checks
# ---------------------------------------------------------------------------


def test_platform_module_imports_no_forbidden_dependencies():
    import ast

    tree = ast.parse(inspect.getsource(platform))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    forbidden = {"langchain", "langgraph", "boto3", "subprocess", "checkov"}
    assert not (imported_roots & forbidden), imported_roots & forbidden


def test_platform_module_source_never_mentions_raw_plan_json_access():
    source = inspect.getsource(platform)
    # The only Terraform-plan-shaped object this module may touch is the
    # already-analyzed PlanSummary — never a raw `terraform show -json`
    # dict or its characteristic keys.
    for forbidden in ("resource_changes", "show_json", "terraform show"):
        assert forbidden not in source
