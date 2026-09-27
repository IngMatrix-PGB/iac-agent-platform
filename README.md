# iac-agent-platform

Agentic Infrastructure-as-Code Platform — natural-language infrastructure
intent turned into safe, deterministic, reviewable Terraform changes.

**Status:** Phase 1 (AWS SQS) and Phase 2 (AWS S3, AWS DynamoDB, AWS
Lambda, AWS API Gateway, AWS ECR, and two compositions) are working,
validated vertical slices, proving the same design generalizes across
individual resource types and multi-resource architectures alike.
Currently supported resources: **SQS queues, S3 buckets, DynamoDB
tables, Lambda functions, API Gateway HTTP APIs, and ECR repositories**
— not generic AWS support.
Lambda includes a trusted execution IAM role internally (trust policy +
a narrowly scoped CloudWatch Logs permission, generated via
`aws_iam_policy_document` — never a hand-authored policy, never an
AWS-managed policy, never a wildcard); there is no independent, generic
IAM resource type.

Currently supported compositions:

- **SQS → Lambda → DynamoDB** (a "serverless worker" — an SQS queue
  triggers a Lambda consumer, which is granted permission to write to a
  DynamoDB table). See `docs/compositions/serverless-worker.md`.
- **API Gateway → Lambda** — an HTTP API route triggers a Lambda
  function via a proxy integration, with a narrowly-scoped Lambda
  resource-based invocation permission (never a change to the
  function's execution role). See `docs/compositions/api-lambda.md`.

Both are one bounded, named architecture each — never a generic
graph/DAG composer, and this platform does not claim to generate
arbitrary AWS architectures.

```
AWS resource spec (SQS queue, S3 bucket, DynamoDB table, Lambda function, API Gateway HTTP API, or ECR repository)
  or a composition (SQS → Lambda → DynamoDB, or API Gateway → Lambda)
  → deterministic Terraform rendering
  → Terraform validation/plan (credential-free)
  → deterministic security policy + Checkov
  → durable human-in-the-loop approval
  → GitHub pull request
```

An `IntentResolutionService` (Batch 21) optionally sits in front of
this pipeline, accepting natural language and resolving it — via a
closed, deterministic allowlist, never an LLM choice — to one of the
same typed requests above; it never introduces a new resource,
composition, or terminal artifact, and unresolved or unsupported
requests never reach Terraform at all. See
`docs/superpowers/specs/2026-09-15-structured-architecture-intent-design.md`.

A minimal stdlib-`argparse` CLI (Batch 24) exposes this natural-language
path from a terminal:

```
iac-agent propose "Build an asynchronous worker that reads messages from a queue, processes them, and saves the result."
iac-agent resume <request-id> --approve|--reject
```

It is a thin presentation layer only — no new orchestrator, no
`terraform apply`. See `docs/application.md` for the exact command
contract and required environment variables.

A request is only ever *proposed* as a reviewable pull request — it is
never deployed. See `docs/application.md`, `docs/hitl.md`,
`docs/source-control.md`, `docs/resources/s3.md`,
`docs/resources/dynamodb.md`, `docs/resources/lambda.md`,
`docs/resources/ecr.md`,
`docs/compositions/serverless-worker.md`,
`docs/compositions/api-lambda.md`,
`docs/compositions/api-lambda-dynamodb.md`, `docs/roadmap.md`,
`docs/ci.md`, `docs/real-llm-intent-interpreter.md`, and
`docs/aws-plan-boundary.md` for the composition root, the
approval gate, the GitHub adapter, the S3 resource, the DynamoDB
resource, the Lambda resource, the ECR repository, the serverless-worker
composition, the
API-Gateway-to-Lambda composition, the (Gate A complete, Gate B
pending) API-Gateway-to-Lambda-to-DynamoDB composition, the project
roadmap, the CI quality gates, the optional real LLM intent
interpreter, and the (implemented and empirically OIDC-verified;
real-AWS bootstrap/plan application still human-gated and deferred)
AWS OIDC plan boundary respectively.

**Safety:** `terraform apply` is not part of this project's design and
does not exist anywhere in this codebase. No AWS resource is ever
created; a GitHub pull request is Phase 1's terminal artifact.
