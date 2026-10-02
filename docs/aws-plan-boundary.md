# AWS plan boundary

This repository can render and plan Terraform. It does not apply or destroy it, and it does not create the AWS identity that a plan would assume.

A separate bootstrap module, `bootstrap/aws-oidc/`, is human-applied reference source for a GitHub OIDC role. Nothing under `src/`, the CI workflow, or `TerraformRunner` applies that module. The agent does not manage the authority boundary that would constrain it.

## Repository trust boundary

GitHub Actions for this repository triggers on `pull_request` to `main` and on `push` to `main`.

`pull_request_target` is not used. That event would run workflow code in the base repository's trust context against a pull request head, including a head the base repository does not control. The CI workflow must not gain that event. A unit test asserts the string `pull_request_target` does not appear in `.github/workflows/ci.yml`.

The workflow's token permission is `contents: read`. It does not request `id-token: write`, pull-request write, or a secret.

## Fork constraint

A future job that assumes an AWS plan role must run only when the pull request head repository is this repository. A fork pull request must not receive that role, even if it carries a label. OIDC `id-token` permission is a workflow grant, not a secret, so the event type and the head-repository check are what keep a fork from assuming the role.

The current CI workflow does not assume an AWS role.

## Claim shape

The bootstrap role trusts one exact GitHub OIDC subject. It is not a wildcard and it is not an OR of the legacy and current formats.

For a `pull_request` event on this repository the confirmed subject is:

```text
repo:IngMatrix-PGB@167713460/iac-agent-platform@1368782253:pull_request
```

The audience condition is `sts.amazonaws.com`. The subject ends in `:pull_request`, not an environment name. A different repository must not reuse this subject.

## What remains outside this repository

Applying `bootstrap/aws-oidc/` and enabling a labeled `aws-plan` job are human actions. They are not performed by CI here, and they are not performed by `TerraformRunner`. Until a human does that work, this platform's plans stay credential-free, as described in `docs/terraform-credential-free-plan.md`.

No `terraform apply` and no `terraform destroy` are part of this boundary.
