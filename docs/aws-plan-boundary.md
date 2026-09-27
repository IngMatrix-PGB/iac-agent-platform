# AWS plan boundary / GitHub OIDC foundation (Batch 25)

See `docs/superpowers/specs/2026-09-26-aws-plan-boundary-oidc-foundation-design.md`
for the full trust-boundary design. This document is the operator
runbook for the two real, human-gated actions that design requires:
confirming this repository's actual OIDC claims, and applying the
bootstrap plane. Neither step is executed by `iac-agent-platform`
itself — both are performed by a human, outside this repository's own
CI.

## Current status (2026-09-26)

| Layer | Status |
|---|---|
| A. Structurally/deterministically proven (Gate A/B — Tasks 1–10) | ✅ **Complete.** Bootstrap Terraform module, frozen empirical-minimum IAM policy, CI-owned provider override, `aws-plan` job contract (pre-committed, `xfail` until Task 13), no-self-management regression tests, real (credential-free) `terraform fmt/init/validate/plan` against the bootstrap module — all merged to `feat/batch25-aws-plan-boundary`. |
| B. Empirically proven against real GitHub OIDC (Gate C, part 1 — Task 11) | ✅ **Complete.** Step 1 below — real, observed `aud`/`sub` claims from a real workflow run, not assumed. |
| C. Requires an authorized AWS sandbox (Gate C parts 2–3, Gate D, Gate E — Tasks 12–16) | ⏸ **Deferred.** No personal/lab AWS account has been authorized yet (ClubHub corporate account `891377250201`, under any profile, is explicitly excluded from this scope). Steps 2–3 below, and everything past them, cannot proceed until one is provided. |

This is an external-integration constraint, not a defect in the Batch
25 implementation: everything that can be proven without a real,
authorized AWS account has been proven, and nothing beyond that has
been claimed or fabricated.

## Step 1 — confirm the actual OIDC claims for this repository

**Status: done (Batch 25, Task 11, 2026-09-26).** Do not assume the
`sub` claim format from a repository's age alone. GitHub changed the
default subject format for repositories created after 2026-07-15 to
an immutable `owner_id@repo_id` shape. This repository's `created_at`
is `2026-09-13T19:18:45Z` — *after* that cutover, not before — so it
was never eligible for the legacy `repo:ORG/REPO:pull_request` format.
This was verified empirically, not assumed:

1. Added a temporary workflow (never `ci.yml` itself),
   `.github/workflows/oidc-claim-debugger.yml`, on a `pull_request`
   trigger, requesting `id-token: write` only in that one job. The
   plan originally specified GitHub's `github/actions-oidc-debugger`
   action, but that action was found **archived** (2025-09-22,
   read-only) before use and was not depended on; the workflow
   instead requests and decodes the OIDC token directly via GitHub's
   own documented `ACTIONS_ID_TOKEN_REQUEST_URL`/
   `ACTIONS_ID_TOKEN_REQUEST_TOKEN` mechanism, in Python
   (`shell: python3 {0}`) — the raw JWT is never echoed, logged, or
   persisted, only the decoded, non-secret claim subset.
2. Opened a throwaway PR (#7) to trigger it.
3. Recorded only the sanitized, decoded claim fields printed:
   `aud`, `sub`, `repository`, `repository_owner`, `repository_id`,
   `repository_owner_id`, `event_name`, `ref`, `workflow_ref`,
   `job_workflow_ref`, `iss`. The raw JWT was never recorded or
   persisted.
4. Confirmed the run did **not** reference a GitHub Environment
   (`ci.yml` has none today) — the observed `sub` ends in
   `:pull_request`, not `:environment:<name>`.
5. Deleted the temporary workflow, its branch, and closed the
   throwaway PR (#7) once this evidence was preserved here and in the
   design spec §5.
6. **Confirmed `sub` for this repository (`pull_request` event):**
   ```
   repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request
   ```
   This is now the exact, authoritative value for
   `bootstrap/aws-oidc`'s `github_oidc_subject` variable (Step 2) —
   never the legacy shape, never a wildcard, never an OR of both
   formats. The recorded `job_workflow_ref` above belonged to this
   *temporary* discovery workflow only and must never be copied into
   the production trust policy or used as a workflow-pinning
   condition.

## Step 2 — apply the bootstrap plane

**Status: DEFERRED — authorized personal/lab AWS account required.**
As of 2026-09-26, the only AWS credentials available resolve to
ClubHub corporate account `891377250201` (profiles `no-prod` and
`iac-agent-lab`, both explicitly excluded — this account is outside
`iac-agent-platform`'s authority boundary, an employer-owned account,
not a personal/lab sandbox for this portfolio project). No `terraform
plan` or `apply` has been run against any real AWS account for this
module.

See `bootstrap/aws-oidc/README.md` for the exact `terraform
init/plan/apply` commands to use once an authorized account is
available. This is run by a human, from their own machine or a
separate bootstrap pipeline — never by this repository's CI, never by
`TerraformRunner`. Record the resulting `iac_plan_role_arn` output and
set it as the `AWS_PLAN_ROLE_ARN` repository variable (non-secret) in
GitHub.

## Step 3 — enable the `aws-plan` CI job

**Status: DEFERRED** — blocked on Step 2. Only after Steps 1–2 are
complete and `AWS_PLAN_ROLE_ARN` is set: the `aws-plan` job
(implementation plan Task 13, human-gated) can be added to `ci.yml`.
It never runs automatically — it requires the `aws-plan` label, an
authorized-actor check, and the PR's head repository to be this
repository itself (never a fork).

## What this never does

No `terraform apply`, no `terraform destroy`, no AWS deployment, no
remote Terraform state. The AWS identity used for planning structurally
lacks mutation authority — see the design spec's own golden rule.
