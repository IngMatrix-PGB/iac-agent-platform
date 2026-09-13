"""Phase 1 deterministic platform policies for SQS requests.

`evaluate_platform_policies` is a pure function of two already-validated
facts — an `SQSResourceSpec` and a `PlanSummary` — and nothing else. It
never touches raw Terraform plan JSON, the Terraform CLI, Checkov, the
AWS API, or an LLM. Given the same spec and plan summary, it always
returns an equal `PolicyEvaluation`.
"""

from __future__ import annotations

from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import (
    FindingSource,
    PolicyEvaluation,
    PolicyStatus,
    SecurityFinding,
    SecuritySeverity,
)
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

SQS_ENCRYPTION_REQUIRED = "SQS_ENCRYPTION_REQUIRED"
SQS_DLQ_RECOMMENDED = "SQS_DLQ_RECOMMENDED"
TF_NO_DESTRUCTIVE_CHANGES = "TF_NO_DESTRUCTIVE_CHANGES"


def evaluate_platform_policies(
    spec: SQSResourceSpec,
    plan_summary: PlanSummary,
) -> PolicyEvaluation:
    """Evaluate every Phase 1 platform policy and return the aggregate result.

    One finding is always emitted per policy, including PASS — later
    UI/eval consumers need positive evidence that a policy actually ran,
    rather than inferring "no finding means pass".
    """
    findings = (
        _evaluate_encryption_policy(spec),
        _evaluate_dlq_policy(spec),
        _evaluate_destructive_policy(plan_summary),
    )
    return PolicyEvaluation(findings=findings)


def _evaluate_encryption_policy(spec: SQSResourceSpec) -> SecurityFinding:
    """SQS_ENCRYPTION_REQUIRED — defense in depth.

    The Pydantic contract and the trusted Terraform module already make
    an unencrypted queue unconstructible, so this normally always
    PASSes. It exists to fail closed (BLOCK) if an internally-invalid
    spec ever reaches this layer regardless.
    """
    if spec.encryption.enabled:
        return SecurityFinding(
            policy_id=SQS_ENCRYPTION_REQUIRED,
            severity=SecuritySeverity.HIGH,
            status=PolicyStatus.PASS,
            resource=spec.name,
            message="SQS encryption is enabled.",
            source=FindingSource.PLATFORM_POLICY,
        )
    return SecurityFinding(
        policy_id=SQS_ENCRYPTION_REQUIRED,
        severity=SecuritySeverity.HIGH,
        status=PolicyStatus.BLOCK,
        resource=spec.name,
        message="SQS encryption is disabled; this request cannot proceed.",
        source=FindingSource.PLATFORM_POLICY,
    )


def _evaluate_dlq_policy(spec: SQSResourceSpec) -> SecurityFinding:
    """SQS_DLQ_RECOMMENDED — a warning, not a block.

    A disabled DLQ is a legitimate choice for some workloads, but the
    review flow should surface the risk rather than silently proceed.
    """
    if spec.dlq.enabled:
        return SecurityFinding(
            policy_id=SQS_DLQ_RECOMMENDED,
            severity=SecuritySeverity.MEDIUM,
            status=PolicyStatus.PASS,
            resource=spec.name,
            message="Dead-letter queue is enabled.",
            source=FindingSource.PLATFORM_POLICY,
        )
    return SecurityFinding(
        policy_id=SQS_DLQ_RECOMMENDED,
        severity=SecuritySeverity.MEDIUM,
        status=PolicyStatus.WARN,
        resource=spec.name,
        message="Dead-letter queue is disabled; review retry/failure handling.",
        source=FindingSource.PLATFORM_POLICY,
    )


def _evaluate_destructive_policy(plan_summary: PlanSummary) -> SecurityFinding:
    """TF_NO_DESTRUCTIVE_CHANGES — blocks on any destructive plan action.

    A REPLACE is destructive (it contains a delete) exactly as
    established in Batch 6's PlanSummary semantics; no exception is
    made for it here. ``resource`` is left None because this finding
    can summarize more than one resource — the destroyed addresses are
    named in the message instead, never with raw before/after values.
    """
    if not plan_summary.destructive_change_detected:
        return SecurityFinding(
            policy_id=TF_NO_DESTRUCTIVE_CHANGES,
            severity=SecuritySeverity.CRITICAL,
            status=PolicyStatus.PASS,
            resource=None,
            message="Terraform plan contains no destructive changes.",
            source=FindingSource.PLATFORM_POLICY,
        )
    addresses = ", ".join(sorted(plan_summary.resources_to_destroy))
    return SecurityFinding(
        policy_id=TF_NO_DESTRUCTIVE_CHANGES,
        severity=SecuritySeverity.CRITICAL,
        status=PolicyStatus.BLOCK,
        resource=None,
        message=f"Terraform plan contains destructive changes: {addresses}.",
        source=FindingSource.PLATFORM_POLICY,
    )
