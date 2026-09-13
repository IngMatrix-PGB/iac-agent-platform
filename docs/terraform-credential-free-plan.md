# Credential-free Terraform planning — verified evidence

This documents the Batch 3 reproducibility spike proving that
`terraform init` / `validate` / `plan` can run for the trusted SQS
module without a real AWS account, real credentials, or network access
to any AWS API.

## Why this matters

Anyone can clone this repository and exercise the full Terraform
pipeline (fmt → validate → plan → show) with nothing but Terraform
itself and internet access to the public Terraform Registry (to
download the AWS provider plugin). No AWS account is required to try
the project or to run its test suite / CI.

## How it works

The AWS provider is configured **only** in the root test fixture
(`tests/terraform/sqs/main.tf`), never inside the trusted module, with:

```hcl
provider "aws" {
  region = var.aws_region

  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
}
```

These four arguments were confirmed against the `hashicorp/aws` v6.64.0
provider documentation (not assumed from an older provider generation)
before use.

Terraform still requires *some* value for `AWS_ACCESS_KEY_ID` /
`AWS_SECRET_ACCESS_KEY` to satisfy the provider's credential chain, so
the runner (a later batch) supplies non-secret placeholder values
(`test` / `test`) **only via the process environment**, never written
into any tracked file. `skip_credentials_validation` and
`skip_requesting_account_id` mean these placeholder values are never
sent to AWS STS for verification — Terraform never actually reaches an
AWS API during `plan` for this configuration.

## Verified evidence (Batch 3)

Environment for every command below: `env -i PATH="$PATH" HOME="$HOME"
[AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test for plan]` — i.e. no
inherited shell environment, no `~/.aws` profile in use, no `AWS_*`
variables beyond the two dummy ones shown.

- Terraform version: `1.16.1`
- AWS provider resolved: `hashicorp/aws v6.64.0` (constraint `~> 6.0`)
- `terraform init -backend=false`: **exit 0** (no credentials present at
  all for this step)
- `terraform validate`: **exit 0** (no credentials present at all for
  this step)
- `terraform plan -var-file=scenarios/standard-dlq-enabled.tfvars -out=tfplan`:
  **exit 0**, `Plan: 2 to add, 0 to change, 0 to destroy`
  - `module.queue.aws_sqs_queue.this` — create
  - `module.queue.aws_sqs_queue.dlq[0]` — create
- All 7 valid scenario `.tfvars` files under `scenarios/` produced a
  successful plan (exit 0): `standard-dlq-enabled`,
  `standard-dlq-disabled`, `fifo-queue`, `sse-sqs-managed`, `sse-kms`,
  `boundary-min`, `boundary-max`.
- All 3 invalid scenario `.tfvars` files produced a deterministic
  **exit 1** at `terraform plan`, with the exact expected error:
  - `invalid-fifo-name-mismatch` → module `lifecycle.precondition`:
    *"fifo must be true if and only if name ends with '.fifo' ..."*
  - `invalid-numeric-out-of-range` → variable validation on
    `visibility_timeout_seconds`: *"visibility_timeout_seconds must be
    between 0 and 43200."*
  - `invalid-contradictory-dlq` → module `lifecycle.precondition`:
    *"max_receive_count must be set when dlq_enabled is true, and null
    when dlq_enabled is false."*

## Security properties confirmed from the plan JSON (`terraform show -json`)

- `standard-dlq-enabled`: both `aws_sqs_queue.this` and
  `aws_sqs_queue.dlq[0]` planned with `sqs_managed_sse_enabled = true`.
- `sse-kms`: both resources planned with
  `kms_master_key_id = "alias/aws/sqs"` and `sqs_managed_sse_enabled`
  unset — no code path produces a queue with encryption fully absent.
- `fifo-queue`: DLQ name is correctly derived as
  `order-processing-dlq.fifo` (FIFO suffix preserved on the DLQ too).
- `standard-dlq-disabled`: only `aws_sqs_queue.this` appears in
  `resource_changes` — no DLQ resource is planned at all.
- In every scenario, `aws_sqs_queue.this`'s `redrive_policy` expression
  references `aws_sqs_queue.dlq[0].arn` and `var.max_receive_count`
  (confirmed via `configuration.root_module.module_calls.queue.module`
  in the plan JSON) — the redrive policy is wired to the actual created
  DLQ, not a hardcoded/unrelated ARN.
- No `aws_iam_*` resource appears anywhere in the module or any plan.
- No `terraform apply` or `terraform destroy` was executed at any point
  in this spike.

## Limitation

This proves **plan-time** credential-freedom for *new resource
creation* only. It does not prove (and does not need to prove, for
Phase 1) that `plan` would succeed against **existing** infrastructure
state, which can require real read access to AWS to refresh prior
resources. Phase 1 never manages existing state — every request in
this project always plans a brand-new composition.
