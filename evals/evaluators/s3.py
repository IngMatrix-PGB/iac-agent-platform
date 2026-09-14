"""Deterministic evaluators for S3 golden scenarios.

Mirrors `evals.evaluators.sqs` exactly in structure and intent: each
evaluator checks exactly one aspect of system behavior against a
scenario's expected outcome and returns a binary-scored `EvalResult`.
`security_status` uses a fixed, explicitly-constructed clean
`CheckovScanResult` and a typed create-only `PlanSummary` fixture
rather than the real Terraform/Checkov binaries — this suite must stay
fast and runnable anywhere with no external tool dependency; the real
tools are already proven separately by
tests/integration/test_s3_workflow_integration.py and
tests/integration/test_s3_renderer_terraform.py.
"""

from __future__ import annotations

from pydantic import ValidationError

from evals.scenarios.s3_loader import S3Scenario
from iac_agent.domain.evals import EvalResult, EvalStatus
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.resource import ResourceType
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.s3.renderer import S3TerraformCompositionRenderer
from iac_agent.security.checkov import CheckovScanResult
from iac_agent.security.gate import evaluate_security_gate

#: A fixed, explicitly-constructed clean scanner result — never a real
#: Checkov invocation. The specific passed_checks/skipped_checks counts
#: are benign fixture data (matching the real secure-baseline scan
#: shape with the documented Phase 2 skip list applied); only
#: failed_checks=0/findings=() matter to any evaluator here.
_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=13, failed_checks=0, skipped_checks=4, scanner_version="3.3.13"
)

_BUCKET_ADDRESS = "module.bucket.aws_s3_bucket.this"
_VERSIONING_ADDRESS = "module.bucket.aws_s3_bucket_versioning.this"
_ENCRYPTION_ADDRESS = "module.bucket.aws_s3_bucket_server_side_encryption_configuration.this"
_PUBLIC_ACCESS_ADDRESS = "module.bucket.aws_s3_bucket_public_access_block.this"
_POLICY_ADDRESS = "module.bucket.aws_s3_bucket_policy.tls_only"


def _create_only_plan_summary() -> PlanSummary:
    """A typed, create-only PlanSummary fixture — not a real Terraform
    plan. Mirrors exactly what the real renderer + trusted module
    produces for a brand-new bucket (see
    tests/integration/test_s3_renderer_terraform.py), without invoking
    Terraform."""
    addresses = (
        _BUCKET_ADDRESS,
        _VERSIONING_ADDRESS,
        _ENCRYPTION_ADDRESS,
        _PUBLIC_ACCESS_ADDRESS,
        _POLICY_ADDRESS,
    )
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
    scenario: S3Scenario,
) -> tuple[EvalResult, S3ResourceSpec | None]:
    """Check whether contract construction matches the expected valid/invalid outcome.

    Returns the EvalResult plus the constructed spec — the spec is
    `None` whenever there is nothing valid to hand to the downstream
    evaluators, whether because rejection was expected (and happened)
    or because this check itself FAILed/ERRORed.
    """
    try:
        spec = S3ResourceSpec(**scenario.input)
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


def evaluate_field_expectations(scenario: S3Scenario, spec: S3ResourceSpec) -> EvalResult:
    """Compare only the explicitly expected fields — never internal/private
    Pydantic metadata."""
    expected = scenario.expected
    mismatches: list[str] = []

    if spec.name != expected.bucket_name:
        mismatches.append(f"name: expected {expected.bucket_name!r}, got {spec.name!r}")
    if spec.versioning != expected.versioning:
        mismatches.append(f"versioning: expected {expected.versioning!r}, got {spec.versioning!r}")
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
    if spec.block_public_access != expected.block_public_access:
        mismatches.append(
            f"block_public_access: expected {expected.block_public_access!r}, "
            f"got {spec.block_public_access!r}"
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


def evaluate_rendering_determinism(scenario: S3Scenario, spec: S3ResourceSpec) -> EvalResult:
    """Render twice; the same validated spec must always produce byte-identical output."""
    renderer = S3TerraformCompositionRenderer()
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


def evaluate_security_status(scenario: S3Scenario, spec: S3ResourceSpec) -> EvalResult:
    """Check the aggregate SecurityGateResult against the expected status.

    Uses `evaluate_security_gate` directly rather than re-deriving
    BLOCK/WARN/PASS precedence here, so this evaluator can never drift
    from the gate's own logic. Passes `resource_type=ResourceType.S3`
    explicitly (see Batch 16's `security.gate` fix) so the gate checks
    completeness against S3's own required platform-policy IDs, not
    SQS's.
    """
    plan_summary = _create_only_plan_summary()

    try:
        platform_evaluation = evaluate_platform_policies(spec, plan_summary)
        gate_result = evaluate_security_gate(
            platform_evaluation, _CLEAN_CHECKOV_RESULT, resource_type=ResourceType.S3
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
