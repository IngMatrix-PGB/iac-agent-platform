"""Deterministic evaluators for serverless-worker golden scenarios
(Batch 19).

Mirrors `evals.evaluators.lambda_function` exactly in structure and
intent: each evaluator checks exactly one aspect of system behavior
against a scenario's expected outcome and returns a binary-scored
`EvalResult`. `security_status` uses a fixed, explicitly-constructed
clean `CheckovScanResult` and a typed create-only `PlanSummary` fixture
rather than the real Terraform/Checkov binaries — this suite must stay
fast and runnable anywhere with no external tool dependency; the real
tools are already proven separately by
tests/integration/test_serverless_worker_workflow_integration.py and
tests/integration/test_serverless_worker_renderer_terraform.py.
"""

from __future__ import annotations

from pydantic import ValidationError

from evals.scenarios.serverless_worker_loader import ServerlessWorkerScenario
from iac_agent.compositions.resource import composition_type_of
from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.compositions.serverless_worker.renderer import (
    ServerlessWorkerModuleSources,
    ServerlessWorkerTerraformRenderer,
)
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
#: (resource_count=10, passed=69, failed=0, skipped=6) observed in
#: Batch 19's real Checkov run with the six approved skips applied (see
#: `iac_agent.security.composition_checkov_profiles`); only
#: failed_checks=0/findings=() matter to any evaluator here.
_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=69, failed_checks=0, skipped_checks=6, scanner_version="3.3.13"
)

_MODULE_SOURCES = ServerlessWorkerModuleSources(
    queue="../../terraform/modules/sqs",
    function="../../terraform/modules/lambda",
    table="../../terraform/modules/dynamodb",
)

_RELATIONSHIP_ADDRESSES = (
    "module.queue.aws_sqs_queue.dlq[0]",
    "module.queue.aws_sqs_queue.this",
    "module.function.aws_cloudwatch_log_group.this",
    "module.function.aws_iam_role.this",
    "module.function.aws_iam_role_policy.logs",
    "module.function.aws_lambda_function.this",
    "module.table.aws_dynamodb_table.this",
    "aws_lambda_event_source_mapping.queue_to_function",
    "aws_iam_role_policy.sqs_consumer",
    "aws_iam_role_policy.dynamodb_write",
)


def _create_only_plan_summary() -> PlanSummary:
    """A typed, create-only PlanSummary fixture — not a real Terraform
    plan. Mirrors exactly what the real renderer + trusted modules
    produce for a brand-new composition (see
    tests/integration/test_serverless_worker_renderer_terraform.py: ten
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
    scenario: ServerlessWorkerScenario,
) -> tuple[EvalResult, ServerlessWorkerSpec | None]:
    """Check whether contract construction matches the expected valid/invalid outcome.

    Returns the EvalResult plus the constructed spec — the spec is
    `None` whenever there is nothing valid to hand to the downstream
    evaluators, whether because rejection was expected (and happened)
    or because this check itself FAILed/ERRORed.
    """
    try:
        spec = ServerlessWorkerSpec(**scenario.input)
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
    scenario: ServerlessWorkerScenario, spec: ServerlessWorkerSpec
) -> EvalResult:
    """Compare only the explicitly expected fields — never internal/private
    Pydantic metadata. Fields left unset in the dataset's `expected`
    block (architecture/tracing_mode/reserved_concurrency/
    point_in_time_recovery/deletion_protection are all optional) are
    simply not checked for that scenario."""
    expected = scenario.expected
    mismatches: list[str] = []

    if spec.name != expected.name:
        mismatches.append(f"name: expected {expected.name!r}, got {spec.name!r}")
    if spec.queue.name != expected.queue_name:
        mismatches.append(f"queue.name: expected {expected.queue_name!r}, got {spec.queue.name!r}")
    if spec.function.name != expected.function_name:
        mismatches.append(
            f"function.name: expected {expected.function_name!r}, got {spec.function.name!r}"
        )
    if spec.table.name != expected.table_name:
        mismatches.append(f"table.name: expected {expected.table_name!r}, got {spec.table.name!r}")
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
    if (
        expected.point_in_time_recovery is not None
        and spec.table.point_in_time_recovery != expected.point_in_time_recovery
    ):
        mismatches.append(
            f"table.point_in_time_recovery: expected {expected.point_in_time_recovery!r}, "
            f"got {spec.table.point_in_time_recovery!r}"
        )
    if (
        expected.deletion_protection is not None
        and spec.table.deletion_protection != expected.deletion_protection
    ):
        mismatches.append(
            f"table.deletion_protection: expected {expected.deletion_protection!r}, "
            f"got {spec.table.deletion_protection!r}"
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
    scenario: ServerlessWorkerScenario, spec: ServerlessWorkerSpec
) -> EvalResult:
    """Render twice; the same validated spec must always produce byte-identical output."""
    renderer = ServerlessWorkerTerraformRenderer()
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


def evaluate_security_status(
    scenario: ServerlessWorkerScenario, spec: ServerlessWorkerSpec
) -> EvalResult:
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
