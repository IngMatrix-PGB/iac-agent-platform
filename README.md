# iac-agent-platform

Agentic Infrastructure-as-Code Platform — natural-language infrastructure
intent turned into safe, deterministic, reviewable Terraform changes.

**Status:** Phase 1 (AWS SQS) is a working, validated vertical slice;
Phase 2 (AWS S3) is in progress, proving the same design generalizes to
a second resource type. Currently supported resources: **SQS queues
and S3 buckets** — not generic AWS support.

```
AWS resource spec (SQS queue or S3 bucket)
  → deterministic Terraform rendering
  → Terraform validation/plan (credential-free)
  → deterministic security policy + Checkov
  → durable human-in-the-loop approval
  → GitHub pull request
```

A request is only ever *proposed* as a reviewable pull request — it is
never deployed. See `docs/application.md`, `docs/hitl.md`,
`docs/source-control.md`, `docs/resources/s3.md`, and `docs/roadmap.md`
for the composition root, the approval gate, the GitHub adapter, the S3
resource, and the project roadmap respectively.

**Safety:** `terraform apply` is not part of this project's design and
does not exist anywhere in this codebase. No AWS resource is ever
created; a GitHub pull request is Phase 1's terminal artifact.
