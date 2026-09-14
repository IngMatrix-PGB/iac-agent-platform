# iac-agent-platform

Agentic Infrastructure-as-Code Platform — natural-language infrastructure
intent turned into safe, deterministic, reviewable Terraform changes.

**Status:** Phase 1 (AWS SQS) and Phase 2 (AWS S3, AWS DynamoDB) are
working, validated vertical slices, proving the same design
generalizes across resource types. Currently supported resources:
**SQS queues, S3 buckets, and DynamoDB tables** — not generic AWS
support.

```
AWS resource spec (SQS queue, S3 bucket, or DynamoDB table)
  → deterministic Terraform rendering
  → Terraform validation/plan (credential-free)
  → deterministic security policy + Checkov
  → durable human-in-the-loop approval
  → GitHub pull request
```

A request is only ever *proposed* as a reviewable pull request — it is
never deployed. See `docs/application.md`, `docs/hitl.md`,
`docs/source-control.md`, `docs/resources/s3.md`,
`docs/resources/dynamodb.md`, and `docs/roadmap.md` for the
composition root, the approval gate, the GitHub adapter, the S3
resource, the DynamoDB resource, and the project roadmap respectively.

**Safety:** `terraform apply` is not part of this project's design and
does not exist anywhere in this codebase. No AWS resource is ever
created; a GitHub pull request is Phase 1's terminal artifact.
