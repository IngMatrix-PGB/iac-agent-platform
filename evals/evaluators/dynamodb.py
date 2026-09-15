"""Deterministic evaluators for DynamoDB golden scenarios (Batch 17).

Mirrors `evals.evaluators.s3` exactly in structure and intent: each
evaluator checks exactly one aspect of system behavior against a
scenario's expected outcome and returns a binary-scored `EvalResult`.
`security_status` uses a fixed, explicitly-constructed clean
`CheckovScanResult` and a typed create-only `PlanSummary` fixture
rather than the real Terraform/Checkov binaries — this suite must stay
fast and runnable anywhere with no external tool dependency; the real
tools are already proven separately by
tests/integration/test_dynamodb_workflow_integration.py and
tests/integration/test_dynamodb_renderer_terraform.py.
"""

from __future__ import annotations

from pydantic import ValidationError

from evals.scenarios.dynamodb_loader import DynamoDBScenario
from iac_agent.domain.evals import EvalResult, EvalStatus
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.resource import ResourceType
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.providers.aws.dynamodb.contract import DynamoDBResourceSpec
from iac_agent.providers.aws.dynamodb.renderer import DynamoDBTerraformCompositionRenderer
from iac_agent.security.checkov import CheckovScanResult
from iac_agent.security.gate import evaluate_security_gate

#: A fixed, explicitly-constructed clean scanner result — never a real
#: Checkov invocation. Matches the real secure-baseline scan shape
#: (resource_count=1, passed=3, failed=0) observed in Batch 17's real
#: Checkov run with the approved CKV_AWS_119 skip applied; only
#: failed_checks=0/findings=() matter to any evaluator here.
_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=3, failed_checks=0, skipped_checks=0, scanner_version="3.3.13"
)

_TABLE_ADDRESS = "module.dynamodb.aws_dynamodb_table.this"


def _create_only_plan_summary() -> PlanSummary:
    """A typed, create-only PlanSummary fixture — not a real Terraform
    plan. Mirrors exactly what the real renderer + trusted module
    produces for a brand-new table (see
    tests/integration/test_dynamodb_renderer_terraform.py), without
    invoking Terraform."""
    change = ResourceChange(
        address=_TABLE_ADDRESS,
        actions=("create",),
        action=PlanAction.CREATE,
        replacement=False,
        destructive=False,
    )
    return PlanSummary(
        resource_changes=(change,),
        resources_to_add=(_TABLE_ADDRESS,),
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def evaluate_contract_validity(
    scenario: DynamoDBScenario,
) -> tuple[EvalResult, DynamoDBResourceSpec | None]:
    """Check whether contract construction matches the expected valid/invalid outcome.

    Returns the EvalResult plus the constructed spec — the spec is
    `None` whenever there is nothing valid to hand to the downstream
    evaluators, whether because rejection was expected (and happened)
    or because this check itself FAILed/ERRORed.
    """
    try:
        spec = DynamoDBResourceSpec(**scenario.input)
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


def evaluate_field_expectations(
    scenario: DynamoDBScenario, spec: DynamoDBResourceSpec
) -> EvalResult:
    """Compare only the explicitly expected fields — never internal/private
    Pydantic metadata."""
    expected = scenario.expected
    mismatches: list[str] = []

    if spec.name != expected.table_name:
        mismatches.append(f"name: expected {expected.table_name!r}, got {spec.name!r}")
    if spec.partition_key.name != expected.partition_key_name:
        mismatches.append(
            f"partition_key.name: expected {expected.partition_key_name!r}, "
            f"got {spec.partition_key.name!r}"
        )
    if spec.partition_key.type.value != expected.partition_key_type:
        mismatches.append(
            f"partition_key.type: expected {expected.partition_key_type!r}, "
            f"got {spec.partition_key.type.value!r}"
        )

    actual_sort_key_name = spec.sort_key.name if spec.sort_key is not None else None
    actual_sort_key_type = spec.sort_key.type.value if spec.sort_key is not None else None
    if actual_sort_key_name != expected.sort_key_name:
        mismatches.append(
            f"sort_key.name: expected {expected.sort_key_name!r}, got {actual_sort_key_name!r}"
        )
    if actual_sort_key_type != expected.sort_key_type:
        mismatches.append(
            f"sort_key.type: expected {expected.sort_key_type!r}, got {actual_sort_key_type!r}"
        )

    if spec.point_in_time_recovery != expected.point_in_time_recovery:
        mismatches.append(
            f"point_in_time_recovery: expected {expected.point_in_time_recovery!r}, "
            f"got {spec.point_in_time_recovery!r}"
        )
    if spec.deletion_protection != expected.deletion_protection:
        mismatches.append(
            f"deletion_protection: expected {expected.deletion_protection!r}, "
            f"got {spec.deletion_protection!r}"
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
    scenario: DynamoDBScenario, spec: DynamoDBResourceSpec
) -> EvalResult:
    """Render twice; the same validated spec must always produce byte-identical output."""
    renderer = DynamoDBTerraformCompositionRenderer()
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


def evaluate_security_status(scenario: DynamoDBScenario, spec: DynamoDBResourceSpec) -> EvalResult:
    """Check the aggregate SecurityGateResult against the expected status.

    Uses `evaluate_security_gate` directly rather than re-deriving
    BLOCK/WARN/PASS precedence here, so this evaluator can never drift
    from the gate's own logic. Passes `resource_type=ResourceType.DYNAMODB`
    explicitly so the gate checks completeness against DynamoDB's own
    required platform-policy IDs, not SQS's.
    """
    plan_summary = _create_only_plan_summary()

    try:
        platform_evaluation = evaluate_platform_policies(spec, plan_summary)
        gate_result = evaluate_security_gate(
            platform_evaluation, _CLEAN_CHECKOV_RESULT, resource_type=ResourceType.DYNAMODB
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
