"""Deterministic evaluators for Lambda golden scenarios (Batch 18).

Mirrors `evals.evaluators.dynamodb` exactly in structure and intent:
each evaluator checks exactly one aspect of system behavior against a
scenario's expected outcome and returns a binary-scored `EvalResult`.
`security_status` uses a fixed, explicitly-constructed clean
`CheckovScanResult` and a typed create-only `PlanSummary` fixture
rather than the real Terraform/Checkov binaries — this suite must stay
fast and runnable anywhere with no external tool dependency; the real
tools are already proven separately by
tests/integration/test_lambda_workflow_integration.py and
tests/integration/test_lambda_renderer_terraform.py.
"""

from __future__ import annotations

from pydantic import ValidationError

from evals.scenarios.lambda_loader import LambdaScenario
from iac_agent.domain.evals import EvalResult, EvalStatus
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.resource import ResourceType
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.providers.aws.lambda_function.contract import LambdaResourceSpec
from iac_agent.providers.aws.lambda_function.renderer import LambdaTerraformCompositionRenderer
from iac_agent.security.checkov import CheckovScanResult
from iac_agent.security.gate import evaluate_security_gate

#: A fixed, explicitly-constructed clean scanner result — never a real
#: Checkov invocation. Matches the real secure-baseline scan shape
#: (resource_count=4, passed=36, failed=0, skipped=5) observed in Batch
#: 18's real Checkov run with the five approved skips applied (see
#: `iac_agent.security.checkov_profiles`); only failed_checks=0/
#: findings=() matter to any evaluator here.
_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=36, failed_checks=0, skipped_checks=5, scanner_version="3.3.13"
)

_LOG_GROUP_ADDRESS = "module.lambda.aws_cloudwatch_log_group.this"
_ROLE_ADDRESS = "module.lambda.aws_iam_role.this"
_ROLE_POLICY_ADDRESS = "module.lambda.aws_iam_role_policy.logs"
_FUNCTION_ADDRESS = "module.lambda.aws_lambda_function.this"


def _create_only_plan_summary() -> PlanSummary:
    """A typed, create-only PlanSummary fixture — not a real Terraform
    plan. Mirrors exactly what the real renderer + trusted module
    produces for a brand-new function (see
    tests/integration/test_lambda_renderer_terraform.py: log group, IAM
    role, inline IAM role policy, Lambda function — four resources,
    zero changes, zero destroys), without invoking Terraform."""
    addresses = (_LOG_GROUP_ADDRESS, _ROLE_ADDRESS, _ROLE_POLICY_ADDRESS, _FUNCTION_ADDRESS)
    changes = tuple(
        ResourceChange(
            address=address,
            actions=("create",),
            action=PlanAction.CREATE,
            replacement=False,
            destructive=False,
        )
        for address in addresses
    )
    return PlanSummary(
        resource_changes=changes,
        resources_to_add=addresses,
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def evaluate_contract_validity(
    scenario: LambdaScenario,
) -> tuple[EvalResult, LambdaResourceSpec | None]:
    """Check whether contract construction matches the expected valid/invalid outcome.

    Returns the EvalResult plus the constructed spec — the spec is
    `None` whenever there is nothing valid to hand to the downstream
    evaluators, whether because rejection was expected (and happened)
    or because this check itself FAILed/ERRORed.
    """
    try:
        spec = LambdaResourceSpec(**scenario.input)
    except ValidationError as exc:
        if scenario.expected.valid:
            return (
                EvalResult(
                    scenario_id=scenario.id,
                    evaluator="contract_validity",
                    status=EvalStatus.FAIL,
                    score=0.0,
                    message=(
                        f"expected valid construction but it was rejected: "
                        f"{exc.error_count()} error(s)"
                    ),
                ),
                None,
            )
        return (
            EvalResult(
                scenario_id=scenario.id,
                evaluator="contract_validity",
                status=EvalStatus.PASS,
                score=1.0,
                message="construction was rejected as expected",
            ),
            None,
        )
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any other
        # exception is an evaluator-level ERROR, never a passing/failing
        # product-behavior signal.
        return (
            EvalResult(
                scenario_id=scenario.id,
                evaluator="contract_validity",
                status=EvalStatus.ERROR,
                score=0.0,
                message=f"unexpected exception during construction: {type(exc).__name__}",
            ),
            None,
        )

    if not scenario.expected.valid:
        return (
            EvalResult(
                scenario_id=scenario.id,
                evaluator="contract_validity",
                status=EvalStatus.FAIL,
                score=0.0,
                message="expected construction to be rejected but it succeeded",
            ),
            None,
        )

    return (
        EvalResult(
            scenario_id=scenario.id,
            evaluator="contract_validity",
            status=EvalStatus.PASS,
            score=1.0,
            message="construction succeeded as expected",
        ),
        spec,
    )


def evaluate_field_expectations(scenario: LambdaScenario, spec: LambdaResourceSpec) -> EvalResult:
    """Compare only the explicitly expected fields — never internal/private
    Pydantic metadata."""
    expected = scenario.expected
    mismatches: list[str] = []

    if spec.name != expected.function_name:
        mismatches.append(f"name: expected {expected.function_name!r}, got {spec.name!r}")
    if spec.handler != expected.handler:
        mismatches.append(f"handler: expected {expected.handler!r}, got {spec.handler!r}")
    if spec.architecture.value != expected.architecture:
        mismatches.append(
            f"architecture: expected {expected.architecture!r}, got {spec.architecture.value!r}"
        )
    if spec.memory_size_mb != expected.memory_size_mb:
        mismatches.append(
            f"memory_size_mb: expected {expected.memory_size_mb!r}, got {spec.memory_size_mb!r}"
        )
    if spec.timeout_seconds != expected.timeout_seconds:
        mismatches.append(
            f"timeout_seconds: expected {expected.timeout_seconds!r}, got {spec.timeout_seconds!r}"
        )
    if spec.reserved_concurrency != expected.reserved_concurrency:
        mismatches.append(
            f"reserved_concurrency: expected {expected.reserved_concurrency!r}, "
            f"got {spec.reserved_concurrency!r}"
        )
    if spec.tracing_mode.value != expected.tracing_mode:
        mismatches.append(
            f"tracing_mode: expected {expected.tracing_mode!r}, got {spec.tracing_mode.value!r}"
        )

    if mismatches:
        return EvalResult(
            scenario_id=scenario.id,
            evaluator="field_expectations",
            status=EvalStatus.FAIL,
            score=0.0,
            message="; ".join(mismatches),
        )
    return EvalResult(
        scenario_id=scenario.id,
        evaluator="field_expectations",
        status=EvalStatus.PASS,
        score=1.0,
        message="all expected fields matched",
    )


def evaluate_rendering_determinism(
    scenario: LambdaScenario, spec: LambdaResourceSpec
) -> EvalResult:
    """Render twice; the same validated spec must always produce byte-identical output."""
    renderer = LambdaTerraformCompositionRenderer()
    try:
        first = renderer.render(spec)
        second = renderer.render(spec)
    except Exception as exc:  # noqa: BLE001
        return EvalResult(
            scenario_id=scenario.id,
            evaluator="rendering_determinism",
            status=EvalStatus.ERROR,
            score=0.0,
            message=f"renderer raised: {type(exc).__name__}",
        )

    if first.files != second.files:
        return EvalResult(
            scenario_id=scenario.id,
            evaluator="rendering_determinism",
            status=EvalStatus.FAIL,
            score=0.0,
            message="repeated render of the same spec produced different output",
        )

    return EvalResult(
        scenario_id=scenario.id,
        evaluator="rendering_determinism",
        status=EvalStatus.PASS,
        score=1.0,
        message="repeated render was byte-identical",
    )


def evaluate_security_status(scenario: LambdaScenario, spec: LambdaResourceSpec) -> EvalResult:
    """Check the aggregate SecurityGateResult against the expected status.

    Uses `evaluate_security_gate` directly rather than re-deriving
    BLOCK/WARN/PASS precedence here, so this evaluator can never drift
    from the gate's own logic. Passes `resource_type=ResourceType.LAMBDA`
    explicitly so the gate checks completeness against Lambda's own
    required platform-policy IDs, not DynamoDB's.
    """
    plan_summary = _create_only_plan_summary()

    try:
        platform_evaluation = evaluate_platform_policies(spec, plan_summary)
        gate_result = evaluate_security_gate(
            platform_evaluation, _CLEAN_CHECKOV_RESULT, resource_type=ResourceType.LAMBDA
        )
    except Exception as exc:  # noqa: BLE001
        return EvalResult(
            scenario_id=scenario.id,
            evaluator="security_status",
            status=EvalStatus.ERROR,
            score=0.0,
            message=f"security evaluation raised: {type(exc).__name__}",
        )

    expected_status = scenario.expected.overall_security_status
    actual_status = gate_result.overall_status.value

    if actual_status != expected_status:
        return EvalResult(
            scenario_id=scenario.id,
            evaluator="security_status",
            status=EvalStatus.FAIL,
            score=0.0,
            message=f"expected overall_security_status={expected_status!r}, got {actual_status!r}",
        )

    return EvalResult(
        scenario_id=scenario.id,
        evaluator="security_status",
        status=EvalStatus.PASS,
        score=1.0,
        message=f"overall_security_status={actual_status!r} as expected",
    )
