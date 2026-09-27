# Bootstrap: GitHub OIDC provider + IaCPlanRole (Batch 25)

This module is **never applied by iac-agent-platform**. It is
human-applied reference source only — no code under `src/`, no CI
workflow, and no `TerraformRunner` invocation in this repository ever
runs `terraform apply` (or even `plan`) against this directory for
real. `iac-agent-platform` only ever *consumes* the resulting
`iac_plan_role_arn` output, as a plain, non-secret CI configuration
value (`AWS_PLAN_ROLE_ARN`).

This separation is the core Batch 25 invariant: the agent must never
control the authority boundary that constrains it.

## Before applying

1. Confirm this repository's actual GitHub OIDC `sub` claim using the
   discovery runbook in `docs/aws-plan-boundary.md` — do not guess or
   reuse a value from another repository or from this module's own
   comments.
2. Verify AWS's current guidance for the GitHub Actions OIDC provider
   thumbprint(s) at apply time (this has changed before).

## Applying (by a human, from their own machine or a separate bootstrap
pipeline — never from this repository's CI)

```bash
cd bootstrap/aws-oidc
terraform init
terraform plan \
  -var "aws_region=us-east-1" \
  -var "github_oidc_subject=<value confirmed by the discovery runbook>" \
  -var 'github_oidc_thumbprints=["<current AWS/GitHub guidance>"]'
terraform apply   # same -var flags
```

Record the `iac_plan_role_arn` output and set it as the
`AWS_PLAN_ROLE_ARN` repository variable (not a secret — role ARNs are
not sensitive) in `iac-agent-platform`'s GitHub repository settings.

## Extending the permissions policy

`policy/iac_plan_role_permissions.json` starts at the empirical
minimum (`sts:GetCallerIdentity` only). Follow the discovery loop in
the design spec (§8) and the implementation plan (Task 14) exactly:
one `AccessDenied` at a time, one action added per commit, each with a
written justification — never a bulk grant, never
`AdministratorAccess`/`PowerUserAccess`/persistent `ReadOnlyAccess`.
After editing the policy file here, re-apply this module (`terraform
apply` again, same as above) for the change to take effect in AWS.
