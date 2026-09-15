"""Deterministic composition-level policies for the SQS -> Lambda ->
DynamoDB serverless-worker architecture (Phase 2, Batch 19).

`evaluate_composition_policies` is the composition counterpart to
`iac_agent.policies.platform.evaluate_platform_policies` — a pure
function of an already-validated `ServerlessWorkerSpec` and a
`PlanSummary`, nothing else. It never touches raw Terraform plan JSON,
the Terraform CLI, Checkov, the AWS API, or an LLM.

These policies evaluate exactly what this batch's own typed composition
input and rendered-plan evidence can honestly support — see each
function's docstring for its evidence source. They deliberately do
**not** attempt to parse or re-derive the IAM policy JSON the
composition renderer emits (that JSON's `resources` field is genuinely
unknown at credential-free plan time, exactly as Batch 18 already
established for the Lambda module's own CloudWatch Logs policy — see
`tests/integration/test_serverless_worker_renderer_terraform.py` for
the real-plan proof of the composition's IAM scoping instead). Static,
deterministic facts about the *composition spec itself* (which queue is
bound, which table is bound, that the generated relationship never
grants a wildcard action) are exactly what a typed-input policy layer
can respond to.

In addition to the three composition-specific policies below, this
dispatcher also runs the constituent Lambda/DynamoDB sub-specs' own
already-approved recommendation policies
(`evaluate_lambda_tracing_policy`, `evaluate_lambda_reserved_
concurrency_policy`, `evaluate_dynamodb_pitr_policy`,
`evaluate_dynamodb_deletion_protection_policy` — reused verbatim from
`iac_agent.policies.platform`, never re-implemented here) against
`spec.function`/`spec.table`. A composition's Lambda tracing mode or
DynamoDB point-in-time-recovery setting is exactly as real a risk
signal inside a composition as it is for a standalone Lambda/DynamoDB
request — dropping it here would silently discard evidence Batches
17-18 already established matters. The SQS queue's own DLQ/encryption
policies are deliberately **not** re-run here: the composition's SQS
consumer relationship only cares that the queue exists and is bound
correctly (`SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED`), and SQS's own
encryption invariant is unconditional (never representable as
disabled) so re-running it would only ever repeat a PASS a caller
cannot act on differently inside a composition.
"""

from __future__ import annotations

from iac_agent.compositions.serverless_worker.contract import ServerlessWorkerSpec
from iac_agent.domain.composition import CompositionType
from iac_agent.domain.plan import PlanSummary
from iac_agent.domain.security import (
    FindingSource,
    PolicyEvaluation,
    PolicyStatus,
    SecurityFinding,
    SecuritySeverity,
)
from iac_agent.policies.platform import (
    DDB_DELETION_PROTECTION_RECOMMENDED,
    DDB_PITR_RECOMMENDED,
    LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
    LAMBDA_TRACING_RECOMMENDED,
    evaluate_dynamodb_deletion_protection_policy,
    evaluate_dynamodb_pitr_policy,
    evaluate_lambda_reserved_concurrency_policy,
    evaluate_lambda_tracing_policy,
)
from iac_agent.policies.shared import TF_NO_DESTRUCTIVE_CHANGES, evaluate_destructive_policy

SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED = "SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED"
SERVERLESS_DDB_WRITE_SCOPE_REQUIRED = "SERVERLESS_DDB_WRITE_SCOPE_REQUIRED"
SERVERLESS_NO_WILDCARD_IAM = "SERVERLESS_NO_WILDCARD_IAM"

#: The composition counterpart to `iac_agent.policies.platform.
#: REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE` — the single source of
#: truth `iac_agent.security.gate.evaluate_security_gate` reads (via its
#: `required_policy_ids` parameter) to check that composition-policy
#: evaluation was complete before aggregating.
REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE: dict[CompositionType, tuple[str, ...]] = {
    CompositionType.SQS_LAMBDA_DYNAMODB: (
        SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED,
        SERVERLESS_DDB_WRITE_SCOPE_REQUIRED,
        SERVERLESS_NO_WILDCARD_IAM,
        LAMBDA_TRACING_RECOMMENDED,
        LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED,
        DDB_PITR_RECOMMENDED,
        DDB_DELETION_PROTECTION_RECOMMENDED,
        TF_NO_DESTRUCTIVE_CHANGES,
    ),
}


def evaluate_composition_policies(
    spec: ServerlessWorkerSpec,
    plan_summary: PlanSummary,
) -> PolicyEvaluation:
    """Evaluate every applicable Batch 19 composition policy and return
    the aggregate result — the composition counterpart to
    `iac_agent.policies.platform.evaluate_platform_policies`. One
    finding is always emitted per applicable policy, including PASS,
    exactly like the platform-policy dispatcher.
    """
    findings = (
        _evaluate_sqs_lambda_binding_policy(spec),
        _evaluate_dynamodb_write_scope_policy(spec),
        _evaluate_no_wildcard_iam_policy(),
        evaluate_lambda_tracing_policy(spec.function),
        evaluate_lambda_reserved_concurrency_policy(spec.function),
        evaluate_dynamodb_pitr_policy(spec.table),
        evaluate_dynamodb_deletion_protection_policy(spec.table),
        evaluate_destructive_policy(plan_summary),
    )
    return PolicyEvaluation(findings=findings)


def _evaluate_sqs_lambda_binding_policy(spec: ServerlessWorkerSpec) -> SecurityFinding:
    """SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED — always PASS.

    Evidence source: the already-validated `ServerlessWorkerSpec`
    itself. `ServerlessWorkerSpec.queue`/`.function` being present and
    correctly typed (`SQSResourceSpec`/`LambdaResourceSpec`) is a
    Pydantic-enforced construction-time invariant — there is no
    representable `ServerlessWorkerSpec` missing either sub-spec, so
    this can never observe an unbound pair. Exists so later UI/eval
    consumers have positive evidence the binding was actually checked,
    mirroring the defense-in-depth pattern already used for SQS/S3/
    DynamoDB's own hard-invariant encryption policies.
    """
    return SecurityFinding(
        policy_id=SERVERLESS_SQS_LAMBDA_BINDING_REQUIRED,
        severity=SecuritySeverity.HIGH,
        status=PolicyStatus.PASS,
        resource=spec.name,
        message=(
            f"Lambda function {spec.function.name!r} is bound to SQS queue "
            f"{spec.queue.name!r} via an event source mapping."
        ),
        source=FindingSource.PLATFORM_POLICY,
    )


def _evaluate_dynamodb_write_scope_policy(spec: ServerlessWorkerSpec) -> SecurityFinding:
    """SERVERLESS_DDB_WRITE_SCOPE_REQUIRED — always PASS.

    Evidence source: the already-validated `ServerlessWorkerSpec`
    itself, combined with the renderer's own fixed, non-caller-
    configurable choice of exactly one DynamoDB action
    (`dynamodb:PutItem` — see
    `iac_agent.compositions.serverless_worker.renderer`). There is no
    field on this contract through which a caller can request a
    different or broader DynamoDB action, so this table is always
    granted write access, and only write access, to exactly the one
    table named in this spec. The real, rendered IAM policy's resource
    scoping is proven directly against a real Terraform plan in
    `tests/integration/test_serverless_worker_renderer_terraform.py` —
    this policy records that the *typed relationship* which drives that
    rendering is itself well-formed.
    """
    return SecurityFinding(
        policy_id=SERVERLESS_DDB_WRITE_SCOPE_REQUIRED,
        severity=SecuritySeverity.HIGH,
        status=PolicyStatus.PASS,
        resource=spec.name,
        message=(
            f"Lambda function {spec.function.name!r} is granted dynamodb:PutItem, "
            f"scoped to table {spec.table.name!r} only."
        ),
        source=FindingSource.PLATFORM_POLICY,
    )


def _evaluate_no_wildcard_iam_policy() -> SecurityFinding:
    """SERVERLESS_NO_WILDCARD_IAM — always PASS, evidence-only.

    Evidence source: this is a trusted-renderer invariant, not a fact
    derivable from `ServerlessWorkerSpec`'s fields (nothing in the
    contract could ever *cause* a wildcard action or resource to be
    emitted — there is no such field to set). The renderer's fixed
    action lists (`_SQS_CONSUMER_ACTIONS`, `_DYNAMODB_WRITE_ACTIONS`)
    and fixed per-resource-ARN scoping are checked-in, reviewed source,
    proven never to contain a wildcard via a real Terraform plan in
    `tests/integration/test_serverless_worker_renderer_terraform.py`.
    This finding exists so later UI/eval consumers have positive
    evidence the check was made, exactly like Lambda's own
    LAMBDA_LOG_RETENTION_REQUIRED policy.
    """
    return SecurityFinding(
        policy_id=SERVERLESS_NO_WILDCARD_IAM,
        severity=SecuritySeverity.CRITICAL,
        status=PolicyStatus.PASS,
        resource=None,
        message=(
            "Composition-generated IAM policies grant only the documented, "
            "narrowly-scoped SQS-consumer and DynamoDB-write actions — never a "
            "wildcard action or resource."
        ),
        source=FindingSource.PLATFORM_POLICY,
    )
