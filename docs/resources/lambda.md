# Lambda + Execution IAM Resource (Phase 2, Batch 18)

## Why Lambda, and why this document exists

Batches 16 and 17 proved the platform generalizes across independent,
single-service AWS resources (S3, DynamoDB). Batch 18 adds Lambda
specifically to prove a *different* kind of generalization: a small,
deterministic **multi-resource relationship** — a function, its IAM
execution role, an inline CloudWatch Logs permission policy, and a log
group — represented as **one** top-level resource spec, not as a
generic IAM policy generator and not as two independently orchestrated
resource types. There is deliberately no `ResourceType.IAM` anywhere in
this platform. See `docs/roadmap.md` for the exact registration
touchpoints this batch used.

## Lambda + IAM as one resource, not two

`LambdaResourceSpec` is the only new `ResourceType` member
(`LAMBDA = "lambda"`). Its trusted Terraform module
(`terraform/modules/lambda`) creates the execution role, its inline
CloudWatch Logs permission policy, and the log group *internally* —
none of that is visible to the platform's resource-dispatch layer,
platform-policy layer, or Checkov-profile layer. This is a deliberate
architectural choice, not an oversight: a Lambda function is never
meaningfully requested without an execution role, so splitting them
into two independently-requestable resource types would let a user
construct a role with no function (or vice versa) — a state this
platform has no reason to support. See "Platform policy" below for why
there is no separate IAM platform policy either.

## The contract: `LambdaResourceSpec`

`iac_agent.providers.aws.lambda_function.contract.LambdaResourceSpec`
is the Lambda counterpart to `SQSResourceSpec`/`S3ResourceSpec`/
`DynamoDBResourceSpec` — a strongly typed, Pydantic-validated model
with no network calls, no AWS SDK, no filesystem access:

```python
LambdaResourceSpec(
    name: str,
    environment: str | None = None,
    runtime: LambdaRuntime = LambdaRuntime.PYTHON3_12,
    handler: str,
    architecture: LambdaArchitecture = LambdaArchitecture.ARM64,
    memory_size_mb: int = 256,
    timeout_seconds: int = 30,
    reserved_concurrency: int | None = None,
    tracing_mode: LambdaTracingMode = LambdaTracingMode.ACTIVE,
    log_retention_days: int = 365,
    environment_variables: dict[str, str] = {},
    tags: dict[str, str] = {},
)
```

Named `lambda_function` (package and module) rather than `lambda`
because `lambda` is a Python reserved keyword — this mirrors the
trusted module's own `aws_lambda_function` resource name, consistent
with this project's "resource-named provider package" convention
(`sqs`, `s3`, `dynamodb`).

The package is a **package of what to run and how**, never *what code
runs*. There is no field for a deployment package path, S3 code
location, or container image — see "Deployment package strategy"
below.

## Package/module boundaries: explicit Batch 18 non-goals

This contract deliberately excludes, all documented rather than
silently absent:

- **VPC configuration** — no subnet/security-group attachment.
- **Lambda Layers** — no shared-code-layer attachment.
- **Dead-letter queue (DLQ)** — a DLQ target is a cross-resource ARN
  reference; that composition is explicit Batch 19 scope (serverless
  composition), not this batch's.
- **Secrets Manager / SSM Parameter Store integration** — environment
  variables are the *only* configuration-injection mechanism this batch
  supports, and they are plaintext, not a secrets mechanism (see
  "Environment variables" below).
- **Event source mappings** (SQS triggers, EventBridge rules, Function
  URLs, API Gateway integrations) — deliberately deferred to Batch 19.
- **Customer-managed KMS** for the log group or environment variables —
  mirrors the identical DynamoDB deferral; see "Checkov" below.
- **Code signing configuration.**
- **Cross-resource IAM permissions** — the execution role can act on
  nothing but its own function's own log group.

## Runtime: `python3.12` only

`LambdaRuntime` has exactly one member, `PYTHON3_12`. Node.js, Java,
.NET, Go, Ruby, and custom runtimes are not added merely for breadth —
each would need its own handler-format validation and its own trusted
fixture package, which is more surface area than this batch's goal
(prove the Lambda+IAM relationship) requires.

## Deployment package strategy: a trusted, checked-in fixture only

Every function created by the trusted module references exactly one
file: `terraform/modules/lambda/fixtures/placeholder.zip`, a small,
checked-in zip built with a fixed timestamp (for deterministic
`terraform plan` output) containing a single trivial handler. It is
referenced via:

```hcl
filename         = "${path.module}/fixtures/placeholder.zip"
source_code_hash = filebase64sha256("${path.module}/fixtures/placeholder.zip")
```

This is a deliberate, explicitly-chosen strategy, not a shortcut taken
without consideration:

- **Never a user-controlled filesystem path.** Nothing in
  `LambdaResourceSpec` names a file on disk — there is no path for a
  caller (or an LLM acting on a caller's behalf) to point at arbitrary
  local files.
- **Never real application code.** This platform proposes
  infrastructure, never executes or packages a user's actual
  application logic.
- **No new Terraform provider.** An alternative design
  (`data.archive_file` / the `hashicorp/archive` provider, zipping a
  directory at plan time) was considered and explicitly rejected in
  favor of the fixture-zip approach, so this batch adds **zero** new
  Terraform providers. Per this batch's own instruction, adding
  `archive_file` would have required stopping to report it before
  proceeding — that never became necessary.
- **Decoupled from `handler`.** The contract's `handler` field is pure
  metadata describing what a real deployment's entry point *would be*
  — it is never read, imported, or executed by this project, and the
  fixture zip's own trivial handler is unrelated to it.

## Architecture, memory, and timeout

- **Architecture:** `x86_64` or `arm64`, default `arm64` (Graviton;
  typically better price/performance for a generic workload with no
  architecture-specific dependency).
- **Memory:** 128–10,240 MB, default 256 MB — verified against the
  canonical AWS Lambda quotas documentation. A separate, more advanced
  `CreateFunction` API reference describing up to 32,768 MB
  ("Lambda Managed Instances") was found during verification and
  deliberately **not** used — it documents a different, more advanced
  execution mode outside Batch 18's scope.
- **Timeout:** 1–900 seconds, default 30 seconds — Lambda's own
  documented minimum and maximum.

## Reserved concurrency: `-1` / `0` / `null` are three distinct states

`reserved_concurrency: int | None = None` mirrors AWS/Terraform's own
three-way semantics exactly, never collapsing them:

| Contract value | Terraform value | Meaning |
|---|---|---|
| `null` (the Python `None`/unset default) | `-1` | No reservation configured — the sentinel AWS/Terraform itself uses for "not set", never silently omitted |
| `0` | `0` | Fully throttle the function — a legitimate, distinct configuration (e.g. temporarily disabling invocations) |
| any positive integer | that integer | An explicit concurrency ceiling |

The renderer/module both implement this as
`reserved_concurrent_executions = var.reserved_concurrency == null ? -1 : var.reserved_concurrency`.
The platform policy (`LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED`, below)
treats `0` as "explicitly configured" exactly the same as any other
non-null value — only `null` triggers the WARN.

## Tracing: AWS X-Ray

`LambdaTracingMode` mirrors Lambda's own `TracingConfig.Mode` values
exactly (`Active`, `PassThrough`; exact casing verified against current
AWS API documentation), default `Active`. `PassThrough` is a legitimate,
constructible choice — the platform policy WARNs, never blocks.

## Environment variables: configuration, not secrets

`environment_variables: dict[str, str] = {}` supports plaintext
configuration only. Validation (verified against current AWS Lambda
documentation, not assumed):

- Names must start with a letter, be at least 2 characters, and contain
  only letters, digits, and underscores.
- Names may not collide with any of the 20 names AWS's Lambda runtime
  itself reserves (`AWS_REGION`, `_HANDLER`, `AWS_LAMBDA_FUNCTION_NAME`,
  etc.) — a caller-supplied variable using one of these names would
  silently never take effect at runtime, so rejecting it at
  construction is more useful than a runtime surprise.
- The aggregate size of all names+values together may not exceed 4,096
  bytes, Lambda's own documented limit.

**Environment variables are never a secrets mechanism.** There is no
encryption-at-rest configuration for them beyond Lambda's own default
AWS-owned-key encryption (see "Checkov" below for the one corresponding
skip), and there is no field for referencing Secrets Manager or SSM
Parameter Store — that integration is explicit future scope, deferred
rather than half-implemented as a plaintext-only stand-in.

## The execution role: generated, never hand-authored JSON

The trusted module never contains a raw hand-authored IAM policy JSON
blob, never attaches the AWS-managed
`AWSLambdaBasicExecutionRole` policy, and never uses
`Action = "*"`/`Resource = "*"`. Every IAM document is generated via
`aws_iam_policy_document` and applied via `aws_iam_role_policy`
(an inline policy, not a managed-policy attachment):

- **Trust policy** (`data.aws_iam_policy_document.assume_role`): allows
  `sts:AssumeRole` for exactly the `lambda.amazonaws.com` service
  principal. Verified directly from a real `terraform plan`'s resolved
  `assume_role_policy` JSON (this data source has no dependency on any
  not-yet-created resource, so it is fully known even in a
  credential-free plan) — see
  `tests/integration/test_lambda_renderer_terraform.py`.
- **CloudWatch Logs permission policy**
  (`data.aws_iam_policy_document.logs`, applied via
  `aws_iam_role_policy.logs`): grants exactly
  `logs:CreateLogGroup`, `logs:CreateLogStream`, and
  `logs:PutLogEvents`, scoped to
  `"${aws_cloudwatch_log_group.this.arn}:*"` — this function's own log
  group only, never a wildcard, never another resource type's ARN
  prefix. This resource's `Resource` value genuinely cannot be resolved
  in a credential-free plan (it depends on the log group's real
  AWS-assigned ARN) — confirmed empirically via `after_unknown` in a
  real plan before writing the corresponding test, rather than assumed.
  The concrete scoping expression is instead verified via a direct,
  justified static read of the trusted module's own checked-in
  `main.tf` (the exact file the plan just used).

## CloudWatch Logs: an explicitly-created log group with bounded retention

`aws_cloudwatch_log_group.this` is created explicitly by the module at
the conventional name `/aws/lambda/<function-name>` — never left to
Lambda's own lazy auto-creation (which would default to indefinite
retention). `log_retention_days` defaults to **365** and is restricted
to CloudWatch Logs' own complete 22-value `retentionInDays` enumeration
(1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096,
1827, 2192, 2557, 2922, 3288, 3653) — verified against the current
CloudWatch Logs API documentation. There is no indefinite-retention
option at all.

The default was originally 30 days and was raised to 365 as a direct
result of a real Checkov finding — see "Checkov" below.

## Platform policy

`iac_agent.policies.platform.evaluate_platform_policies` dispatches on
resource type and evaluates three Lambda-specific policies plus the
one platform-wide policy shared with SQS/S3/DynamoDB:

| Policy ID | Outcome |
|---|---|
| `LAMBDA_TRACING_RECOMMENDED` | PASS if `Active`, WARN if `PassThrough` — never BLOCK |
| `LAMBDA_RESERVED_CONCURRENCY_RECOMMENDED` | PASS if explicitly set (including `0`), WARN if `null` — never BLOCK |
| `LAMBDA_LOG_RETENTION_REQUIRED` | always PASS (evidence-only: the contract already restricts this to CloudWatch's own valid values, so no invalid value can ever reach this policy) |
| `TF_NO_DESTRUCTIVE_CHANGES` | shared with SQS/S3/DynamoDB — evaluated once, resource-agnostic |

There is deliberately **no separate IAM platform policy**. The
execution role's safety (trust principal, permission scope) is a
trusted-module invariant — enforced by the module's own fixed HCL, not
by anything derived from caller-supplied fields — and a Checkov
concern, not something this typed-input layer needs to re-evaluate.

## Checkov: one real fix, five documented scope exclusions

Running real Checkov (Checkov 3.3.13) against the secure Lambda+IAM
baseline (4 resources) initially reported **six** findings. One was a
genuine, fixable defect:

| Check | What it wanted | Resolution |
|---|---|---|
| `CKV_AWS_338` | "Ensure that AWS Lambda function is configured for a minimum of one year of log retention" | **Fixed directly** — raised `log_retention_days`'s default from 30 to 365 in both the contract and the module |

After that fix, real Checkov reported exactly five remaining findings,
each corresponding to a documented Phase 2 non-goal above:

| Check | What it wants | Why it's out of scope |
|---|---|---|
| `CKV_AWS_117` | Function configured inside a VPC | VPC configuration — explicit non-goal |
| `CKV_AWS_116` | Function configured with a DLQ | DLQ needs a cross-resource ARN — Batch 19 scope |
| `CKV_AWS_158` | Log group encrypted with customer-managed KMS | Mirrors the DynamoDB KMS deferral |
| `CKV_AWS_173` | Environment variables encrypted with customer-managed KMS | Same KMS deferral, applied to env vars |
| `CKV_AWS_272` | Code-signing configuration validated | A separate, more advanced feature never in scope |

Since every Checkov-reported failed check maps unconditionally to
`PolicyStatus.BLOCK` (no WARN pathway exists for Checkov findings),
leaving these five unskipped would mean no Lambda request could ever
reach human approval, regardless of how secure the baseline actually
is. Per this batch's own "classify the finding, then STOP and request
explicit approval before adding a skip" instruction, all five were
surfaced to the project owner via `AskUserQuestion` before being
added — the same discipline followed for S3 (Batch 16, four skips) and
DynamoDB (Batch 17, one skip). The project owner explicitly chose to
add all five as targeted skips. Real scan result with the skips
applied: 36 passed, 0 failed, 5 skipped
(`iac_agent.security.checkov_profiles.checkov_profile_for(ResourceType.LAMBDA)`).

## Workflow integration

`iac_agent.graph.workflow.build_iac_workflow` is the resource-neutral
entry point — a `LambdaResourceSpec` flows through the identical graph
nodes an `SQSResourceSpec`/`S3ResourceSpec`/`DynamoDBResourceSpec` does.
No new graph node was added for Lambda: `render_terraform` selects the
Lambda renderer and trusted module directory, and `source_control` uses
the existing generalized PR/commit text
(`feat(iac): add Lambda proposal <request_id>`, "Resource type:
lambda") — the same mechanism DynamoDB already generalized in Batch 17.

There is no `build_lambda_workflow` — `build_iac_workflow` remains the
one shared entry point every resource type ultimately goes through.

## Registration consistency: a new architecture regression test

`tests/unit/test_resource_registration_consistency.py` is a new,
explicitly-required test that mechanically proves — for every current
`ResourceType` member, via a small hand-maintained table of one minimal
real spec per resource type, deliberately not runtime metaprogramming —
correct dispatch, correct renderer dispatch, a complete
`REQUIRED_PLATFORM_POLICY_IDS_BY_RESOURCE_TYPE` entry that
`evaluate_platform_policies` actually satisfies, a non-raising
`checkov_profile_for`, an existing trusted module directory on disk,
and a non-empty display-name entry. It caught zero real registration
gaps once this batch's registration edits were made — confirming SQS,
S3, DynamoDB, and Lambda are all wired consistently everywhere this
platform's dispatch/policy/Checkov/module-directory surfaces exist.

## No `terraform apply`, still

Nothing about Lambda support changes this project's central safety
property: `TerraformRunner` has no `apply` method anywhere, no AWS
mutation of any kind ever occurs, and a GitHub pull request remains the
terminal artifact for a Lambda request exactly as it is for
SQS/S3/DynamoDB.

## Known application-layer debt (unchanged scope this batch)

`iac_agent.app.service.Phase1Application` and the composition layer
remain SQS-only (tracked since Batch 16 — see `docs/roadmap.md`).
Lambda, like S3 and DynamoDB, does not go through that layer in this
batch; every Lambda test in this batch calls `build_iac_workflow`
directly.
