"""Resource-aware Checkov scan profiles for composition requests (Batch 19).

Mirrors `iac_agent.security.checkov_profiles` exactly in structure and
discipline: `CheckovAdapter` itself carries no notion of a composition,
and this is the one place that maps a `CompositionType` to the specific
`CheckovScanProfile` its requests are permitted to use.

A composition's skip list is **not** an automatic union of its
constituent resources' approved skip lists — that would silently trust
an assumption never actually verified for the composition itself.
Instead, this project's own discipline was followed exactly as
instructed: a **real, strict** Checkov scan (zero skips) was run first
against the composition's own rendered, secure-default baseline, and
the actual reported findings were compared against the constituent
skip lists — only then was a profile written.

Empirical result (2026-09, Checkov 3.3.13, real scan of the rendered
`ServerlessWorkerSpec` secure baseline — 10 managed resources: SQS
queue + DLQ, Lambda function + execution role + inline logs policy +
log group, DynamoDB table, the event source mapping, and the two
composition-owned `aws_iam_role_policy` resources — resource_count=10,
passed=69, failed=6): the reported failed checks are **exactly** the
union of DynamoDB's one already-approved skip (`CKV_AWS_119`) and
Lambda's five already-approved skips (`CKV_AWS_117`, `CKV_AWS_116`,
`CKV_AWS_158`, `CKV_AWS_173`, `CKV_AWS_272`) — no new finding appeared,
and critically **no S3-related check appeared at all** (this
composition never uses S3). Because the union hypothesis was verified
empirically rather than assumed, no new `AskUserQuestion` decision gate
was needed this batch — the six skips below are a direct, checked
carry-forward of decisions already explicitly approved by the project
owner in Batches 17 and 18, not a new unilateral decision.
"""

from __future__ import annotations

from iac_agent.domain.composition import CompositionType
from iac_agent.security.checkov import CheckovScanProfile

#: Verified empirically (see module docstring): exactly the union of
#: the already-approved DynamoDB and Lambda skips, and nothing else.
_SQS_LAMBDA_DYNAMODB_SKIPPED_CHECKS: tuple[str, ...] = (
    # DynamoDB: customer-managed KMS — same deferral as
    # `iac_agent.security.checkov_profiles._DYNAMODB_SKIPPED_CHECKS`.
    "CKV_AWS_119",
    # Lambda: VPC, DLQ, log-group KMS, env-var KMS, code-signing — same
    # five deferrals as
    # `iac_agent.security.checkov_profiles._LAMBDA_SKIPPED_CHECKS`. The
    # Lambda function's own DLQ check (CKV_AWS_116) is distinct from
    # this composition's *queue*: the Lambda function's own DLQ is
    # still Batch 19's own non-goal (a DLQ for the function's own
    # failed invocations, not the SQS event source mapping this
    # composition already builds).
    "CKV_AWS_117",
    "CKV_AWS_116",
    "CKV_AWS_158",
    "CKV_AWS_173",
    "CKV_AWS_272",
)

_PROFILES_BY_COMPOSITION_TYPE: dict[CompositionType, CheckovScanProfile] = {
    CompositionType.SQS_LAMBDA_DYNAMODB: CheckovScanProfile(
        skipped_checks=_SQS_LAMBDA_DYNAMODB_SKIPPED_CHECKS
    ),
}


def composition_checkov_profile_for(composition_type: CompositionType) -> CheckovScanProfile:
    """The Checkov scan profile for `composition_type`.

    Fails closed (raises `ValueError`) for any composition type without
    an explicit, reviewed profile registered above — mirrors
    `iac_agent.security.checkov_profiles.checkov_profile_for` exactly.
    """
    try:
        return _PROFILES_BY_COMPOSITION_TYPE[composition_type]
    except KeyError:
        raise ValueError(
            f"no Checkov scan profile registered for composition type: {composition_type!r}"
        ) from None
