# iac-agent-platform

IaC Agent turns a natural-language infrastructure request into a reviewable GitHub pull request.

```text
natural-language request
  → typed ArchitectureIntent
  → deterministic resolver and contracts
  → trusted Terraform rendering
  → terraform plan
  → security analysis
  → human approval
  → GitHub pull request
```

Terraform apply is not performed. Terraform destroy is not performed. No AWS resource is created.

## What it supports

Resources: SQS queues, S3 buckets, DynamoDB tables, Lambda functions (including the execution role), API Gateway HTTP APIs, and ECR repositories.

Compositions, each one closed architecture:

- SQS → Lambda → DynamoDB (`docs/compositions/serverless-worker.md`)
- API Gateway → Lambda (`docs/compositions/api-lambda.md`)
- API Gateway → Lambda → DynamoDB (`docs/compositions/api-lambda-dynamodb.md`)

The resolver allowlist is closed. Anything else stops before Terraform. See `docs/intent.md`.

A local HTTP API and operator UI review the plan, the security result, and the human decision. The operator secret stays in memory. That check is not RBAC. See `docs/api.md`.

## Documentation

- `docs/intent.md` — intent model and resolver
- `docs/application.md` — composition root and CLI
- `docs/api.md` — HTTP API, operator UI, request id
- `docs/hitl.md` — human approval
- `docs/source-control.md` — pull request publication
- `docs/persistence.md` — checkpoints
- `docs/observability.md` — optional Langfuse boundary
- `docs/evals.md` — deterministic evals
- `docs/ci.md` — continuous integration
- `docs/terraform-credential-free-plan.md` — credential-free plan
- `docs/aws-plan-boundary.md` — OIDC plan boundary
- `docs/real-llm-intent-interpreter.md` — optional real model
- `docs/resources/s3.md`, `docs/resources/dynamodb.md`, `docs/resources/lambda.md`, `docs/resources/ecr.md`
- `docs/adr/2026-09-27-registry-catalog-deferred.md`

## Current boundary

The runtime is local. Compose publishes `127.0.0.1:8000:8000`.

Not started: RBAC, multi-user access, tenants, durable operator identity, approver audit, remote or public deployment, TLS, ingress, and a reverse proxy.

A pull request is the terminal artifact.
