# AWS plan boundary

This repository can render and plan Terraform. It does not apply or destroy it, and it does not create the AWS identity that a plan would assume.

A separate bootstrap module, `bootstrap/aws-oidc/`, is human-applied reference source for a GitHub OIDC role. Nothing under `src/`, the CI workflow, or `TerraformRunner` applies that module. The agent does not manage the authority boundary that would constrain it.

## Build CI

GitHub Actions for ordinary integration triggers on `pull_request` to `main` and on `push` to `main` (`.github/workflows/ci.yml`).

`pull_request_target` is not used. The CI workflow's token permission is `contents: read`. It does not request `id-token: write`. It does not contain an `aws-plan` job. Plans produced by that workflow stay credential-free, as described in `docs/terraform-credential-free-plan.md`.

## V3 real plan

V3 is `.github/workflows/aws-plan.yml`. It is `workflow_dispatch` only. It is not part of build CI and it does not replace the credential-free proposal plan.

Job `prepare` has `contents: read` and no AWS identity. Job `plan` needs `prepare`, uses the GitHub Environment `aws-plan`, and is the only job with `id-token: write`. It verifies the handoff artifact before `configure-aws-credentials`. The role session is requested for 900 seconds. Unsetting variables in a later step does not revoke that session.

The fixed target is account `891377250201`, region `us-east-1`, and role `arn:aws:iam::891377250201:role/IaCPlanRole`. The workflow does not apply or destroy.

## Environment gate

The name `aws-plan` in the workflow file does not create the environment. A human must create it with deployment branches limited to `main` and with required reviewers. No V3 environment secrets are required. `python -m iac_agent.aws_plan check-environment` reads a normalized description of that configuration and returns `ready` or `blocked`. It is not called from CI.

## Claim shape

The audience condition is `sts.amazonaws.com`. Trust is one exact `StringEquals` subject, not a wildcard.

The earlier OIDC smoke proved federation for this subject:

```text
repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request
```

That smoke is not V3 acceptance. The V3 subject, after a human trust migration, is:

```text
repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:environment:aws-plan
```

The `pull_request` subject is removed in that same human update. A different repository must not reuse either subject.

## What remains a human action

Creating the GitHub Environment, replacing the trust subject, and adding any SQS read action to `IaCPlanRole` are human actions. An `AccessDenied` from a profile dispatch is candidate evidence. The workflow records the action when it can parse it and stops. It does not decide whether the action is safe, and it does not edit the role.

No `terraform apply` and no `terraform destroy` are part of this boundary.
