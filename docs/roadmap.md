# Roadmap

## Phase 1 — SQS (complete)

A working, validated vertical slice for AWS SQS: contract → renderer →
Terraform plan (credential-free) → deterministic security policy →
Checkov → durable human-in-the-loop approval → GitHub pull request.
Golden dataset: 14 scenarios / 38 evaluations, 100% pass rate. No
`terraform apply`, no AWS mutation, ever. See `docs/application.md`,
`docs/hitl.md`, `docs/source-control.md`.

## Phase 2 — S3 (complete)

**Goal:** prove the Phase 1 design generalizes to a second AWS resource
type without duplicating the platform — not "add S3" as an end in
itself. See `docs/resources/s3.md` for the full S3 contract, module,
policy, and Checkov-scope write-up.

Delivered so far:

- Shared `ResourceType` enum and `AWSResourceSpec` union
  (`iac_agent.providers.aws.resource`) — a small, explicit two-case
  dispatch (`match`/`case`), not a plugin framework or registry.
- Shared, resource-agnostic HCL-rendering primitives extracted from the
  SQS renderer (`iac_agent.providers.aws.terraform_render`) and reused
  byte-identically by the new S3 renderer.
- Shared KMS key-ID validation (`iac_agent.providers.aws.kms`).
- A new `S3ResourceSpec` contract with bucket-naming rules verified
  against current AWS documentation, hard invariants for encryption and
  public-access-block, and a soft (WARN-only) versioning policy.
- A new trusted `terraform/modules/s3` module with a strict, small
  security baseline (encryption, public access block, TLS-only bucket
  policy) — website hosting, ACLs, replication, lifecycle, object lock,
  logging, CloudFront, and notifications are explicit, documented Phase
  2 non-goals, not oversights.
- `iac_agent.graph.workflow.build_iac_workflow`: the new
  resource-neutral entry point, generalized from the Phase 1
  SQS-only graph. `build_sqs_workflow` remains as a zero-cost
  backward-compatible wrapper.
- A fix to `iac_agent.security.gate.evaluate_security_gate`, whose
  "platform policy evaluation was complete" check was hardcoded to
  SQS's own policy IDs — see `docs/resources/s3.md` for why this was a
  real (not hypothetical) blocker for every S3 request, and the
  resource-type-aware fix applied.
- An explicit, narrowly-scoped Checkov skip list for the four checks
  corresponding exactly to this batch's documented S3 scope exclusions
  — a project-owner decision, not a unilateral one. Batch 16.5 later
  hardened this into a resource-aware `CheckovScanProfile` /
  `checkov_profile_for` mapping (`src/iac_agent/security/
  checkov_profiles.py`) so the skip list can never grow into a global
  bucket of suppressions as more resource types are added — see
  `docs/resources/s3.md`.
- An S3 golden eval dataset (`evals/datasets/s3_golden.json`, 14
  scenarios) and parallel evaluators/loader/runner
  (`evals/evaluators/s3.py`, `evals/scenarios/s3_loader.py`,
  `evals/scenarios/s3_runner.py`).

## Phase 2 — DynamoDB (complete)

**Goal:** prove that adding a *third* resource type is mostly additive
— a small, bounded set of registration touchpoints, not a redesign of
anything shared. See `docs/resources/dynamodb.md` for the full
DynamoDB contract, module, policy, and Checkov-scope write-up.

DynamoDB registration touchpoints (discovered via read-only inspection
before implementation, confirmed accurate afterward):

- `ResourceType` (`iac_agent.domain.resource`) — one new member,
  `DYNAMODB = "dynamodb"`.
- `AWSResourceSpec` union + `resource_type_of` (`iac_agent.providers.
  aws.resource`) — one new union arm, one new `match`/`case` arm.
- `AWSResourceRenderer` (`iac_agent.providers.aws.renderer`) — one new
  constructor parameter (`dynamodb_renderer`), one new `case`.
- `REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE` and three new
  `_evaluate_dynamodb_*` policy functions (`iac_agent.policies.
  platform`) — no changes to the SQS/S3 policy functions or the shared
  destructive-change policy.
- `checkov_profile_for` mapping (`iac_agent.security.
  checkov_profiles`) — one new resource-type entry.
- `_DEFAULT_TRUSTED_MODULE_DIRS` (`iac_agent.graph.workflow`) — one new
  resource-type entry.
- `_ALLOWED_WORKFLOW_TYPES` serializer allowlist (`iac_agent.
  persistence.checkpoints`) — five new (module, qualname) entries for
  the new contract/enum types.
- One genuine non-mechanical fix, found and reported before changing:
  the PR/commit "resource kind" display text in `iac_agent.graph.
  workflow` derived from `resource_type_of(spec).value.upper()`, which
  happened to be correct for SQS/S3 (both already-correct all-caps
  acronyms) but would have produced "DYNAMODB" instead of "DynamoDB".
  Fixed with a small explicit `ResourceType`-keyed display-name
  mapping — not a broader redesign.

No changes were needed to: `terraform_execute`, `plan_analysis`,
`security_gate`, `approval_gate`, graph routing, `PlanAnalyzer`,
`SecurityGate`'s aggregation logic (only its already-generic
`resource_type`-keyed required-ID lookup, unchanged since Batch 16.5),
or the application/composition layer (DynamoDB does not go through
that layer in this batch — see "Known naming debt" below).

One deferred feature, decided via explicit project-owner approval
(not unilaterally): customer-managed KMS encryption for DynamoDB. A
real `terraform plan` failure ("invalid ARN: arn: invalid prefix")
showed `aws_dynamodb_table.server_side_encryption.kms_key_arn`
requires a full ARN, rejecting the bare alias/key-ID forms the shared
KMS validator accepts for SQS/S3 — so `DynamoDBEncryptionSpec` has no
`kms_key_id` field at all this phase. The one resulting real Checkov
finding (`CKV_AWS_119`, customer-managed CMK) was added to the
DynamoDB `CheckovScanProfile` only after being surfaced via
`AskUserQuestion` — see `docs/resources/dynamodb.md`.

## Phase 2 — Lambda + execution IAM (complete)

**Goal:** prove the platform can represent a small, deterministic
*multi-resource relationship* — a function, its IAM execution role, an
inline CloudWatch Logs permission policy, and a log group — as **one**
top-level resource spec, without becoming a generic IAM policy
generator. See `docs/resources/lambda.md` for the full Lambda contract,
module, IAM design, policy, and Checkov-scope write-up.

Lambda registration touchpoints (mirroring DynamoDB's exact pattern):

- `ResourceType` (`iac_agent.domain.resource`) — one new member,
  `LAMBDA = "lambda"`. No `ResourceType.IAM` was added, or ever
  planned — the execution role is a trusted-module implementation
  detail, never an independently requestable resource type.
- `AWSResourceSpec` union + `resource_type_of` (`iac_agent.providers.
  aws.resource`) — one new union arm, one new `match`/`case` arm.
- `AWSResourceRenderer` (`iac_agent.providers.aws.renderer`) — one new
  constructor parameter (`lambda_renderer`), one new `case`.
- `REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE` and three new
  `_evaluate_lambda_*` policy functions (`iac_agent.policies.
  platform`) — no changes to the SQS/S3/DynamoDB policy functions or
  the shared destructive-change policy, and deliberately no separate
  IAM platform policy at all.
- `checkov_profile_for` mapping (`iac_agent.security.
  checkov_profiles`) — one new resource-type entry (five skips).
- `_DEFAULT_TRUSTED_MODULE_DIRS` and `_RESOURCE_KIND_DISPLAY_NAMES`
  (`iac_agent.graph.workflow`) — one new resource-type entry each; no
  new graph node.
- `_ALLOWED_WORKFLOW_TYPES` serializer allowlist (`iac_agent.
  persistence.checkpoints`) — four new (module, qualname) entries for
  the new contract/enum types.
- A new architecture regression test,
  `tests/unit/test_resource_registration_consistency.py`, mechanically
  proving every one of the touchpoints above is wired consistently for
  every current `ResourceType` — see `docs/resources/lambda.md`.

One genuinely fixable Checkov defect (`CKV_AWS_338`, log retention
under one year) was resolved directly by raising the contract/module
default from 30 to 365 days. Five further findings, each corresponding
to a documented Phase 2 non-goal (VPC, DLQ, log-group KMS, env-var KMS,
code signing), were surfaced via `AskUserQuestion` before being added
as skips — the project owner explicitly approved all five, mirroring
the S3/DynamoDB decision-gate precedent exactly.

No new Terraform provider was added: the deployment package strategy
uses a single checked-in trusted fixture zip
(`terraform/modules/lambda/fixtures/placeholder.zip`), avoiding
`hashicorp/archive`/`archive_file` entirely — see
`docs/resources/lambda.md`.

**Next: Serverless composition** (Batch 19) — API Gateway, EventBridge,
SNS, DLQ wiring, and the FastAPI/HTTP adapter/UI work this and every
prior batch have deliberately deferred.

## Known naming debt (tracked, not yet resolved)

`iac_agent.app.service.Phase1Application` and the surrounding
composition layer (`iac_agent.app.composition`,
`iac_agent.app.config`) are still SQS-only as of Batch 18 — they
construct `build_sqs_workflow` and a single SQS trusted-module path
directly, never `build_iac_workflow` or an S3/DynamoDB/Lambda-capable
renderer. This is a real gap (the graph layer one level below has been
resource-neutral since Batch 16) but a full generalization here would
need `ApplicationConfig` to carry a *mapping* of trusted module
directories rather than one path, and `submit()`'s type hint widened
from `SQSResourceSpec` to `AWSResourceSpec` — more churn than any of
these batches' scope, and deferred rather than rushed each time.
Tracked here explicitly so it is not forgotten; revisit when the first
real caller (FastAPI adapter, CLI) makes the gap unavoidable.

## Not yet started

Serverless composition (API Gateway, EventBridge, SNS, DLQ wiring), a
FastAPI/HTTP adapter, and any UI remain entirely out of scope until a
future phase is explicitly approved.
