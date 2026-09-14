"""Phase 2 deterministic platform policies for SQS, S3, and DynamoDB
requests.

`evaluate_platform_policies` is a pure function of two already-validated
facts — a resource spec (`SQSResourceSpec`, `S3ResourceSpec`, or
`DynamoDBResourceSpec`) and a `PlanSummary` — and nothing else. It
never touches raw Terraform plan JSON, the Terraform CLI, Checkov, the
AWS API, or an LLM. Given the same spec and plan summary, it always
returns an equal `PolicyEvaluation`.

Resource-specific policies stay resource-specific (SQS encryption/DLQ
checks only ever run for `SQSResourceSpec`; S3 encryption/public-access/
versioning checks only ever run for `S3ResourceSpec`; DynamoDB
encryption/PITR/deletion-protection checks only ever run for
`DynamoDBResourceSpec`). `TF_NO_DESTRUCTIVE_CHANGES` is platform-wide —
it never touches the resource spec at all, only the plan summary — so
it is evaluated exactly once, for every resource type, rather than
duplicated per resource.
"""

from __future__ import annotations

from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.resource import ResourceType
from iac_agent.domain.security import (
    FindingSource,
    PolicyEvaluation,
    PolicyStatus,
    SecurityFinding,
    SecuritySeverity,
)
from iac_agent.providers.aws.dynamodb.contract import DynamoDBResourceSpec
from iac_agent.providers.aws.resource import AWSResourceSpec
from iac_agent.providers.aws.s3.contract import S3ResourceSpec
from iac_agent.providers.aws.sqs.contract import SQSResourceSpec

SQS_ENCRYPTION_REQUIRED = "SQS_ENCRYPTION_REQUIRED"
SQS_DLQ_RECOMMENDED = "SQS_DLQ_RECOMMENDED"
S3_ENCRYPTION_REQUIRED = "S3_ENCRYPTION_REQUIRED"
S3_PUBLIC_ACCESS_BLOCK_REQUIRED = "S3_PUBLIC_ACCESS_BLOCK_REQUIRED"
S3_VERSIONING_RECOMMENDED = "S3_VERSIONING_RECOMMENDED"
DDB_ENCRYPTION_REQUIRED = "DDB_ENCRYPTION_REQUIRED"
DDB_PITR_RECOMMENDED = "DDB_PITR_RECOMMENDED"
DDB_DELETION_PROTECTION_RECOMMENDED = "DDB_DELETION_PROTECTION_RECOMMENDED"
TF_NO_DESTRUCTIVE_CHANGES = "TF_NO_DESTRUCTIVE_CHANGES"

#: The complete set of platform-policy IDs `evaluate_platform_policies`
#: guarantees to emit for a request of each resource type — the single
#: source of truth `iac_agent.security.gate.evaluate_security_gate`
#: reads to check that platform-policy evaluation was complete before
#: aggregating, rather than that module hardcoding its own resource-
#: specific list (which is what let a Phase 1 SQS-only list silently
#: reject every S3 request until Batch 16 fixed it).
REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE: dict[ResourceType, tuple[str, ...]] = {
    ResourceType.SQS: (SQS_ENCRYPTION_REQUIRED, SQS_DLQ_RECOMMENDED, TF_NO_DESTRUCTIVE_CHANGES),
    ResourceType.S3: (
        S3_ENCRYPTION_REQUIRED,
        S3_PUBLIC_ACCESS_BLOCK_REQUIRED,
        S3_VERSIONING_RECOMMENDED,
        TF_NO_DESTRUCTIVE_CHANGES,
    ),
    ResourceType.DYNAMODB: (
        DDB_ENCRYPTION_REQUIRED,
        DDB_PITR_RECOMMENDED,
        DDB_DELETION_PROTECTION_RECOMMENDED,
        TF_NO_DESTRUCTIVE_CHANGES,
    ),
}


def evaluate_platform_policies(
    spec: AWSResourceSpec,
    plan_summary: PlanSummary,
) -> PolicyEvaluation:
    """Evaluate every applicable Phase 2 platform policy and return the
    aggregate result.

    One finding is always emitted per applicable policy, including
    PASS — later UI/eval consumers need positive evidence that a policy
    actually ran, rather than inferring "no finding means pass".
    """
    match spec:
        case SQSResourceSpec():
            resource_findings: tuple[SecurityFinding, ...] = (
                _evaluate_sqs_encryption_policy(spec),
                _evaluate_sqs_dlq_policy(spec),
            )
        case S3ResourceSpec():
            resource_findings = (
                _evaluate_s3_encryption_policy(spec),
                _evaluate_s3_public_access_policy(spec),
                _evaluate_s3_versioning_policy(spec),
            )
        case DynamoDBResourceSpec():
            resource_findings = (
                _evaluate_dynamodb_encryption_policy(spec),
                _evaluate_dynamodb_pitr_policy(spec),
                _evaluate_dynamodb_deletion_protection_policy(spec),
            )
        case _:
            raise ValueError(f"unsupported resource spec type: {type(spec).__name__}")

    findings = (*resource_findings, _evaluate_destructive_policy(plan_summary))
    return PolicyEvaluation(findings=findings)


# ---------------------------------------------------------------------------
# SQS policies
# ---------------------------------------------------------------------------


def _evaluate_sqs_encryption_policy(spec: SQSResourceSpec) -> SecurityFinding:
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


def _evaluate_sqs_dlq_policy(spec: SQSResourceSpec) -> SecurityFinding:
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


# ---------------------------------------------------------------------------
# S3 policies
# ---------------------------------------------------------------------------


def _evaluate_s3_encryption_policy(spec: S3ResourceSpec) -> SecurityFinding:
    """S3_ENCRYPTION_REQUIRED — defense in depth, mirroring the SQS
    encryption policy exactly: the Pydantic contract and the trusted
    Terraform module already make an unencrypted bucket unconstructible."""
    if spec.encryption.enabled:
        return SecurityFinding(
            policy_id=S3_ENCRYPTION_REQUIRED,
            severity=SecuritySeverity.HIGH,
            status=PolicyStatus.PASS,
            resource=spec.name,
            message="S3 encryption is enabled.",
            source=FindingSource.PLATFORM_POLICY,
        )
    return SecurityFinding(
        policy_id=S3_ENCRYPTION_REQUIRED,
        severity=SecuritySeverity.HIGH,
        status=PolicyStatus.BLOCK,
        resource=spec.name,
        message="S3 encryption is disabled; this request cannot proceed.",
        source=FindingSource.PLATFORM_POLICY,
    )


def _evaluate_s3_public_access_policy(spec: S3ResourceSpec) -> SecurityFinding:
    """S3_PUBLIC_ACCESS_BLOCK_REQUIRED — defense in depth: the Pydantic
    contract already makes `block_public_access=False` unconstructible."""
    if spec.block_public_access:
        return SecurityFinding(
            policy_id=S3_PUBLIC_ACCESS_BLOCK_REQUIRED,
            severity=SecuritySeverity.CRITICAL,
            status=PolicyStatus.PASS,
            resource=spec.name,
            message="S3 public access is blocked.",
            source=FindingSource.PLATFORM_POLICY,
        )
    return SecurityFinding(
        policy_id=S3_PUBLIC_ACCESS_BLOCK_REQUIRED,
        severity=SecuritySeverity.CRITICAL,
        status=PolicyStatus.BLOCK,
        resource=spec.name,
        message="S3 public access block is disabled; this request cannot proceed.",
        source=FindingSource.PLATFORM_POLICY,
    )


def _evaluate_s3_versioning_policy(spec: S3ResourceSpec) -> SecurityFinding:
    """S3_VERSIONING_RECOMMENDED — a warning, not a block. Disabled
    versioning is a legitimate choice for some workloads (mirrors the
    SQS DLQ policy's WARN-not-BLOCK precedent)."""
    if spec.versioning:
        return SecurityFinding(
            policy_id=S3_VERSIONING_RECOMMENDED,
            severity=SecuritySeverity.MEDIUM,
            status=PolicyStatus.PASS,
            resource=spec.name,
            message="S3 object versioning is enabled.",
            source=FindingSource.PLATFORM_POLICY,
        )
    return SecurityFinding(
        policy_id=S3_VERSIONING_RECOMMENDED,
        severity=SecuritySeverity.MEDIUM,
        status=PolicyStatus.WARN,
        resource=spec.name,
        message="S3 object versioning is disabled; review data-recovery requirements.",
        source=FindingSource.PLATFORM_POLICY,
    )


# ---------------------------------------------------------------------------
# DynamoDB policies
# ---------------------------------------------------------------------------


def _evaluate_dynamodb_encryption_policy(spec: DynamoDBResourceSpec) -> SecurityFinding:
    """DDB_ENCRYPTION_REQUIRED — defense in depth, mirroring the SQS/S3
    encryption policies exactly: the Pydantic contract and the trusted
    Terraform module already make an unencrypted table unconstructible."""
    if spec.encryption.enabled:
        return SecurityFinding(
            policy_id=DDB_ENCRYPTION_REQUIRED,
            severity=SecuritySeverity.HIGH,
            status=PolicyStatus.PASS,
            resource=spec.name,
            message="DynamoDB encryption is enabled.",
            source=FindingSource.PLATFORM_POLICY,
        )
    return SecurityFinding(
        policy_id=DDB_ENCRYPTION_REQUIRED,
        severity=SecuritySeverity.HIGH,
        status=PolicyStatus.BLOCK,
        resource=spec.name,
        message="DynamoDB encryption is disabled; this request cannot proceed.",
        source=FindingSource.PLATFORM_POLICY,
    )


def _evaluate_dynamodb_pitr_policy(spec: DynamoDBResourceSpec) -> SecurityFinding:
    """DDB_PITR_RECOMMENDED — a warning, not a block. Disabled
    point-in-time recovery is a legitimate choice for some workloads
    (mirrors the SQS DLQ / S3 versioning WARN-not-BLOCK precedent)."""
    if spec.point_in_time_recovery:
        return SecurityFinding(
            policy_id=DDB_PITR_RECOMMENDED,
            severity=SecuritySeverity.MEDIUM,
            status=PolicyStatus.PASS,
            resource=spec.name,
            message="DynamoDB point-in-time recovery is enabled.",
            source=FindingSource.PLATFORM_POLICY,
        )
    return SecurityFinding(
        policy_id=DDB_PITR_RECOMMENDED,
        severity=SecuritySeverity.MEDIUM,
        status=PolicyStatus.WARN,
        resource=spec.name,
        message="DynamoDB point-in-time recovery is disabled; review data-recovery requirements.",
        source=FindingSource.PLATFORM_POLICY,
    )


def _evaluate_dynamodb_deletion_protection_policy(spec: DynamoDBResourceSpec) -> SecurityFinding:
    """DDB_DELETION_PROTECTION_RECOMMENDED — a warning, not a block:
    users may legitimately need an ephemeral/demo table, so this is
    never force-corrected back to True, only flagged."""
    if spec.deletion_protection:
        return SecurityFinding(
            policy_id=DDB_DELETION_PROTECTION_RECOMMENDED,
            severity=SecuritySeverity.MEDIUM,
            status=PolicyStatus.PASS,
            resource=spec.name,
            message="DynamoDB deletion protection is enabled.",
            source=FindingSource.PLATFORM_POLICY,
        )
    return SecurityFinding(
        policy_id=DDB_DELETION_PROTECTION_RECOMMENDED,
        severity=SecuritySeverity.MEDIUM,
        status=PolicyStatus.WARN,
        resource=spec.name,
        message="DynamoDB deletion protection is disabled; review accidental-deletion risk.",
        source=FindingSource.PLATFORM_POLICY,
    )


# ---------------------------------------------------------------------------
# Platform-wide policy (resource-agnostic)
# ---------------------------------------------------------------------------


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
