# Bootstrap: GitHub OIDC provider + IaCPlanRole (Batch 25)

This module is **never applied by iac-agent-platform**. It is
human-applied reference source only — no code under `src/`, no CI
workflow, and no `TerraformRunner` invocation in this repository ever
runs `terraform apply` (or even `plan`) against this directory for
real. `iac-agent-platform` only ever *consumes* the resulting
`iac_plan_role_arn` output, as a plain, non-secret CI configuration
value (`AWS_PLAN_ROLE_ARN`).

The agent must never control the authority boundary that constrains it.
See `docs/aws-plan-boundary.md`.

## Before applying

1. This repository's `sub` claim is the exact subject in
   `docs/aws-plan-boundary.md`: the immutable-format
   `repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request`
   — never the legacy `repo:IngMatrix-PGB/iac-agent-platform:pull_request`
   shape (this repository was created after GitHub's 2026-07-15
   immutable-subject cutover, so the legacy shape never applied to it).
   If this module is ever reused for a **different** repository, do
   not reuse this value — repeat the discovery runbook for that
   repository instead.
2. Verify AWS's current guidance for the GitHub Actions OIDC provider
   thumbprint(s) at apply time (this has changed before).

## Applying (by a human, from their own machine or a separate bootstrap
pipeline — never from this repository's CI)

```bash
cd bootstrap/aws-oidc
terraform init
terraform plan \
  -var "aws_region=us-east-1" \
  -var "github_oidc_subject=repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request" \
  -var 'github_oidc_thumbprints=["<current AWS/GitHub guidance>"]'
terraform apply   # same -var flags
```

Record the `iac_plan_role_arn` output and set it as the
`AWS_PLAN_ROLE_ARN` repository variable (not a secret — role ARNs are
not sensitive) in `iac-agent-platform`'s GitHub repository settings.

## V3 trust migration (human, not yet applied)

V3 acceptance requires the role trust subject to be replaced. Do not
leave both subjects in the policy. The replacement value is:

```text
repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:environment:aws-plan
```

Audience stays `sts.amazonaws.com`, still `StringEquals`, still one
subject. Apply that change from a human workstation after the GitHub
Environment `aws-plan` exists and admits only `main`. The
`pull_request` subject above is the currently documented live value
until that human apply. This repository's workflows do not run
`terraform apply` in this directory.

The earlier OIDC smoke for the `pull_request` subject is federation
evidence only. It is not V3 acceptance.

## Extending the permissions policy

`policy/iac_plan_role_permissions.json` starts at the empirical
minimum (`sts:GetCallerIdentity` only). A profile run that receives
`AccessDenied` records the exact action when the error text includes
it, returns `AUTHORIZATION_ERROR`, and stops. A human then decides
whether that action is an acceptable non-mutating read. The workflow
does not classify the action by its name and does not attach
`ReadOnlyAccess`. After a human edits the policy file here, re-apply
this module (`terraform apply` again, same as above) for the change to
take effect in AWS.
