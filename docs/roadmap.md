# Roadmap

## Phase 1 — SQS (complete)

A working, validated vertical slice for AWS SQS: contract → renderer →
Terraform plan (credential-free) → deterministic security policy →
Checkov → durable human-in-the-loop approval → GitHub pull request.
Golden dataset: 14 scenarios / 38 evaluations, 100% pass rate. No
`terraform apply`, no AWS mutation, ever. See `docs/application.md`,
`docs/hitl.md`, `docs/source-control.md`.

## Phase 2 — S3 (in progress)

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
- An explicit, narrowly-scoped Checkov skip list
  (`DEFAULT_SKIPPED_CHECKS`) for the four checks corresponding exactly
  to this batch's documented S3 scope exclusions — a project-owner
  decision, not a unilateral one.
- An S3 golden eval dataset (`evals/datasets/s3_golden.json`, 14
  scenarios) and parallel evaluators/loader/runner
  (`evals/evaluators/s3.py`, `evals/scenarios/s3_loader.py`,
  `evals/scenarios/s3_runner.py`).

## Known naming debt (tracked, not yet resolved)

`iac_agent.app.service.Phase1Application` and the surrounding
composition layer (`iac_agent.app.composition`,
`iac_agent.app.config`) are still SQS-only as of Batch 16 — they
construct `build_sqs_workflow` and a single SQS trusted-module path
directly, never `build_iac_workflow` or an S3-capable renderer. This is
a real gap (the graph layer one level below is already resource-neutral)
but a full generalization here would need `ApplicationConfig` to carry
a *mapping* of trusted module directories rather than one path, and
`submit()`'s type hint widened from `SQSResourceSpec` to
`AWSResourceSpec` — more churn than this batch's scope, and deferred
rather than rushed. Tracked here explicitly so it is not forgotten;
revisit when a third resource type or the first real caller (FastAPI
adapter, CLI) makes the gap unavoidable.

## Not yet started

DynamoDB, Lambda, IAM, a FastAPI/HTTP adapter, and any UI remain
entirely out of scope until a future phase is explicitly approved.
