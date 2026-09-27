# ECR Repository (Phase 2, Batch 27)

ECR is a standalone resource, `ResourceType.ECR` (`"ecr"`). It is not a
composition. A container image registry is object storage's neighbor in
the `STORAGE` workload, and it is not object storage.

## Intent

`WorkloadType.STORAGE` plus exactly `{Capability.CONTAINER_REGISTRY}`
resolves to `EcrResourceSpec` for every interaction pattern. The matched
pattern is `storage+container_registry`. There is no clarification arm.

`OBJECT_STORAGE` still resolves to S3. A mixed set
(`CONTAINER_REGISTRY` with `OBJECT_STORAGE`, or with `PERSISTENCE`)
stays `UNSUPPORTED_CAPABILITY`. The deterministic resolver is
authoritative. The interpreter prompt (version 4) only teaches that
`container_registry` is not `object_storage`, and the reverse. Gate A
makes no OpenAI call.

## Contract

`iac_agent.providers.aws.ecr.contract.EcrResourceSpec`:

- `resource_type` is the literal `"ecr_repository"`.
- `name` uses the AWS CreateRepository regex, anchored, with length
  checked separately at 2–256:

  `^[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*(\/[a-z0-9]+((\.|_|__|-+)[a-z0-9]+)*)*$`

  A leading digit matches this regex. AWS provider 6.x accepted
  `name = "1orders"` in a credential-free `terraform plan` (one
  `aws_ecr_repository` create). The regex stands.
- `image_tag_mutability` defaults to `IMMUTABLE`. `MUTABLE` is allowed
  and warned. Exclusion-filter modes are not members.
- `scan_on_push` defaults to `True`.
- `EcrEncryptionSpec.enabled` defaults to `True` and rejects `False`
  (`encryption.enabled cannot be False`).
- No `kms_key_id`. No `force_delete`. No lifecycle policy.

## Policies

| Policy | Result |
|---|---|
| `ECR_ENCRYPTION_REQUIRED` | PASS when enabled (HIGH, platform policy). BLOCK only through `model_construct`, because a normal spec cannot disable encryption. |
| `ECR_SCAN_ON_PUSH_RECOMMENDED` | WARN when `scan_on_push` is false (MEDIUM). |
| `ECR_IMAGE_TAG_MUTABILITY_RECOMMENDED` | WARN when mutability is `MUTABLE` (MEDIUM). |

The required-ID tuple also includes `TF_NO_DESTRUCTIVE_CHANGES`.

## Terraform module

`terraform/modules/ecr/` contains one `aws_ecr_repository`.
`encryption_type = "AES256"` is hardcoded in the module. The root
module does not pass `encryption_type`, a KMS key, `force_delete`, or a
lifecycle policy. Existing trusted modules are unchanged. Gate A does
not run `terraform apply` or `terraform destroy`.

## Checkov

A zero-skip scan of the secure-default module (Checkov 3.3.13,
`resource_count=1`, `passed=3`, `failed=1`, `skipped=0`) produced one
finding:

- `CKV_AWS_136` — "Ensure that ECR repositories are encrypted using KMS."
  Accepted architectural trade-off. The module hardcodes `AES256` and
  Batch 27 does not add a KMS key. This is not a defect in the
  repository, and it is not a false positive: Checkov is asking for a
  customer-managed key that this batch refuses.

The frozen profile is `skipped_checks=("CKV_AWS_136",)`. No other id is
skipped. The list was not copied from S3, DynamoDB, Lambda, or API
Gateway.

## CLI

`_architecture_label()` no longer falls back to `"s3"`. Every
`ResourceType` has an explicit label, and an unknown standalone
resource fails at lookup. ECR's label is `ecr`. Component lines show
the repository name, `image_tag_mutability`, and `scan_on_push`.

## Non-goals

Lifecycle policy, repository policy, KMS, public ECR, registry-level
scanning (`aws_ecr_registry_scanning_configuration`), and `force_delete`
are out of this batch.

## Actual versus theoretical

Design inventory: 20 production dispatch/registration sites, 1
non-dispatch prompt site (`intent/adapters/openai.py`), and 24
test/eval rows. Gate B did not add a 21st dispatch site. `request.py`
stayed unchanged.

The 24 inventory rows all exist after Gate B, including
`tests/integration/test_ecr_renderer_terraform.py`,
`tests/integration/test_ecr_golden_real_tool_eval.py`, and
`tests/integration/test_ecr_workflow_persistence.py`. Three test/eval
files were outside that inventory:
`tests/unit/graph/test_state.py` (exact workflow-state union),
`tests/unit/intent/adapters/test_openai_adapter.py` (recorded prompt
version), and `evals/evaluators/architecture_intent_resolver.py`
(`EcrResourceSpec` in the resolved-type map). `ApiLambdaDynamoDbSpec`
is still absent from that map. That pre-existing hole did not block
ECR.

Omission behavior, from the tests that failed before the registration
existed:

- A missing `ResourceType` arm, renderer case, policy id, Checkov
  profile, module-directory entry, or display name fails loudly
  (`ValueError` or `KeyError`).
- Omitting the checkpoint allowlist does not raise. The recovered
  value is a `dict`. The unit round-trip and the fresh-process HITL
  test are what catch it.
- Omitting the `_component_lines` branch does not raise. The lines are
  `[]`. Only the dedicated CLI test catches that.
- The resolver golden evaluator ignores a `resolved_type` it does not
  map. ECR is mapped. An unmapped name would still pass on outcome and
  pattern alone.

A registry would mostly move the dicts and `match` arms that already
fail loudly. It would not, by itself, own checkpoint allowlisting or
CLI component lines. Those two silent spots already have dedicated
tests. No registry is implemented in this batch.
