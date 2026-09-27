"""Resource-aware Checkov scan profiles for composition requests
(Batches 19-20).

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

Batch 26 followed the identical, ordered procedure for a *third*
composition (`ApiLambdaDynamoDbSpec`): render a real, secure-default
composition; run the existing strict, zero-skip real Checkov path
against it; capture every actual finding; classify each one
individually (genuine defect / accepted trade-off / false positive)
before writing anything here. See that composition's own result below,
after the Batch 19/20 results this module originally documented.

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

#: Verified empirically (2026-09, Checkov 3.3.13, real scan of the
#: rendered `ApiLambdaSpec` secure baseline — 9 managed resources:
#: HTTP API + $default stage, Lambda function + execution role +
#: inline logs policy + log group, the integration, the route, and the
#: Lambda permission — resource_count=9, passed=41, failed=7): six of
#: the seven findings are exactly the already-approved API Gateway skip
#: (`CKV_AWS_76`) and Lambda's five already-approved skips
#: (`CKV_AWS_117`, `CKV_AWS_116`, `CKV_AWS_158`, `CKV_AWS_173`,
#: `CKV_AWS_272`). The seventh, `CKV_AWS_309` ("Ensure API GatewayV2
#: routes specify an authorization type"), is a genuinely **new**
#: finding not covered by any prior batch's profile — surfaced to the
#: project owner via `AskUserQuestion` before being added, per this
#: batch's own "classify the finding, then STOP and request explicit
#: approval before adding a new skip" instruction. It corresponds
#: exactly to Batch 20's declared non-goal of authorization (no
#: Cognito, no JWT/Lambda authorizers, no IAM route auth, no API keys —
#: explicit future hardening, not this batch's scope).
_API_GATEWAY_LAMBDA_SKIPPED_CHECKS: tuple[str, ...] = (
    # API Gateway: access logging — same deferral as
    # `iac_agent.security.checkov_profiles._API_GATEWAY_SKIPPED_CHECKS`.
    "CKV_AWS_76",
    # Lambda: VPC, DLQ, log-group KMS, env-var KMS, code-signing — same
    # five deferrals as
    # `iac_agent.security.checkov_profiles._LAMBDA_SKIPPED_CHECKS`.
    "CKV_AWS_117",
    "CKV_AWS_116",
    "CKV_AWS_158",
    "CKV_AWS_173",
    "CKV_AWS_272",
    # API Gateway route authorization — a genuinely new finding this
    # batch, approved via AskUserQuestion (see docstring above).
    "CKV_AWS_309",
)

#: Verified empirically (Batch 26, 2026-09, Checkov 3.3.13, real scan
#: of the rendered `ApiLambdaDynamoDbSpec` secure baseline — 11 managed
#: resources: HTTP API + $default stage, Lambda function + execution
#: role + inline logs policy + log group, DynamoDB table, the
#: integration, the route, the Lambda permission, and the composition-
#: owned `aws_iam_role_policy.dynamodb_write` — resource_count=11,
#: passed=56, failed=8).
#:
#: Every one of the 8 real findings was classified individually, not
#: assumed from either existing profile:
#: - `CKV_AWS_116`/`CKV_AWS_117`/`CKV_AWS_158`/`CKV_AWS_173`/
#:   `CKV_AWS_272` — the same 5 Lambda deferrals both existing
#:   compositions already carry, because this composition reuses the
#:   identical, unchanged trusted Lambda module — an accepted
#:   architectural trade-off, not a new decision.
#: - `CKV_AWS_119` — the same DynamoDB customer-managed-KMS deferral
#:   `serverless_worker` already carries, because this composition
#:   reuses the identical, unchanged trusted DynamoDB module.
#: - `CKV_AWS_76`/`CKV_AWS_309` — the same 2 API Gateway deferrals
#:   `api_lambda` already carries (access logging; route authorization
#:   type), because this composition reuses the identical, unchanged
#:   API-Gateway integration/route model and the same declared
#:   Batch 20 non-goal (no authorization mechanism of any kind) still
#:   holds here — not a newly-discovered finding, and not re-escalated
#:   via `AskUserQuestion` since it is a direct carry-forward of an
#:   already-approved decision, not a new one.
#:
#: The result happens to equal the union of the other two profiles'
#: skip lists — exactly like `serverless_worker`'s own result did in
#: Batch 19 — but this was *discovered*, not assumed: no finding was
#: predicted in advance, and the real scan was run first with zero
#: composition-specific skips. No genuinely new finding appeared, and
#: none of the 8 findings required a renderer/composition fix.
_API_GATEWAY_LAMBDA_DYNAMODB_SKIPPED_CHECKS: tuple[str, ...] = (
    "CKV_AWS_76",
    "CKV_AWS_117",
    "CKV_AWS_116",
    "CKV_AWS_119",
    "CKV_AWS_158",
    "CKV_AWS_173",
    "CKV_AWS_272",
    "CKV_AWS_309",
)

_PROFILES_BY_COMPOSITION_TYPE: dict[CompositionType, CheckovScanProfile] = {
    CompositionType.SQS_LAMBDA_DYNAMODB: CheckovScanProfile(
        skipped_checks=_SQS_LAMBDA_DYNAMODB_SKIPPED_CHECKS
    ),
    CompositionType.API_GATEWAY_LAMBDA: CheckovScanProfile(
        skipped_checks=_API_GATEWAY_LAMBDA_SKIPPED_CHECKS
    ),
    CompositionType.API_GATEWAY_LAMBDA_DYNAMODB: CheckovScanProfile(
        skipped_checks=_API_GATEWAY_LAMBDA_DYNAMODB_SKIPPED_CHECKS
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
