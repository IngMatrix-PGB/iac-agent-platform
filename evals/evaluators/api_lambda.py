"""Deterministic evaluators for api_lambda golden scenarios (Batch 20).

Mirrors `evals.evaluators.serverless_worker` exactly in structure and
intent: each evaluator checks exactly one aspect of system behavior
against a scenario's expected outcome and returns a binary-scored
`EvalResult`. `security_status` uses a fixed, explicitly-constructed
clean `CheckovScanResult` and a typed create-only `PlanSummary` fixture
rather than the real Terraform/Checkov binaries — this suite must stay
fast and runnable anywhere with no external tool dependency; the real
tools are already proven separately by
tests/integration/test_api_lambda_workflow_integration.py and
tests/integration/test_api_lambda_renderer_terraform.py.
"""

from __future__ import annotations

from pydantic import ValidationError

from evals.scenarios.api_lambda_loader import ApiLambdaScenario
from iac_agent.compositions.api_lambda.contract import ApiLambdaSpec
from iac_agent.compositions.api_lambda.renderer import (
    ApiLambdaModuleSources,
    ApiLambdaTerraformRenderer,
)
from iac_agent.compositions.resource import composition_type_of
from iac_agent.domain.evals import EvalResult, EvalStatus
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.policies.composition import (
    REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE,
    evaluate_composition_policies,
)
from iac_agent.security.checkov import CheckovScanResult
from iac_agent.security.gate import evaluate_security_gate

#: A fixed, explicitly-constructed clean scanner result — never a real
#: Checkov invocation. Matches the real secure-baseline scan shape
#: (resource_count=9, passed=41, failed=0, skipped=7) observed in
#: Batch 20's real Checkov run with the seven approved skips applied
#: (see `iac_agent.security.composition_checkov_profiles`); only
#: failed_checks=0/findings=() matter to any evaluator here.
_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=41, failed_checks=0, skipped_checks=7, scanner_version="3.3.13"
)

_MODULE_SOURCES = ApiLambdaModuleSources(
    api="../../terraform/modules/api_gateway",
    function="../../terraform/modules/lambda",
)

_RELATIONSHIP_ADDRESSES = (
    "module.api.aws_apigatewayv2_api.this",
    "module.api.aws_apigatewayv2_stage.default",
    "module.function.aws_cloudwatch_log_group.this",
    "module.function.aws_iam_role.this",
    "module.function.aws_iam_role_policy.logs",
    "module.function.aws_lambda_function.this",
    "aws_apigatewayv2_integration.lambda",
    "aws_apigatewayv2_route.this",
    "aws_lambda_permission.api_gateway",
)


def _create_only_plan_summary() -> PlanSummary:
    """A typed, create-only PlanSummary fixture — not a real Terraform
    plan. Mirrors exactly what the real renderer + trusted modules
    produce for a brand-new composition (see
    tests/integration/test_api_lambda_renderer_terraform.py: nine
    resources, zero changes, zero destroys), without invoking
    Terraform."""
    changes = tuple(
        ResourceChange(
            address=address,
            actions=("create",),
            action=PlanAction.CREATE,
            replacement=False,
            destructive=False,
        )
        for address in _RELATIONSHIP_ADDRESSES
    )
    return PlanSummary(
        resource_changes=changes,
        resources_to_add=_RELATIONSHIP_ADDRESSES,
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def evaluate_contract_validity(
    scenario: ApiLambdaScenario,
) -> tuple[EvalResult, ApiLambdaSpec | None]:
    """Check whether contract construction matches the expected valid/invalid outcome."""
    try:
        spec = ApiLambdaSpec(**scenario.input)
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


def evaluate_field_expectations(scenario: ApiLambdaScenario, spec: ApiLambdaSpec) -> EvalResult:
    """Compare only the explicitly expected fields — never internal/private
    Pydantic metadata."""
    expected = scenario.expected
    mismatches: list[str] = []

    if spec.name != expected.name:
        mismatches.append(f"name: expected {expected.name!r}, got {spec.name!r}")
    if spec.api.name != expected.api_name:
        mismatches.append(f"api.name: expected {expected.api_name!r}, got {spec.api.name!r}")
    if spec.function.name != expected.function_name:
        mismatches.append(
            f"function.name: expected {expected.function_name!r}, got {spec.function.name!r}"
        )
    if spec.route.route_key != expected.route_key:
        mismatches.append(
            f"route.route_key: expected {expected.route_key!r}, got {spec.route.route_key!r}"
        )
    architecture_mismatch = (
        expected.architecture is not None
        and spec.function.architecture.value != expected.architecture
    )
    if architecture_mismatch:
        mismatches.append(
            f"function.architecture: expected {expected.architecture!r}, "
            f"got {spec.function.architecture.value!r}"
        )
    tracing_mismatch = (
        expected.tracing_mode is not None
        and spec.function.tracing_mode.value != expected.tracing_mode
    )
    if tracing_mismatch:
        mismatches.append(
            f"function.tracing_mode: expected {expected.tracing_mode!r}, "
            f"got {spec.function.tracing_mode.value!r}"
        )
    if (
        expected.reserved_concurrency is not None
        and spec.function.reserved_concurrency != expected.reserved_concurrency
    ):
        mismatches.append(
            f"function.reserved_concurrency: expected {expected.reserved_concurrency!r}, "
            f"got {spec.function.reserved_concurrency!r}"
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


def evaluate_rendering_determinism(scenario: ApiLambdaScenario, spec: ApiLambdaSpec) -> EvalResult:
    """Render twice; the same validated spec must always produce byte-identical output."""
    renderer = ApiLambdaTerraformRenderer()
    try:
        first = renderer.render(spec, module_sources=_MODULE_SOURCES)
        second = renderer.render(spec, module_sources=_MODULE_SOURCES)
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


def evaluate_security_status(scenario: ApiLambdaScenario, spec: ApiLambdaSpec) -> EvalResult:
    """Check the aggregate SecurityGateResult against the expected status.

    Uses `evaluate_security_gate` directly (via its `required_policy_ids`
    parameter, keyed by this composition's own `CompositionType`) rather
    than re-deriving BLOCK/WARN/PASS precedence here, so this evaluator
    can never drift from the gate's own logic.
    """
    plan_summary = _create_only_plan_summary()

    try:
        platform_evaluation = evaluate_composition_policies(spec, plan_summary)
        composition_type = composition_type_of(spec)
        gate_result = evaluate_security_gate(
            platform_evaluation,
            _CLEAN_CHECKOV_RESULT,
            required_policy_ids=REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE[
                composition_type
            ],
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
