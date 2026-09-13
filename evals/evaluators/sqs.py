"""Deterministic evaluators for SQS golden scenarios.

Each evaluator checks exactly one aspect of system behavior against a
scenario's expected outcome and returns a binary-scored `EvalResult`
(1.0 = matched, 0.0 = did not). `security_status` uses a fixed,
explicitly-constructed clean `CheckovScanResult` and a typed
create-only `PlanSummary` fixture rather than the real Terraform/
Checkov binaries — this suite must stay fast and runnable anywhere
with no external tool dependency; the real tools are already proven
separately by the Batch 4-9 integration tests.
"""

from __future__ import annotations

from pydantic import ValidationError

from evals.scenarios.loader import Scenario
from iac_agent.domain.evals import EvalResult, EvalStatus
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec
from iac_agent.providers.aws.sqs.renderer import TerraformCompositionRenderer
from iac_agent.security.checkov import CheckovScanResult
from iac_agent.security.gate import evaluate_security_gate

#: A fixed, explicitly-constructed clean scanner result — never a real
#: Checkov invocation. The specific passed_checks count is benign fixture
#: data; only failed_checks=0/findings=() matter to any evaluator here.
_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(),
    passed_checks=5,
    failed_checks=0,
    skipped_checks=0,
    scanner_version="3.3.13",
)

_PRIMARY_QUEUE_ADDRESS = "module.queue.aws_sqs_queue.this"
_DLQ_ADDRESS = "module.queue.aws_sqs_queue.dlq[0]"


def _create_only_plan_summary(*, dlq_enabled: bool) -> PlanSummary:
    """A typed, create-only PlanSummary fixture — not a real Terraform
    plan. Mirrors exactly what the real renderer + trusted module would
    produce for a brand-new queue (see the Batch 6/9 integration
    evidence), without invoking Terraform."""
    addresses = [_PRIMARY_QUEUE_ADDRESS]
    if dlq_enabled:
        addresses.append(_DLQ_ADDRESS)

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
        resources_to_add=tuple(sorted(addresses)),
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def evaluate_contract_validity(
    scenario: Scenario,
) -> tuple[EvalResult, SQSResourceSpec | None]:
    """Check whether contract construction matches the expected valid/invalid outcome.

    Returns the EvalResult plus the constructed spec — the spec is
    `None` whenever there is nothing valid to hand to the downstream
    evaluators, whether because rejection was expected (and happened)
    or because this check itself FAILed/ERRORed.
    """
    try:
        spec = SQSResourceSpec(**scenario.input)
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


def evaluate_field_expectations(scenario: Scenario, spec: SQSResourceSpec) -> EvalResult:
    """Compare only the explicitly expected fields — never internal/private
    Pydantic metadata."""
    expected = scenario.expected
    mismatches: list[str] = []

    if spec.name != expected.queue_name:
        mismatches.append(f"name: expected {expected.queue_name!r}, got {spec.name!r}")
    if spec.fifo != expected.fifo:
        mismatches.append(f"fifo: expected {expected.fifo!r}, got {spec.fifo!r}")
    if spec.dlq.enabled != expected.dlq_enabled:
        mismatches.append(
            f"dlq.enabled: expected {expected.dlq_enabled!r}, got {spec.dlq.enabled!r}"
        )
    if spec.encryption.enabled != expected.encryption_enabled:
        mismatches.append(
            f"encryption.enabled: expected {expected.encryption_enabled!r}, "
            f"got {spec.encryption.enabled!r}"
        )
    if spec.encryption.kms_key_id != expected.kms_key_id:
        mismatches.append(
            f"encryption.kms_key_id: expected {expected.kms_key_id!r}, "
            f"got {spec.encryption.kms_key_id!r}"
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


def evaluate_rendering_determinism(scenario: Scenario, spec: SQSResourceSpec) -> EvalResult:
    """Render twice; the same validated spec must always produce byte-identical output."""
    renderer = TerraformCompositionRenderer()
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


def evaluate_security_status(scenario: Scenario, spec: SQSResourceSpec) -> EvalResult:
    """Check the aggregate SecurityGateResult against the expected status.

    Uses `evaluate_security_gate` directly rather than re-deriving
    BLOCK/WARN/PASS precedence here, so this evaluator can never drift
    from the gate's own logic.
    """
    plan_summary = _create_only_plan_summary(dlq_enabled=spec.dlq.enabled)

    try:
        platform_evaluation = evaluate_platform_policies(spec, plan_summary)
        gate_result = evaluate_security_gate(platform_evaluation, _CLEAN_CHECKOV_RESULT)
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
