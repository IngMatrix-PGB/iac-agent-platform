# Bootstrap: IaCPlanRole

This module is **never applied by iac-agent-platform**. It is
human-applied reference source only — no code under `src/`, no CI
workflow, and no `TerraformRunner` invocation in this repository ever
runs `terraform apply` (or even `plan`) against this directory for
real. `iac-agent-platform` only ever *consumes* the resulting
`iac_plan_role_arn` output, as a plain, non-secret CI configuration
value (`AWS_PLAN_ROLE_ARN`).

The agent must never control the authority boundary that constrains it.
See `docs/aws-plan-boundary.md`.

The GitHub Actions OIDC provider is an account-level prerequisite. It
must already exist for `https://token.actions.githubusercontent.com`.
This module does not create that provider. It reads the existing
provider and creates only `IaCPlanRole` and its inline permissions
policy.

## Before applying

The role trusts one exact `sub` claim, documented in
`docs/aws-plan-boundary.md`:

```text
repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request
```

The audience condition is `sts.amazonaws.com`. Both conditions are
`StringEquals`. A different repository must use its own subject.

## Applying (by a human, from their own machine or a separate bootstrap
pipeline — never from this repository's CI)

```bash
cd bootstrap/aws-oidc
terraform init
terraform plan \
  -var "aws_region=us-east-1" \
  -var "github_oidc_subject=repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request"
terraform apply   # same -var flags
```

Record the `iac_plan_role_arn` output and set it as the
`AWS_PLAN_ROLE_ARN` repository variable (not a secret — role ARNs are
not sensitive) in `iac-agent-platform`'s GitHub repository settings.

## Extending the permissions policy

`policy/iac_plan_role_permissions.json` starts at `sts:GetCallerIdentity`
only. Add one action per change, after a real plan reports
`AccessDenied` for that action, with a written justification. Do not
grant `AdministratorAccess`, `PowerUserAccess`, or a standing
`ReadOnlyAccess`. After editing the policy file here, a human re-applies
this module for the change to take effect in AWS.
