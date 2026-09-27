"""Deterministic evaluators for ECR golden scenarios.

Each evaluator checks one aspect of behavior. Security uses a fixed
clean Checkov result and a typed create-only plan fixture. This suite
does not invoke Terraform or Checkov.
"""

from __future__ import annotations

from pydantic import ValidationError

from evals.scenarios.ecr_loader import EcrScenario
from iac_agent.domain.evals import EvalResult, EvalStatus
from iac_agent.domain.plan import PlanAction, PlanSummary, ResourceChange
from iac_agent.domain.resource import ResourceType
from iac_agent.policies.platform import evaluate_platform_policies
from iac_agent.providers.aws.ecr.contract import EcrResourceSpec
from iac_agent.providers.aws.ecr.renderer import EcrTerraformCompositionRenderer
from iac_agent.security.checkov import CheckovScanResult
from iac_agent.security.gate import evaluate_security_gate

_CLEAN_CHECKOV_RESULT = CheckovScanResult(
    findings=(), passed_checks=0, failed_checks=0, skipped_checks=0, scanner_version=None
)

_REPOSITORY_ADDRESS = "module.ecr.aws_ecr_repository.this"


def _create_only_plan_summary() -> PlanSummary:
    """A typed create-only plan for one aws_ecr_repository. Not a real plan."""
    change = ResourceChange(
        address=_REPOSITORY_ADDRESS,
        actions=("create",),
        action=PlanAction.CREATE,
        replacement=False,
        destructive=False,
    )
    return PlanSummary(
        resource_changes=(change,),
        resources_to_add=(_REPOSITORY_ADDRESS,),
        resources_to_change=(),
        resources_to_destroy=(),
        destructive_change_detected=False,
    )


def evaluate_contract_validity(
    scenario: EcrScenario,
) -> tuple[EvalResult, EcrResourceSpec | None]:
    """Check whether contract construction matches the expected valid/invalid outcome."""
    try:
        spec = EcrResourceSpec(**scenario.input)
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
    except Exception as exc:  # noqa: BLE001
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


def evaluate_field_expectations(scenario: EcrScenario, spec: EcrResourceSpec) -> EvalResult:
    """Compare the expected contract fields."""
    expected = scenario.expected
    mismatches: list[str] = []

    if spec.name != expected.name:
        mismatches.append(f"name: expected {expected.name!r}, got {spec.name!r}")
    if spec.image_tag_mutability.value != expected.image_tag_mutability:
        mismatches.append(
            f"image_tag_mutability: expected {expected.image_tag_mutability!r}, "
            f"got {spec.image_tag_mutability.value!r}"
        )
    if spec.scan_on_push != expected.scan_on_push:
        mismatches.append(
            f"scan_on_push: expected {expected.scan_on_push!r}, got {spec.scan_on_push!r}"
        )
    if spec.encryption.enabled != expected.encryption_enabled:
        mismatches.append(
            f"encryption.enabled: expected {expected.encryption_enabled!r}, "
            f"got {spec.encryption.enabled!r}"
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


def evaluate_rendering_determinism(scenario: EcrScenario, spec: EcrResourceSpec) -> EvalResult:
    """Render twice; the same validated spec must produce byte-identical output."""
    renderer = EcrTerraformCompositionRenderer()
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

    main_tf = first.files["main.tf"]
    if 'module "ecr"' not in main_tf:
        return EvalResult(
            scenario_id=scenario.id,
            evaluator="rendering_determinism",
            status=EvalStatus.FAIL,
            score=0.0,
            message='rendered main.tf did not contain module "ecr"',
        )
    if "encryption_type" in main_tf or "aws_ecr_repository" in main_tf:
        return EvalResult(
            scenario_id=scenario.id,
            evaluator="rendering_determinism",
            status=EvalStatus.FAIL,
            score=0.0,
            message="root module leaked encryption_type or a raw aws_ecr_repository",
        )

    return EvalResult(
        scenario_id=scenario.id,
        evaluator="rendering_determinism",
        status=EvalStatus.PASS,
        score=1.0,
        message="repeated render was byte-identical",
    )


def evaluate_security_status(scenario: EcrScenario, spec: EcrResourceSpec) -> EvalResult:
    """Check the aggregate gate status, and a named policy when the scenario names one."""
    try:
        platform_evaluation = evaluate_platform_policies(spec, _create_only_plan_summary())
        gate_result = evaluate_security_gate(
            platform_evaluation, _CLEAN_CHECKOV_RESULT, resource_type=ResourceType.ECR
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
    mismatches: list[str] = []
    if actual_status != expected_status:
        mismatches.append(
            f"expected overall_security_status={expected_status!r}, got {actual_status!r}"
        )

    policy_id = scenario.expected.policy_id
    if policy_id is not None:
        matches = [
            finding
            for finding in platform_evaluation.findings
            if finding.policy_id == policy_id
        ]
        if not matches:
            mismatches.append(f"expected policy {policy_id!r} was not evaluated")
        elif matches[0].status.value != expected_status:
            mismatches.append(
                f"policy {policy_id!r}: expected status {expected_status!r}, "
                f"got {matches[0].status.value!r}"
            )

    if mismatches:
        return EvalResult(
            scenario_id=scenario.id,
            evaluator="security_status",
            status=EvalStatus.FAIL,
            score=0.0,
            message="; ".join(mismatches),
        )

    return EvalResult(
        scenario_id=scenario.id,
        evaluator="security_status",
        status=EvalStatus.PASS,
        score=1.0,
        message=f"overall_security_status={actual_status!r} as expected",
    )
