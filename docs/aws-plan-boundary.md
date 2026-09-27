# AWS plan boundary / GitHub OIDC foundation (Batch 25)

See `docs/superpowers/specs/2026-09-26-aws-plan-boundary-oidc-foundation-design.md`
for the full trust-boundary design. This document is the operator
runbook for the two real, human-gated actions that design requires:
confirming this repository's actual OIDC claims, and applying the
bootstrap plane. Neither step is executed by `iac-agent-platform`
itself — both are performed by a human, outside this repository's own
CI.

## Step 1 — confirm the actual OIDC claims for this repository

Do not assume the `sub` claim format. GitHub changed the default
subject format for repositories created after 2026-07-15 to an
immutable `owner_id@repo_id` shape; this repository predates that date
and should retain the legacy `repo:ORG/REPO:pull_request` format
**unless** immutable subject claims were explicitly opted into — verify
this, do not assume it.

1. Add a temporary workflow (never `ci.yml` itself) running GitHub's
   own `github/actions-oidc-debugger` action on a `pull_request`
   trigger, requesting `id-token: write` only in that one job.
2. Open a throwaway PR to trigger it.
3. Record only the sanitized, decoded claim fields the action prints:
   `aud`, `sub`, `repository`, `repository_owner`, `event_name`, `ref`.
   Never record or persist the raw JWT.
4. Confirm the run did **not** reference a GitHub Environment (`ci.yml`
   has none today) — an `environment:` key would change the `sub`
   shape to include `environment:<name>` instead of `pull_request`.
5. Delete the temporary workflow and close the throwaway PR.
6. Set the confirmed `sub` value as `bootstrap/aws-oidc`'s
   `github_oidc_subject` variable (Step 2).

## Step 2 — apply the bootstrap plane

See `bootstrap/aws-oidc/README.md` for the exact `terraform
init/plan/apply` commands. This is run by a human, from their own
machine or a separate bootstrap pipeline — never by this repository's
CI, never by `TerraformRunner`. Record the resulting
`iac_plan_role_arn` output and set it as the `AWS_PLAN_ROLE_ARN`
repository variable (non-secret) in GitHub.

## Step 3 — enable the `aws-plan` CI job

Only after Steps 1–2 are complete and `AWS_PLAN_ROLE_ARN` is set: the
`aws-plan` job (implementation plan Task 13, human-gated) can be added
to `ci.yml`. It never runs automatically — it requires the `aws-plan`
label, an authorized-actor check, and the PR's head repository to be
this repository itself (never a fork).

## What this never does

No `terraform apply`, no `terraform destroy`, no AWS deployment, no
remote Terraform state. The AWS identity used for planning structurally
lacks mutation authority — see the design spec's own golden rule.
