"""Unit tests for the Phase 2 deterministic Lambda platform policies
(Batch 18).

No Terraform, AWS, network, or LLM dependency anywhere in this file.
Mirrors tests/unit/policies/test_dynamodb_platform_policies.py's
structure for the Lambda-specific policies.
"""

from __future__ import annotations

from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.security import PolicyStatus, SecuritySeverity
from iac_agent.policies.platform import (
    LAMBDA_LOG_RETENTION_REQUIRED,
    LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
    LAMBDA_TRACING_RECOMMENDED,
    TF_NO_DESTRUCTIVE_CHANGES,
    evaluate_platform_policies,
)
from iac_agent.providers.aws.lambda_function.contract import (
    LambdaResourceSpec,
    LambdaTracingMode,
)


def _spec(**overrides) -> LambdaResourceSpec:
    defaults = {"name": "orders-processor", "handler": "app.handler"}
    defaults.update(overrides)
    return LambdaResourceSpec(**defaults)


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


_NO_CHANGE_PLAN = _create_only_plan("module.lambda.aws_lambda_function.this")


def _find(evaluation, policy_id):
    return next(f for f in evaluation.findings if f.policy_id == policy_id)


# ---------------------------------------------------------------------------
# Tracing policy
# ---------------------------------------------------------------------------


def test_tracing_active_passes():
    finding = _find(
        evaluate_platform_policies(_spec(tracing_mode=LambdaTracingMode.ACTIVE), _NO_CHANGE_PLAN),
        LAMBDA_TRACING_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.PASS


def test_tracing_pass_through_warns():
    finding = _find(
        evaluate_platform_policies(
            _spec(tracing_mode=LambdaTracingMode.PASS_THROUGH), _NO_CHANGE_PLAN
        ),
        LAMBDA_TRACING_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.WARN


def test_tracing_warning_is_non_blocking():
    finding = _find(
        evaluate_platform_policies(
            _spec(tracing_mode=LambdaTracingMode.PASS_THROUGH), _NO_CHANGE_PLAN
        ),
        LAMBDA_TRACING_RECOMMENDED,
    )
    assert finding.blocking is False


def test_tracing_warning_severity_is_medium():
    finding = _find(
        evaluate_platform_policies(
            _spec(tracing_mode=LambdaTracingMode.PASS_THROUGH), _NO_CHANGE_PLAN
        ),
        LAMBDA_TRACING_RECOMMENDED,
    )
    assert finding.severity is SecuritySeverity.MEDIUM


# ---------------------------------------------------------------------------
# Reserved concurrency policy
# ---------------------------------------------------------------------------


def test_reserved_concurrency_set_passes():
    finding = _find(
        evaluate_platform_policies(_spec(reserved_concurrency=5), _NO_CHANGE_PLAN),
        LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.PASS


def test_reserved_concurrency_zero_passes():
    """0 is an explicit configuration (fully throttled), not "unset"."""
    finding = _find(
        evaluate_platform_policies(_spec(reserved_concurrency=0), _NO_CHANGE_PLAN),
        LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.PASS


def test_reserved_concurrency_omitted_warns():
    finding = _find(
        evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN),
        LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
    )
    assert finding.status is PolicyStatus.WARN


def test_reserved_concurrency_warning_is_non_blocking():
    finding = _find(
        evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN),
        LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
    )
    assert finding.blocking is False


# ---------------------------------------------------------------------------
# Log retention policy (evidence-only)
# ---------------------------------------------------------------------------


def test_log_retention_always_passes():
    finding = _find(
        evaluate_platform_policies(_spec(log_retention_days=30), _NO_CHANGE_PLAN),
        LAMBDA_LOG_RETENTION_REQUIRED,
    )
    assert finding.status is PolicyStatus.PASS


def test_log_retention_message_states_the_configured_value():
    finding = _find(
        evaluate_platform_policies(_spec(log_retention_days=90), _NO_CHANGE_PLAN),
        LAMBDA_LOG_RETENTION_REQUIRED,
    )
    assert "90" in finding.message


# ---------------------------------------------------------------------------
# Shared destructive-change policy (proves it applies to Lambda too)
# ---------------------------------------------------------------------------


def test_no_destructive_changes_passes():
    finding = _find(evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN), TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.PASS


def test_delete_action_blocks():
    plan = _destructive_plan(
        action=PlanAction.DELETE, addresses=("module.lambda.aws_lambda_function.old",)
    )
    finding = _find(evaluate_platform_policies(_spec(), plan), TF_NO_DESTRUCTIVE_CHANGES)
    assert finding.status is PolicyStatus.BLOCK


# ---------------------------------------------------------------------------
# Cross-policy scenarios
# ---------------------------------------------------------------------------


def test_secure_function_create_only_gives_four_pass_findings():
    evaluation = evaluate_platform_policies(_spec(reserved_concurrency=5), _NO_CHANGE_PLAN)

    assert len(evaluation.findings) == 4
    assert all(f.status is PolicyStatus.PASS for f in evaluation.findings)
    assert evaluation.overall_status is PolicyStatus.PASS


def test_tracing_pass_through_gives_overall_warn():
    evaluation = evaluate_platform_policies(
        _spec(tracing_mode=LambdaTracingMode.PASS_THROUGH, reserved_concurrency=5),
        _NO_CHANGE_PLAN,
    )
    assert evaluation.overall_status is PolicyStatus.WARN


def test_reserved_concurrency_omitted_gives_overall_warn():
    evaluation = evaluate_platform_policies(_spec(), _NO_CHANGE_PLAN)
    assert evaluation.overall_status is PolicyStatus.WARN


def test_destructive_plan_gives_overall_block():
    plan = _destructive_plan(
        action=PlanAction.REPLACE, addresses=("module.lambda.aws_lambda_function.this",)
    )
    evaluation = evaluate_platform_policies(_spec(), plan)
    assert evaluation.overall_status is PolicyStatus.BLOCK


def test_warn_and_destructive_block_wins_over_warn():
    plan = _destructive_plan(
        action=PlanAction.DELETE, addresses=("module.lambda.aws_lambda_function.old",)
    )
    evaluation = evaluate_platform_policies(_spec(), plan)

    assert evaluation.overall_status is PolicyStatus.BLOCK
    assert _find(evaluation, LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED).status is PolicyStatus.WARN


def test_same_logical_inputs_produce_equal_evaluation():
    spec_a = _spec(tags={"Service": "orders", "Team": "data"})
    spec_b = _spec(tags={"Team": "data", "Service": "orders"})

    assert evaluate_platform_policies(spec_a, _NO_CHANGE_PLAN) == evaluate_platform_policies(
        spec_b, _NO_CHANGE_PLAN
    )
