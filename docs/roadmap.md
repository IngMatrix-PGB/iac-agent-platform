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
that layer in this batch — the app-layer naming debt this note used to
point to was resolved in Batch 20; see the "API Gateway (resource) +
API Gateway → Lambda (composition)" section below).

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

## Phase 2 — Serverless composition: SQS -> Lambda -> DynamoDB (complete)

**Goal:** prove the platform can model and generate a small
multi-resource architecture with deterministic relationships — not an
arbitrary graph DSL, not a generic workflow engine, not a generic IAM
generator, not a generic Terraform module composer. See
`docs/compositions/serverless-worker.md` for the full composition
contract, IAM design, Checkov-scope, and policy write-up.

Composition registration touchpoints (discovered via read-only
inspection before implementation, confirmed accurate afterward):

- `CompositionType` (`iac_agent.domain.composition`) — one new enum,
  separate from `ResourceType`, with one member,
  `SQS_LAMBDA_DYNAMODB`. No `ResourceType.SERVERLESS` was added or
  ever planned.
- `ServerlessWorkerSpec` (`iac_agent.compositions.serverless_worker.
  contract`) — reuses `SQSResourceSpec`/`LambdaResourceSpec`/
  `DynamoDBResourceSpec` verbatim as nested fields; adds pairwise-
  distinct-identifier, environment-consistency, and event-source-
  parameter invariants.
- `ServerlessWorkerTerraformRenderer` (`iac_agent.compositions.
  serverless_worker.renderer`) — instantiates the three existing
  trusted modules side by side and adds only the relationship
  resources (event source mapping, two narrowly-scoped
  `aws_iam_role_policy` resources) not naturally owned by any one of
  them.
- `iac_agent.request.IacRequestSpec`/`IacRenderer` — a new request-
  level dispatch boundary (`AWSResourceSpec | ServerlessWorkerSpec`),
  computing each renderer's expected module-source shape from the same
  `ResourceType`-keyed `trusted_module_dirs` mapping every AWS resource
  type already used; no new `CompositionType`-keyed trusted-module map.
- `iac_agent.policies.composition.evaluate_composition_policies` +
  `REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE` — three new
  composition-specific policies, plus the constituent Lambda/DynamoDB
  sub-specs' own already-approved recommendation policies reused
  verbatim (promoted from private to public functions in
  `iac_agent.policies.platform` for reuse), plus the shared
  destructive-changes policy (promoted to `iac_agent.policies.shared`
  once a second dispatcher needed it).
- `iac_agent.security.composition_checkov_profiles.
  composition_checkov_profile_for` — one new composition-type entry,
  verified empirically (not assumed) to be exactly the union of
  DynamoDB's and Lambda's already-approved skips, with zero new
  findings and zero S3-related findings.
- `iac_agent.security.gate.evaluate_security_gate` — one new optional
  `required_policy_ids` parameter, so a composition caller can supply
  its required-ID list directly instead of the `resource_type`-keyed
  lookup; every existing call site is unaffected.
- `iac_agent.graph.state.WorkflowState.resource_spec` — widened to
  `IacRequestSpec`; **not** renamed to `request_spec` (cosmetic churn
  with no behavioral benefit — see `docs/compositions/serverless-
  worker.md`).
- `iac_agent.graph.workflow.build_iac_workflow` — one new optional
  parameter (`serverless_worker_renderer`); `render_terraform`,
  `platform_policy`, and `checkov_scan` each gained one `match`/`case`
  branch; `terraform_execute`, `plan_analysis`, and `approval_gate`
  needed no change at all; `source_control`'s PR/commit text gained a
  composition-specific branch. No new graph node.
- `terraform/modules/lambda/outputs.tf` — one new output,
  `execution_role_name`, the smallest addition needed for the
  composition layer to attach its own IAM policies to the Lambda
  module's role without the module itself becoming IAM-relationship-
  aware.
- `iac_agent.app.service.Phase1Application` renamed to
  `IacApplication` (alias kept); `submit`'s type hint widened to
  `IacRequestSpec`. `iac_agent.app.composition.open_application`
  needed **zero** changes — proven directly (not just asserted) by a
  new test showing a `ServerlessWorkerSpec` request already works
  through the existing composition root.
- `iac_agent.persistence.checkpoints._ALLOWED_WORKFLOW_TYPES` — one
  new entry, `ServerlessWorkerSpec` (its nested sub-spec/enum types
  were already registered individually).

One genuine IAM design decision, evaluated and reported before
implementation (not assumed): Option B (composition-owned
`aws_iam_role_policy` resources targeting the Lambda module's own
`execution_role_name` output) over Option A (extending the Lambda
module with SQS/DynamoDB-aware inputs) — see
`docs/compositions/serverless-worker.md` for the full evaluation.

No new Terraform provider was added, and no new runtime dependency was
added.

**Next: Serverless composition, phase two** — a FastAPI/HTTP
application-layer adapter or API Gateway composition; this is not
claimed to be a full serverless platform yet.

## Phase 2 — API Gateway (resource) + API Gateway → Lambda (composition) (complete)

**Goal:** prove the composition architecture Batch 19 introduced
generalizes to a *second* composition without redesigning any core
layer — an explicit architectural test, not merely "add API Gateway."
See `docs/compositions/api-lambda.md` for the full composition
contract, IAM design, Checkov-scope, and policy write-up.

Resource-level registration touchpoints (Option A: API Gateway is a
full standalone resource type, reused by the composition — see the
design-gate evaluation in `docs/compositions/api-lambda.md`):

- `ResourceType.API_GATEWAY` (`iac_agent.domain.resource`).
- `ApiGatewayResourceSpec` (`iac_agent.providers.aws.api_gateway.
  contract`) — name/description/environment/tags only; protocol type
  is hardcoded HTTP, never a configurable field.
- `ApiGatewayTerraformCompositionRenderer` + `AWSResourceSpec` union +
  `resource_type_of` + `AWSResourceRenderer` — one new arm each,
  matching the existing SQS/S3/DynamoDB/Lambda precedent exactly.
- `terraform/modules/api_gateway` — owns `aws_apigatewayv2_api` and one
  `aws_apigatewayv2_stage` ("$default", `auto_deploy = true`), verified
  against the real AWS provider schema before writing `main.tf`.
- `REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE[ResourceType.
  API_GATEWAY]` — only the shared `TF_NO_DESTRUCTIVE_CHANGES` policy;
  no resource-specific policy was invented merely to inflate the count.
- `checkov_profile_for` — one new entry, one approved skip
  (`CKV_AWS_76`, access logging), approved via `AskUserQuestion`.
- `_DEFAULT_TRUSTED_MODULE_DIRS`/`_RESOURCE_KIND_DISPLAY_NAMES`
  (`iac_agent.graph.workflow`) — one new entry each.

Composition-level registration touchpoints:

- `CompositionType.API_GATEWAY_LAMBDA` (`iac_agent.domain.composition`)
  — kept fully separate from `ResourceType`; still no
  `ResourceType.SERVERLESS`.
- `ApiLambdaSpec`/`RouteSpec`/`HttpMethod` (`iac_agent.compositions.
  api_lambda.contract`) — reuses `ApiGatewayResourceSpec`/
  `LambdaResourceSpec` verbatim; adds pairwise-distinct-identifier and
  environment-consistency invariants, plus deterministic route-path
  validation (bounded, not the full API Gateway grammar).
- `ApiLambdaTerraformRenderer` (`iac_agent.compositions.api_lambda.
  renderer`) — instantiates the two trusted modules side by side and
  adds only the relationship resources not naturally owned by either
  (`aws_apigatewayv2_integration`, `aws_apigatewayv2_route`,
  `aws_lambda_permission`).
- `iac_agent.request.IacRequestSpec`/`IacRenderer` — widened again
  (`AWSResourceSpec | ServerlessWorkerSpec | ApiLambdaSpec`), one new
  `match`/`case` branch; no new `CompositionType`-keyed trusted-module
  map needed.
- `iac_agent.policies.composition.evaluate_composition_policies` +
  `REQUIRED_COMPOSITION_POLICY_IDS_BY_COMPOSITION_TYPE` — three new
  composition-specific policies (`API_LAMBDA_INVOKE_PERMISSION_
  REQUIRED`, `API_LAMBDA_NO_WILDCARD_PRINCIPAL`,
  `API_LAMBDA_ROUTE_EXPLICIT`) plus the constituent Lambda sub-spec's
  own tracing/reserved-concurrency policies reused verbatim, plus the
  shared destructive-changes policy — the same dispatcher Batch 19
  introduced, now matching a second composition spec type.
- `iac_agent.security.composition_checkov_profiles.
  composition_checkov_profile_for` — one new composition-type entry:
  six skips carried forward from the already-approved API Gateway and
  Lambda skips, plus one genuinely new finding this batch
  (`CKV_AWS_309`, route authorization), approved via `AskUserQuestion`.
- `iac_agent.graph.workflow.build_iac_workflow` — one new optional
  parameter (`api_lambda_renderer`); every `match`/`case` branch Batch
  19 added simply widened to include `ApiLambdaSpec`. No new graph
  node, no second gate function.
- `iac_agent.persistence.checkpoints._ALLOWED_WORKFLOW_TYPES` — four
  new entries (`ApiGatewayResourceSpec`, `ApiLambdaSpec`, `HttpMethod`,
  `RouteSpec`).
- A new `tests/unit/test_composition_registration_consistency.py`,
  mirroring the Batch 18 resource-level registration-consistency test
  exactly, now proving every `CompositionType` is wired consistently
  across request typing, renderer dispatch, policy expectations,
  Checkov profile, trusted-module requirements, and persistence.

One genuine IAM design decision, evaluated and reported before
implementation (not assumed): reusing "Option B" from Batch 19
unchanged — composition-owned `aws_lambda_permission` (a resource-based
permission, never a role change) rather than extending the Lambda
module itself to be API-Gateway-aware.

No new Terraform provider was added, and no new runtime dependency was
added. `ApplicationConfig.terraform_module_path` (tracked as naming
debt since Batch 19) was re-evaluated and **removed** this batch — it
was demonstrably dead configuration (never read from the environment,
always identical to `build_sqs_workflow`'s own default), not merely
undocumented; see `docs/compositions/api-lambda.md` for the full
evaluation and its regression tests.

**Next: not automatically implemented.** Candidate Batch 21 direction:
natural-language architecture intent, or a full async API composition
(API Gateway → Lambda → SQS → Lambda → DynamoDB) — a design review is
expected before either is started; this project is not yet a full
serverless platform.

## Not yet started

EventBridge, SNS, a second Lambda in one composition, chaining the two
existing compositions together, Cognito/JWT/Lambda authorizers, WAF,
custom domains, a FastAPI/HTTP adapter, natural-language/LLM-driven
intent parsing, and any UI remain entirely out of scope until a future
phase is explicitly approved.
