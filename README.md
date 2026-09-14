# iac-agent-platform

Agentic Infrastructure-as-Code Platform — natural-language infrastructure
intent turned into safe, deterministic, reviewable Terraform changes.

**Status:** Phase 1 (AWS SQS only) is a working, validated vertical
slice:

```
SQS resource spec
  → deterministic Terraform rendering
  → Terraform validation/plan (credential-free)
  → deterministic security policy + Checkov
  → durable human-in-the-loop approval
  → GitHub pull request
```

A request is only ever *proposed* as a reviewable pull request — it is
never deployed. See `docs/application.md`, `docs/hitl.md`, and
`docs/source-control.md` for the composition root, the approval gate,
and the GitHub adapter respectively.

**Safety:** `terraform apply` is not part of this project's design and
does not exist anywhere in this codebase. No AWS resource is ever
created; a GitHub pull request is Phase 1's terminal artifact.
