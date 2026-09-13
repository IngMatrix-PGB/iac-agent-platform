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

from iac_agent.domain.security import (
    FindingSource,
    PolicyEvaluation,
    SecurityFinding,
    SecurityGateResult,
)
from iac_agent.policies.platform import (
    SQS_DLQ_RECOMMENDED,
    SQS_ENCRYPTION_REQUIRED,
    TF_NO_DESTRUCTIVE_CHANGES,
)
from iac_agent.security.checkov import CheckovScanResult

#: The Phase 1 first-party platform policies that must each contribute
#: exactly one PLATFORM_POLICY-sourced finding before the gate will
#: aggregate anything. Absence, duplication, or a mismatched source for
#: any of these means platform policy evaluation was incomplete —
#: "no finding" must never be silently read as "policy passed".
_REQUIRED_PLATFORM_POLICY_IDS = (
    SQS_ENCRYPTION_REQUIRED,
    SQS_DLQ_RECOMMENDED,
    TF_NO_DESTRUCTIVE_CHANGES,
)


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
) -> SecurityGateResult:
    """Combine platform-policy and Checkov findings into one aggregate result.

    Pure function: given the same two inputs, always returns an equal
    `SecurityGateResult`, regardless of the order of findings within
    either input.
    """
    _require_complete_platform_policies(platform)
    _require_consistent_checkov_result(checkov)

    combined = platform.findings + checkov.findings
    deduplicated = _deduplicate_exact_values(combined)
    return SecurityGateResult(findings=deduplicated)


def _require_complete_platform_policies(platform: PolicyEvaluation) -> None:
    findings_by_policy_id: dict[str, list[SecurityFinding]] = {}
    for finding in platform.findings:
        findings_by_policy_id.setdefault(finding.policy_id, []).append(finding)

    for required_id in _REQUIRED_PLATFORM_POLICY_IDS:
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
