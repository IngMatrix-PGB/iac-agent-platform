"""The deterministic security gate — an aggregator, not another analyzer.

`evaluate_security_gate` combines the two independent security outputs
already produced elsewhere:

    PolicyEvaluation      (iac_agent.policies.platform)
    CheckovScanResult     (iac_agent.security.checkov)

into one `SecurityGateResult`. It does not re-inspect `PlanSummary`,
raw Terraform plan JSON, `SQSResourceSpec`, or Terraform files — those
are already fully consumed and interpreted by
`evaluate_platform_policies` and `CheckovAdapter.scan` respectively.
Re-inspecting them here would duplicate policy logic and create a
second source of truth.

This module performs no subprocess execution, no filesystem access, no
network access, and imports nothing from LangChain/LangGraph. A
`CheckovError` raised by the scanner adapter is never caught here — a
failed/unavailable/timed-out scan is not converted into a passing (or
any) `SecurityGateResult`; it simply prevents one from being produced,
exactly as it already prevents a `CheckovScanResult` from existing.
"""

from __future__ import annotations

from iac_agent.domain.resource import ResourceType
from iac_agent.domain.security import (
    FindingSource,
    PolicyEvaluation,
    SecurityFinding,
    SecurityGateResult,
)
from iac_agent.policies.platform import REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE
from iac_agent.security.checkov import CheckovScanResult


class SecurityGateError(Exception):
    """Raised when the aggregate security state is impossible or
    incomplete to evaluate.

    This is never raised for a legitimate BLOCK/WARN policy outcome —
    only for structural integrity problems: a required platform policy
    finding missing, duplicated, or carrying the wrong source; or a
    Checkov result whose own counts are internally inconsistent.
    Messages reference policy IDs and counts only — never raw
    Terraform/Checkov JSON, full object reprs, or filesystem paths.
    """


def evaluate_security_gate(
    platform: PolicyEvaluation,
    checkov: CheckovScanResult,
    *,
    resource_type: ResourceType = ResourceType.SQS,
    required_policy_ids: tuple[str, ...] | None = None,
) -> SecurityGateResult:
    """Combine platform-policy and Checkov findings into one aggregate result.

    Pure function: given the same inputs, always returns an equal
    `SecurityGateResult`, regardless of the order of findings within
    either input. `resource_type` defaults to `ResourceType.SQS` to
    preserve every Phase 1 call site's exact behavior unchanged; Batch
    16-18 callers evaluating an S3/DynamoDB/Lambda request must pass
    `resource_type=` explicitly (see `iac_agent.graph.workflow`, which
    derives it from the request's own resource spec via
    `resource_type_of`, never a hardcoded default).

    `required_policy_ids` (Batch 19) lets a caller evaluating a
    *composition* request (no single `ResourceType` applies to it at
    all) supply the required-ID list directly — typically
    `iac_agent.policies.composition.
    REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE[...]` — instead
    of the `resource_type`-keyed lookup. When given, it always takes
    precedence over `resource_type`, which is then ignored entirely.
    """
    required_ids = (
        required_policy_ids
        if required_policy_ids is not None
        else REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE[resource_type]
    )
    _require_complete_platform_policies(platform, required_ids)
    _require_consistent_checkov_result(checkov)

    combined = platform.findings + checkov.findings
    deduplicated = _deduplicate_exact_values(combined)
    return SecurityGateResult(findings=deduplicated)


def _require_complete_platform_policies(
    platform: PolicyEvaluation, required_ids: tuple[str, ...]
) -> None:
    findings_by_policy_id: dict[str, list[SecurityFinding]] = {}
    for finding in platform.findings:
        findings_by_policy_id.setdefault(finding.policy_id, []).append(finding)

    for required_id in required_ids:
        matches = findings_by_policy_id.get(required_id, [])

        if not matches:
            raise SecurityGateError(f"required platform policy finding is missing: {required_id}")
        if len(matches) > 1:
            raise SecurityGateError(
                f"required platform policy finding is duplicated: {required_id} "
                f"({len(matches)} findings present)"
            )

        (finding,) = matches
        if finding.source is not FindingSource.PLATFORM_POLICY:
            raise SecurityGateError(
                f"required platform policy finding has an unexpected source: "
                f"{required_id} (source={finding.source.value})"
            )


def _require_consistent_checkov_result(checkov: CheckovScanResult) -> None:
    if len(checkov.findings) != checkov.failed_checks:
        raise SecurityGateError(
            "checkov result is internally inconsistent: "
            f"failed_checks={checkov.failed_checks} but {len(checkov.findings)} findings present"
        )


def _deduplicate_exact_values(
    findings: tuple[SecurityFinding, ...],
) -> tuple[SecurityFinding, ...]:
    """Drop exact value-identical duplicates, preserving first occurrence.

    Findings that merely share a resource, message, or policy_id are
    NOT duplicates and are always preserved — only a `SecurityFinding`
    equal in every field (policy_id, severity, status, resource,
    message, source) is collapsed. `SecurityFinding` is a frozen,
    `eq`-comparable dataclass, so `dict.fromkeys` deduplicates on the
    complete value, never on a partial key.
    """
    return tuple(dict.fromkeys(findings))
